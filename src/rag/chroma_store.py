
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock
import chromadb
import numpy as np
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))



from src.rag.chroma_config import IndexConfig
from src.rag.chunk_contract import PREPARATION_VERSION, PreparedChunk
from src.rag.embeddings import IncompatibleConfig, validate_chunks, validate_vectors

_BATCH = 1000
_SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,              -- building | complete | retired
    config_json TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    source_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    collection TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
    generation INTEGER NOT NULL REFERENCES generations(id),
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    source_reference TEXT NOT NULL,
    title TEXT NOT NULL,
    chunk_ids_json TEXT NOT NULL,
    PRIMARY KEY (generation, source_type, source_id)
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class IncompatibleIndex(IncompatibleConfig):
    """Vetores ou configuração da geração não combinam com a configuração do armazenamento."""


class GenerationNotFound(LookupError):
    """A geração não existe (ou já foi removida pela limpeza)."""


class NoActiveGeneration(RuntimeError):
    """Nenhuma geração foi ativada ainda."""


class CorruptGeneration(RuntimeError):
    """Controle e coleção Chroma divergem (contagem, métrica ou coleção ausente)."""


@dataclass(frozen=True)
class GenerationInfo:
    generation: int
    status: str
    config: IndexConfig
    chunk_count: int
    source_count: int
    created_at: str
    active: bool


@dataclass(frozen=True)
class GenerationSnapshot:
    info: GenerationInfo
    chunks: tuple[dict, ...]
    vectors: np.ndarray


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _collection_name(generation: int) -> str:
    return f"chunks_g{generation:06d}"


class ChromaGenerationStore:
    def __init__(self, persist_dir: str | Path, config: IndexConfig):
        if not isinstance(config, IndexConfig):
            raise TypeError("config deve ser IndexConfig.")
        self.config = config
        self._dir = Path(persist_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "control.sqlite3"
        self._client = chromadb.PersistentClient(path=str(self._dir / "chroma"))
        self._lock = RLock()
        self._leases: dict[int, int] = {}
        self._in_flight: set[int] = set()
        with self._db() as db:
            db.executescript(_SCHEMA)

    # ------------------------------------------------------------------ controle
    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self._db_path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def _active_id(self, db) -> int | None:
        row = db.execute("SELECT value FROM state WHERE key = 'active'").fetchone()
        return int(row["value"]) if row else None

    def _info(self, row, active_id) -> GenerationInfo:
        return GenerationInfo(
            generation=row["id"], status=row["status"],
            config=IndexConfig.from_dict(json.loads(row["config_json"])) if row["config_json"] != "{}" else None,
            chunk_count=row["chunk_count"], source_count=row["source_count"],
            created_at=row["created_at"], active=row["id"] == active_id,
        )

    def _row(self, db, generation: int):
        row = db.execute("SELECT * FROM generations WHERE id = ? AND status != 'retired'", (generation,)).fetchone()
        if row is None:
            raise GenerationNotFound(f"Geração {generation} não existe.")
        return row

    def _require_compatible(self, info: GenerationInfo) -> None:
        if info.config != self.config:
            raise IncompatibleIndex(
                f"Geração {info.generation} foi criada com outra configuração de embeddings/índice; "
                "recrie a geração com a configuração atual."
            )

    def _require_complete(self, info: GenerationInfo) -> None:
        if info.status != "complete":
            raise ValueError(f"Geração {info.generation} não está completa (status: {info.status}).")

    def generations(self) -> list[GenerationInfo]:
        with self._db() as db:
            active = self._active_id(db)
            rows = db.execute("SELECT * FROM generations WHERE status != 'retired' ORDER BY id").fetchall()
            return [self._info(row, active) for row in rows]

    def generation_info(self, generation: int) -> GenerationInfo:
        with self._db() as db:
            return self._info(self._row(db, generation), self._active_id(db))

    def sources(self, generation: int) -> list[dict]:
        with self._db() as db:
            self._row(db, generation)
            rows = db.execute("SELECT * FROM sources WHERE generation = ? ORDER BY source_type, source_id",
                              (generation,)).fetchall()
        return [{"source_type": r["source_type"], "source_id": r["source_id"],
                 "source_reference": r["source_reference"], "title": r["title"],
                 "chunk_ids": json.loads(r["chunk_ids_json"])} for r in rows]

    def active_generation(self) -> int | None:
        with self._db() as db:
            return self._active_id(db)

    # ------------------------------------------------------------------ criação
    def create_candidate(
        self, chunks: Iterable[PreparedChunk], vectors=None, *,
        encode_missing: Callable[[list[PreparedChunk]], np.ndarray] | None = None,
        reuse_from: int | None = None,
    ) -> int:
        """Cria uma geração completa (tudo ou nada) sem ativá-la; devolve seu número.

        `vectors` alinha-se a `chunks`. Sem `vectors`, trechos de `reuse_from` com o mesmo
        chunk_id e conteúdo têm o vetor copiado, e os demais vão a `encode_missing`.
        """
        checked = validate_chunks(chunks)
        dimension = self.config.dimension
        if vectors is not None:
            matrix = validate_vectors(vectors, len(checked), dimension)
        else:
            matrix = self._resolve_vectors(checked, encode_missing, reuse_from)
        sources = self._source_records(checked)

        with self._lock:
            with self._db() as db:
                cursor = db.execute(
                    "INSERT INTO generations (status, config_json, chunk_count, source_count, created_at, collection)"
                    " VALUES ('building', ?, ?, ?, ?, '')",
                    (json.dumps(self.config.to_dict()), len(checked), len(sources),
                     datetime.now(timezone.utc).isoformat()),
                )
                generation = cursor.lastrowid
                db.execute("UPDATE generations SET collection = ? WHERE id = ?",
                           (_collection_name(generation), generation))
            self._in_flight.add(generation)
        name = _collection_name(generation)
        try:
            collection = self._client.create_collection(
                name, configuration={"hnsw": {"space": self.config.metric}}, embedding_function=None,
            )
            for start in range(0, len(checked), _BATCH):
                batch = checked[start:start + _BATCH]
                collection.add(
                    ids=[c["chunk_id"] for c in batch],
                    embeddings=matrix[start:start + _BATCH].tolist(),
                    documents=[c["content"] for c in batch],
                    metadatas=[{"source_type": c["source_type"], "source_id": c["source_id"],
                                "position": start + i, "content_hash": _hash(c["content"])}
                               for i, c in enumerate(batch)],
                )
            if collection.count() != len(checked):
                raise CorruptGeneration("A coleção não contém todos os trechos enviados.")
            with self._db() as db:
                db.executemany(
                    "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
                    [(generation, s["source_type"], s["source_id"], s["source_reference"], s["title"],
                      json.dumps(s["chunk_ids"])) for s in sources],
                )
                db.execute("UPDATE generations SET status = 'complete' WHERE id = ?", (generation,))
        except BaseException:
            self._discard(generation)
            raise
        finally:
            with self._lock:
                self._in_flight.discard(generation)
        return generation

    def _resolve_vectors(self, chunks, encode_missing, reuse_from) -> np.ndarray:
        reused: dict[str, np.ndarray] = {}
        if reuse_from is not None:
            snapshot = self.read_generation(reuse_from)  # exige completa e compatível
            wanted = {c["chunk_id"]: _hash(c["content"]) for c in chunks}
            for chunk, vector in zip(snapshot.chunks, snapshot.vectors, strict=True):
                if wanted.get(chunk["chunk_id"]) == _hash(chunk["content"]):
                    reused[chunk["chunk_id"]] = vector
        missing = [c for c in chunks if c["chunk_id"] not in reused]
        fresh = {}
        if missing:
            if encode_missing is None:
                raise ValueError(f"{len(missing)} trecho(s) sem vetor e sem encode_missing.")
            encoded = validate_vectors(encode_missing(missing), len(missing), self.config.dimension)
            fresh = {c["chunk_id"]: v for c, v in zip(missing, encoded, strict=True)}
        rows = [reused[c["chunk_id"]] if c["chunk_id"] in reused else fresh[c["chunk_id"]] for c in chunks]
        if not rows:
            return np.empty((0, self.config.dimension), dtype=np.float32)
        return validate_vectors(np.stack(rows), len(chunks), self.config.dimension)

    @staticmethod
    def _source_records(chunks) -> list[dict]:
        records: dict[tuple, dict] = {}
        for chunk in chunks:
            key = chunk["source_type"], chunk["source_id"]
            record = records.setdefault(key, {
                "source_type": chunk["source_type"], "source_id": chunk["source_id"],
                "source_reference": chunk["source_reference"], "title": chunk["title"], "chunk_ids": [],
            })
            record["chunk_ids"].append(chunk["chunk_id"])
        return list(records.values())

    def _discard(self, generation: int) -> None:
        """Remove coleção e linhas de uma geração; tolera coleção ausente."""
        try:
            self._client.delete_collection(_collection_name(generation))
        except Exception:  # noqa: BLE001 - coleção pode nunca ter sido criada
            pass
        with self._db() as db:
            db.execute("DELETE FROM sources WHERE generation = ?", (generation,))
            db.execute("DELETE FROM generations WHERE id = ?", (generation,))

    # ------------------------------------------------------------------ leitura
    def _collection(self, info: GenerationInfo):
        try:
            collection = self._client.get_collection(_collection_name(info.generation), embedding_function=None)
        except Exception as exc:  # noqa: BLE001
            raise CorruptGeneration(f"Coleção da geração {info.generation} ausente.") from exc
        space = (collection.configuration or {}).get("hnsw", {}).get("space")
        if space != self.config.metric:
            raise CorruptGeneration(f"Coleção da geração {info.generation} não usa a métrica {self.config.metric}.")
        if collection.count() != info.chunk_count:
            raise CorruptGeneration(f"Geração {info.generation}: contagem da coleção difere do controle.")
        return collection

    def read_generation(self, generation: int) -> GenerationSnapshot:
        """Lê uma geração completa (ativa ou candidata) na ordem original dos trechos."""
        info = self.generation_info(generation)
        self._require_complete(info)
        self._require_compatible(info)
        collection = self._collection(info)
        sources = {(s["source_type"], s["source_id"]): s for s in self.sources(generation)}
        ids, docs, metas, vecs = [], [], [], []
        for offset in range(0, max(info.chunk_count, 1), _BATCH):
            page = collection.get(include=["embeddings", "documents", "metadatas"], limit=_BATCH, offset=offset)
            ids += page["ids"]
            docs += page["documents"]
            metas += page["metadatas"]
            if len(page["ids"]):
                vecs.append(np.asarray(page["embeddings"], dtype=np.float32))
        order = sorted(range(len(ids)), key=lambda i: metas[i]["position"])
        chunks = tuple(self._chunk(ids[i], docs[i], metas[i], sources) for i in order)
        vectors = np.concatenate(vecs)[order] if vecs else np.empty((0, self.config.dimension), dtype=np.float32)
        return GenerationSnapshot(info, chunks, vectors)

    @staticmethod
    def _chunk(chunk_id, content, meta, sources) -> dict:
        source = sources[meta["source_type"], meta["source_id"]]
        return {"source_type": meta["source_type"], "source_id": meta["source_id"],
                "source_reference": source["source_reference"], "title": source["title"],
                "chunk_id": chunk_id, "content": content, "preparation_version": PREPARATION_VERSION}

    # ------------------------------------------------------------------ ativação e leitores
    def activate(self, generation: int) -> None:
        """Aponta a geração ativa para uma candidata completa e compatível (troca atômica)."""
        with self._lock:
            info = self.generation_info(generation)
            self._require_complete(info)
            self._require_compatible(info)
            with self._db() as db:
                db.execute("INSERT INTO state (key, value) VALUES ('active', ?)"
                           " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(generation),))

    def capture_active(self) -> "GenerationReader":
        """Captura a geração ativa agora; o leitor termina nela mesmo se outra for ativada."""
        with self._lock:
            with self._db() as db:
                active = self._active_id(db)
            if active is None:
                raise NoActiveGeneration("Nenhuma geração ativa; crie e ative uma candidata.")
            info = self.generation_info(active)
            self._require_complete(info)
            self._require_compatible(info)
            collection = self._collection(info)
            sources = {(s["source_type"], s["source_id"]): s for s in self.sources(active)}
            self._leases[active] = self._leases.get(active, 0) + 1
        return GenerationReader(self, info, collection, sources)

    def _release(self, generation: int) -> None:
        with self._lock:
            remaining = self._leases.get(generation, 0) - 1
            if remaining > 0:
                self._leases[generation] = remaining
            else:
                self._leases.pop(generation, None)

    # ------------------------------------------------------------------ limpeza
    def cleanup(self, keep_previous: int = 1) -> list[int]:
        """Remove gerações descartáveis e devolve seus números.

        Nunca toca a ativa nem candidatas mais novas que ela. Remove (a) restos de
        construções interrompidas e (b) gerações completas anteriores à ativa, exceto as
        `keep_previous` mais recentes e as que têm leitores abertos neste processo.
        """
        if type(keep_previous) is not int or keep_previous < 0:
            raise ValueError("keep_previous deve ser inteiro não negativo.")
        removed = []
        with self._lock:
            with self._db() as db:
                active = self._active_id(db)
                rows = db.execute("SELECT id, status FROM generations WHERE status != 'retired' ORDER BY id").fetchall()
            stale = [r["id"] for r in rows if r["status"] == "building" and r["id"] not in self._in_flight]
            older = [r["id"] for r in rows if r["status"] == "complete" and active is not None and r["id"] < active]
            expendable = older[:len(older) - keep_previous] if keep_previous else older
            for generation in sorted(stale + [g for g in expendable if g not in self._leases]):
                with self._db() as db:  # 'retired' primeiro: ninguém mais captura; remoção pode ser retomada
                    db.execute("UPDATE generations SET status = 'retired' WHERE id = ?", (generation,))
                self._discard(generation)
                removed.append(generation)
            with self._db() as db:  # retomada de remoções interrompidas
                leftovers = [r["id"] for r in db.execute("SELECT id FROM generations WHERE status = 'retired'")]
            for generation in leftovers:
                self._discard(generation)
        return removed


class GenerationReader:
    """Leitura presa a uma geração. Use como gerenciador de contexto ou chame close()."""

    def __init__(self, store: ChromaGenerationStore, info: GenerationInfo, collection, sources: dict):
        self._store, self._collection, self._sources = store, collection, sources
        self.info = info
        self._closed = False

    @property
    def generation(self) -> int:
        return self.info.generation

    def query(self, vector, limit: int = 3) -> list[dict]:
        if self._closed:
            raise RuntimeError("Leitor já fechado.")
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit deve ser inteiro positivo.")
        query = validate_vectors(np.asarray(vector)[None, :] if np.ndim(vector) == 1 else vector,
                                 1, self._store.config.dimension)
        if self.info.chunk_count == 0:
            return []
        result = self._collection.query(
            query_embeddings=query.tolist(), n_results=min(limit, self.info.chunk_count),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for chunk_id, content, meta, distance in zip(
                result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True):
            source = self._sources[meta["source_type"], meta["source_id"]]
            hits.append({
                "chunk_id": chunk_id, "content": content, "score": 1.0 - float(distance),
                "source_type": meta["source_type"], "source_id": meta["source_id"],
                "source_reference": source["source_reference"], "title": source["title"],
            })
        return hits

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._store._release(self.info.generation)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
