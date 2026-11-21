"""Orquestra tentativas de sync de artigos sem acoplar ao backend do índice.

O serviço de ING-03/04 fornece ``sync_articles``. ING-05 usa este coordenador
para registrar tentativas e resultados e compartilhar o mesmo caminho entre
startup e comando manual.
"""

from collections.abc import Callable, Mapping
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from time import monotonic
from typing import Any, Literal, Protocol

from src.glpi_integration.GLPI_Client import GLPICollection
from src.rag.embeddings import EmbeddingService
from src.rag.local_index import LocalIndexStore
from src.rag.sync import CollectionBatch as IndexCollectionBatch
from src.rag.sync import reconcile_store_with_manifest, run_sync


SyncTrigger = Literal["startup", "manual"]
SyncStatus = Literal["running", "published", "no_changes", "failed"]
SourceAPIStatus = Literal["unknown", "available", "unavailable"]


class SyncAlreadyRunningError(RuntimeError):
    """Outra API/CLI já mantém o lock de sincronização dos artigos."""


class SyncProcessLock:
    """Lock SQLite entre processos, mantido por uma transação curta e exclusiva."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def hold(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path, timeout=0, isolation_level=None
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            connection.close()
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise SyncAlreadyRunningError(
                    "Já existe uma sincronização de artigos em andamento."
                ) from exc
            raise

        try:
            yield
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


@dataclass(frozen=True)
class ArticleSyncReport:
    """Resultado de uma atualização concluída pelo serviço de indexação."""

    status: Literal["published", "no_changes"]
    active_generation: str
    previous_generation: str | None
    checked_at: str
    published_at: str | None
    index_config: Mapping[str, Any]
    sources_total: int
    chunks_total: int

    def __post_init__(self) -> None:
        if self.status not in {"published", "no_changes"}:
            raise ValueError("status deve ser 'published' ou 'no_changes'.")
        if not isinstance(self.active_generation, str) or not self.active_generation.strip():
            raise ValueError("active_generation deve ser uma string não vazia.")
        if not isinstance(self.checked_at, str) or not self.checked_at.strip():
            raise ValueError("checked_at deve ser uma string não vazia.")
        if not isinstance(self.index_config, Mapping):
            raise TypeError("index_config deve ser um mapeamento.")
        for name in ("sources_total", "chunks_total"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} deve ser um inteiro não negativo.")


class ArticleSyncEngine(Protocol):
    """Interface esperada do serviço de reconstrução de ING-03/04."""

    @property
    def index_config(self) -> Mapping[str, Any]: ...

    def sync_articles(self, *, trigger: SyncTrigger) -> ArticleSyncReport: ...


def make_glpi_article_collector(
    client_factory: Callable[[], Any] | None = None,
) -> Callable[[], IndexCollectionBatch]:
    """Cria coleta tipada, preservando a evidência de paginação completa.

    `client_factory` é injetável para integração e execução manual controlada.
    No uso normal, o cliente é criado para cada tentativa para renovar
    autenticação com a configuração atual.
    """
    if client_factory is None:
        def client_factory():
            from scripts.coletar_dados import create_client

            return create_client()

    def collect() -> IndexCollectionBatch:
        collection = client_factory().search_all("/Knowledgebase/Article")
        if not isinstance(collection, GLPICollection):
            raise TypeError("A coleta de artigos não retornou GLPICollection.")

        articles = []
        for raw in collection:
            if not isinstance(raw, dict):
                raise TypeError("A coleta de artigos contém um registro inválido.")
            article = dict(raw)
            title = article.get("title")
            if not isinstance(title, str) or not title.strip():
                title = article.get("name")
            if article.get("eligible") is not False and article.get("is_deleted") is not True:
                article_id = article.get("id")
                content = article.get("content")
                if type(article_id) is not int or article_id < 0:
                    raise ValueError("A coleta de artigos contém um ID inválido.")
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("A coleta de artigos contém um título inválido.")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("A coleta de artigos contém um corpo inválido.")
            article["title"] = title
            article["source_reference"] = "/Knowledgebase/Article"
            articles.append(article)

        complete = (
            collection.complete is True
            and type(collection.total) is int
            and collection.total == len(collection)
        )
        return IndexCollectionBatch(articles=articles, is_complete=complete)

    return collect


class LocalArticleSyncEngine:
    """Adapta ING-04 `run_sync` à interface única consumida pela ING-05."""

    def __init__(
        self,
        *,
        store: LocalIndexStore,
        collect_fn: Callable[[], IndexCollectionBatch],
        encoder: EmbeddingService,
        manifest_path: str | Path | None = None,
    ):
        if store.source_type != "article":
            raise ValueError("LocalArticleSyncEngine exige LocalIndexStore de artigos.")
        if store.embedding != encoder.config:
            raise ValueError("Configuração do encoder difere da configuração do índice.")
        self.store = store
        self.collect_fn = collect_fn
        self.encoder = encoder
        self.manifest_path = Path(manifest_path) if manifest_path is not None else None
        self.source_api_status: SourceAPIStatus = "unknown"

    @property
    def index_config(self) -> Mapping[str, Any]:
        return asdict(self.store.embedding)

    def sync_articles(self, *, trigger: SyncTrigger) -> ArticleSyncReport:
        if trigger not in {"startup", "manual"}:
            raise ValueError("trigger deve ser 'startup' ou 'manual'.")
        self.source_api_status = "unknown"

        manifest_path = self.manifest_path or (self.store.directory / "sync_manifest.json")
        reconcile_store_with_manifest(self.store, manifest_path)

        def collect() -> IndexCollectionBatch:
            try:
                batch = self.collect_fn()
            except Exception:
                self.source_api_status = "unavailable"
                raise
            if not isinstance(batch, IndexCollectionBatch):
                self.source_api_status = "unavailable"
                raise TypeError("A coleta não retornou CollectionBatch.")
            if type(batch.is_complete) is not bool:
                self.source_api_status = "unavailable"
                raise TypeError("A coleta não informou completude como booleano.")
            self.source_api_status = (
                "available" if batch.is_complete else "unavailable"
            )
            return batch

        result = run_sync(
            store=self.store,
            collect_fn=collect,
            prepare_fn=lambda article: self.encoder.prepare_source(
                article, source_type="article"
            ),
            encode_fn=self.encoder.encode_chunks,
            manifest_path=manifest_path,
        )
        generation = self.store.generation_info(result.generation)
        return ArticleSyncReport(
            status=result.status,
            active_generation=result.generation,
            previous_generation=result.previous_generation,
            checked_at=result.checked_at,
            published_at=result.published_at,
            index_config=asdict(self.store.embedding),
            sources_total=generation.source_count,
            chunks_total=result.chunks_total,
        )


@dataclass(frozen=True)
class SyncRun:
    run_id: int
    trigger: SyncTrigger
    status: SyncStatus
    started_at: str
    finished_at: str | None
    duration_seconds: float | None
    active_generation: str | None
    previous_generation: str | None
    checked_at: str | None
    published_at: str | None
    index_config: dict[str, Any] | None
    sources_total: int | None
    chunks_total: int | None
    error_code: str | None
    source_api_status: SourceAPIStatus


class SyncRunLedger:
    """Histórico operacional separado dos arquivos publicados do índice."""

    @staticmethod
    def read_observation(path: str | Path, generation_id: str):
        """Lê a tentativa e o sucesso da geração capturada, sem criar/migrar DB.

        Uma transação de leitura mantém as duas observações coerentes. Não
        consulta ACTIVE nem inicia sincronização. Arquivo ausente retorna None.
        """
        path = Path(path).resolve()
        if not path.is_file():
            return None, None
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            latest = db.execute(
                "SELECT * FROM article_sync_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            success = db.execute(
                "SELECT * FROM article_sync_runs WHERE active_generation = ? "
                "AND status IN ('published', 'no_changes') ORDER BY run_id DESC LIMIT 1",
                (generation_id,),
            ).fetchone()

        def convert(row):
            if row is None:
                return None
            values = dict(row)
            values.pop("scope")
            raw_config = values.pop("index_config_json")
            values["index_config"] = json.loads(raw_config) if raw_config else None
            return SyncRun(**values)

        return convert(latest), convert(success)

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS article_sync_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL CHECK (scope = 'articles'),
                    trigger TEXT NOT NULL CHECK (trigger IN ('startup', 'manual')),
                    status TEXT NOT NULL CHECK (status IN ('running', 'published', 'no_changes', 'failed')),
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_seconds REAL,
                    active_generation TEXT,
                    previous_generation TEXT,
                    checked_at TEXT,
                    published_at TEXT,
                    index_config_json TEXT,
                    sources_total INTEGER,
                    chunks_total INTEGER,
                    error_code TEXT,
                    source_api_status TEXT NOT NULL DEFAULT 'unknown'
                )
                """
            )
            columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(article_sync_runs)")
            }
            if "source_api_status" not in columns:
                db.execute(
                    "ALTER TABLE article_sync_runs ADD COLUMN "
                    "source_api_status TEXT NOT NULL DEFAULT 'unknown'"
                )

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            with db:
                yield db

    def begin(
        self,
        trigger: SyncTrigger,
        started_at: str,
        index_config: Mapping[str, Any],
    ) -> int:
        with self._db() as db:
            previous = db.execute(
                """
                SELECT active_generation, published_at
                FROM article_sync_runs
                WHERE active_generation IS NOT NULL
                ORDER BY run_id DESC LIMIT 1
                """
            ).fetchone()
            active_generation, published_at = previous or (None, None)
            cursor = db.execute(
                """
                INSERT INTO article_sync_runs (
                    scope, trigger, status, started_at,
                    active_generation, published_at, index_config_json
                ) VALUES ('articles', ?, 'running', ?, ?, ?, ?)
                """,
                (
                    trigger,
                    started_at,
                    active_generation,
                    published_at,
                    json.dumps(dict(index_config), sort_keys=True),
                ),
            )
            return int(cursor.lastrowid)

    def finish(
        self,
        run_id: int,
        report: ArticleSyncReport,
        *,
        finished_at: str,
        duration_seconds: float,
        source_api_status: SourceAPIStatus,
    ) -> None:
        with self._db() as db:
            db.execute(
                """
                UPDATE article_sync_runs SET
                    status = ?, finished_at = ?, duration_seconds = ?,
                    active_generation = ?, previous_generation = ?, checked_at = ?,
                    published_at = ?, index_config_json = ?, sources_total = ?,
                    chunks_total = ?, error_code = NULL, source_api_status = ?
                WHERE run_id = ?
                """,
                (
                    report.status,
                    finished_at,
                    duration_seconds,
                    report.active_generation,
                    report.previous_generation,
                    report.checked_at,
                    report.published_at,
                    json.dumps(dict(report.index_config), sort_keys=True),
                    report.sources_total,
                    report.chunks_total,
                    source_api_status,
                    run_id,
                ),
            )

    def fail(
        self,
        run_id: int,
        *,
        finished_at: str,
        duration_seconds: float,
        error_code: str,
        source_api_status: SourceAPIStatus,
    ) -> None:
        with self._db() as db:
            db.execute(
                """
                UPDATE article_sync_runs SET
                    status = 'failed', finished_at = ?, duration_seconds = ?,
                    error_code = ?, source_api_status = ?
                WHERE run_id = ?
                """,
                (finished_at, duration_seconds, error_code, source_api_status, run_id),
            )

    def get(self, run_id: int) -> SyncRun:
        with self._db() as db:
            row = db.execute(
                """
                SELECT run_id, trigger, status, started_at, finished_at,
                       duration_seconds, active_generation, previous_generation,
                       checked_at, published_at, index_config_json, sources_total,
                       chunks_total, error_code, source_api_status
                FROM article_sync_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"Execução de sync {run_id} não encontrada.")
        values = list(row)
        values[10] = json.loads(values[10]) if values[10] is not None else None
        return SyncRun(*values)

    def latest(self) -> SyncRun | None:
        with self._db() as db:
            row = db.execute(
                "SELECT run_id FROM article_sync_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
        return self.get(int(row[0])) if row else None

    def latest_success(self) -> SyncRun | None:
        with self._db() as db:
            row = db.execute(
                """
                SELECT run_id FROM article_sync_runs
                WHERE status IN ('published', 'no_changes')
                ORDER BY run_id DESC LIMIT 1
                """
            ).fetchone()
        return self.get(int(row[0])) if row else None


class ArticleSyncCoordinator:
    """Executa e registra sync de artigos para startup ou comando manual."""

    def __init__(
        self,
        engine: ArticleSyncEngine,
        ledger: SyncRunLedger,
        process_lock: SyncProcessLock | None = None,
    ):
        self.engine = engine
        self.ledger = ledger
        self.process_lock = process_lock or SyncProcessLock(
            ledger.path.with_name("article_sync.lock.sqlite3")
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def run(self, trigger: SyncTrigger) -> SyncRun:
        if trigger not in {"startup", "manual"}:
            raise ValueError("trigger deve ser 'startup' ou 'manual'.")

        started_at = self._now()
        started_clock = monotonic()
        index_config = getattr(self.engine, "index_config", {})
        if not isinstance(index_config, Mapping):
            index_config = {}
        run_id = self.ledger.begin(trigger, started_at, index_config)
        source_api_status: SourceAPIStatus = "unknown"
        engine_started = False
        try:
            with self.process_lock.hold():
                engine_started = True
                report = self.engine.sync_articles(trigger=trigger)
                source_api_status = self._source_api_status()
            duration = max(0.0, monotonic() - started_clock)
            self.ledger.finish(
                run_id,
                report,
                finished_at=self._now(),
                duration_seconds=duration,
                source_api_status=source_api_status,
            )
        except Exception as exc:
            if engine_started:
                source_api_status = self._source_api_status()
            duration = max(0.0, monotonic() - started_clock)
            # Persist only the exception type; messages can contain URLs or secrets.
            self.ledger.fail(
                run_id,
                finished_at=self._now(),
                duration_seconds=duration,
                error_code=type(exc).__name__,
                source_api_status=source_api_status,
            )
        return self.ledger.get(run_id)

    def _source_api_status(self) -> SourceAPIStatus:
        value = getattr(self.engine, "source_api_status", "unknown")
        return value if value in {"unknown", "available", "unavailable"} else "unknown"


def build_default_article_sync_coordinator() -> ArticleSyncCoordinator:
    """Constrói o runtime padrão compartilhado pela API e pelo CLI."""
    from src.config import INDEX_DIR

    encoder = EmbeddingService()
    store = LocalIndexStore(INDEX_DIR, "article", embedding=encoder.config)
    engine = LocalArticleSyncEngine(
        store=store,
        collect_fn=make_glpi_article_collector(),
        encoder=encoder,
    )
    ledger = SyncRunLedger(INDEX_DIR.parent / "article_sync_runs.sqlite3")
    process_lock = SyncProcessLock(INDEX_DIR.parent / "article_sync.lock.sqlite3")
    return ArticleSyncCoordinator(engine, ledger, process_lock)
