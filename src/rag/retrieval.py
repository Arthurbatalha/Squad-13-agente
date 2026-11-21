"""RAG-03: leitura autorizada de gerações publicadas, sem ingestão no caminho.

O Principal e o scope_resolver vêm do servidor. Conteúdo recuperado é dado
não confiável. Similaridade de cosseno: quanto maior, mais semelhante.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import itertools
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

import numpy as np

from src.authorization.policies import Principal, ToolDenied
from src.authorization.service import AuthorizationService, as_model_data
from src.rag.corpus import CorpusUnavailable
from src.rag.embeddings import EmbeddingService, IncompatibleConfig, validate_vectors
from src.rag.local_index import IndexCorrupt, LocalIndexStore
from src.rag.manifest import load_manifest
from src.rag.sync_runtime import SyncRunLedger

TOOLS = {"article": "search_articles", "case": "similar_cases"}
METRIC = "cosine_similarity"


@dataclass(frozen=True)
class RetrievalConfig:
    candidates_per_collection: int = 8
    max_chunks: int = 4
    max_chunks_per_source: int = 2
    context_max_tokens: int = 640
    min_similarity: float = 0.45  # Provisório: calibração pertence à RAG-02.

    def __post_init__(self):
        for name in ("candidates_per_collection", "max_chunks", "max_chunks_per_source",
                     "context_max_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} deve ser inteiro não negativo.")
        if (isinstance(self.min_similarity, bool)
                or not isinstance(self.min_similarity, (int, float))
                or not math.isfinite(self.min_similarity) or not -1 <= self.min_similarity <= 1):
            raise ValueError("min_similarity deve estar entre -1 e 1.")


def _normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def _requirements(question, required_evidence):
    """Marcadores verificáveis; não substitui avaliação semântica da RAG-02.

    RAG-01 pode fornecer frases/termos que obrigatoriamente devem estar no
    contexto. Detecta também pedidos literais de passo N e solução/correção.
    Esses marcadores nunca participam de autorização.
    """
    if isinstance(required_evidence, (str, bytes)):
        raise TypeError("required_evidence deve ser coleção de frases.")
    terms = []
    for term in required_evidence:
        if not isinstance(term, str) or not term.strip():
            raise ValueError("Cada evidência requerida deve ser texto não vazio.")
        term = _normalized(term.strip())
        if not term:
            raise ValueError("Cada evidência requerida deve conter texto após normalização.")
        # Códigos hifenizados são um identificador: ERR-691-A não satisfaz
        # uma exigência de ERR-691. Pontuação de frase continua permitida.
        boundary = r"[\w-]" if "-" in term and not re.search(r"\s", term) else r"\w"
        left = rf"(?<!{boundary})" if re.match(r"\w", term[0]) else ""
        right = rf"(?!{boundary})" if re.match(r"\w", term[-1]) else ""
        terms.append(left + re.escape(term) + right)
    normalized = _normalized(question)
    steps = re.findall(r"\bpasso\s+(\d+)\b", normalized)
    # A marcação de ênfase pode envolver o rótulo, mas asteriscos/crases e
    # pontuação sozinhos não constituem uma instrução. Exige conteúdo após
    # o rótulo, inclusive quando esse conteúdo está no trecho complementar.
    markup = r"[*_`]*"
    body = r"[\W_]*[^\W_]"
    patterns = [rf"(?<!\w){markup}passo\s+{int(step)}{markup}\s*[:.\-]{body}"
                rf"|(?m:^\s*{markup}{int(step)}[.)]{body})" for step in steps]
    if re.search(r"\b(solucao|solucionar|resolver|corrigir|correcao)\b", normalized):
        patterns.append(rf"(?<!\w){markup}(solucao|correcao){markup}\s*[:\-]{body}"
                        rf"|(?m:^\s*#+\s*{markup}(solucao|correcao){markup}\s*\n{body})"
                        rf"|(?<!\w){markup}passo\s+\d+{markup}\s*[:.\-]{body}"
                        rf"|(?m:^\s*{markup}\d+[.)]{body})")
    return tuple(dict.fromkeys(terms + patterns))


def render_context(chunks) -> str:
    """Serialização exata coberta pelo orçamento (inclui rótulos e referências)."""
    if not chunks:
        return ""
    records = [
        {key: chunk[key] for key in ("chunk_id", "source_type", "source_id", "title",
                                    "content", "source_reference")}
        for chunk in chunks
    ]
    return json.dumps(as_model_data(records, source="published_index"),
                      ensure_ascii=False, sort_keys=True)


def _identity(hit):
    return hit["source_type"], hit["source_id"]


def _rank_key(hit):
    ordinal = int(hit["chunk_id"].rsplit(":", 1)[1])
    return (-hit["score"], *_identity(hit), ordinal, hit["chunk_id"])


def _context_order(hits):
    """Relevância entre fontes; ordem original dentro de cada fonte."""
    best = {}
    for hit in hits:
        identity = _identity(hit)
        best[identity] = max(best.get(identity, -1.0), hit["score"])
    return sorted(hits, key=lambda c: (-best[_identity(c)], *_identity(c),
                                      int(c["chunk_id"].rsplit(":", 1)[1])))


class PublishedRetrieval:
    """Reutilizável por processo. Cada chamada captura suas próprias gerações.

    scope_resolver(principal, tipo) é opcional e SOMENTE do backend: restringe
    a uma coleção de IDs; None/erro significa desconhecido e nega a coleção.
    Sem resolver adicional, aplicam-se integralmente as regras da AUTH-01.
    sync_ledgers mapeia tipo -> caminho de histórico, lido apenas em modo ro.
    """

    def __init__(self, stores: Mapping[str, LocalIndexStore], *,
                 authorization: AuthorizationService, encoder: EmbeddingService | None = None,
                 config: RetrievalConfig = RetrievalConfig(),
                 scope_resolver: Callable[[Principal, str], Iterable[int] | None] | None = None,
                 sync_ledgers: Mapping[str, str | Path] | None = None):
        self.stores = dict(stores)
        if any(kind not in TOOLS or store.source_type != kind for kind, store in self.stores.items()):
            raise ValueError("Cada store deve corresponder à coleção article/case.")
        self.authorization = authorization
        self.encoder = encoder if encoder is not None else EmbeddingService()
        self.config = config
        self.scope_resolver = scope_resolver
        self.sync_ledgers = dict(sync_ledgers or {})

    def _collection_info(self, kind, active):
        info = {"state": "available", "generation": active.generation_id,
                "generation_created_at": active.info.created_at,
                "update": {"state": "unknown", "last_attempt_at": None,
                           "last_attempt_result": None, "last_checked_at": None,
                           "last_published_at": None, "observed_generation": None,
                           "last_success_at": None, "source_api_status": "unknown", "error": None}}
        # ING-04 também publica datas no manifesto. Só usa datas cuja
        # geração coincide com a captura; nunca atribui datas da geração nova.
        try:
            manifest = load_manifest(self.stores[kind].directory / "sync_manifest.json")
            if manifest["active_generation"] == active.generation_id:
                info["update"].update(state="current", last_checked_at=manifest["last_checked_at"],
                                      last_published_at=manifest["last_published_at"],
                                      observed_generation=active.generation_id)
        except (OSError, ValueError, TypeError):
            info["update"]["state"] = "unavailable"
        path = self.sync_ledgers.get(kind)
        if path is None:
            return info
        try:
            latest, success = SyncRunLedger.read_observation(path, active.generation_id)
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            info["update"]["state"] = "unavailable"
            return info
        if success:
            info["update"].update(last_checked_at=success.checked_at,
                                  last_published_at=success.published_at, last_success_at=success.finished_at)
        if latest:
            state = ("failed" if latest.status == "failed" or latest.source_api_status == "unavailable"
                     else "updating" if latest.status == "running"
                     else "current" if latest.active_generation == active.generation_id
                     else "generation_changed")
            info["update"].update(state=state, last_attempt_at=latest.started_at,
                                  last_attempt_result=latest.status,
                                  observed_generation=latest.active_generation,
                                  source_api_status=latest.source_api_status, error=latest.error_code)
            if state == "failed":
                info["state"] = "stale"
        return info

    def retrieve(self, question: str, principal: Principal, *, required_evidence=()) -> dict:
        if not isinstance(principal, Principal):
            raise ToolDenied()
        if not isinstance(question, str) or not question.strip():
            raise ValueError("A pergunta deve ser texto não vazio.")
        requirements = _requirements(question, required_evidence)
        collections, snapshots, authorized_rows = {}, {}, {}
        with ExitStack() as stack:
            for kind, store in sorted(self.stores.items()):
                try:
                    self.authorization.authorize_tool(principal, TOOLS[kind])
                except ToolDenied:
                    collections[kind] = {"state": "not_authorized"}
                    continue
                restriction = None
                if self.scope_resolver is not None:
                    try:
                        scope = self.scope_resolver(principal, kind)
                        if scope is None or isinstance(scope, (str, bytes, Mapping)):
                            raise ValueError("Escopo desconhecido.")
                        restriction = frozenset(scope)
                        if any(type(i) is not int or i < 0 for i in restriction):
                            raise ValueError("Escopo inválido.")
                    except Exception:
                        restriction = frozenset()
                    if not restriction:
                        collections[kind] = {"state": "not_authorized"}
                        continue
                # Casos são opcionais: ING-05 publica apenas artigos. Não
                # cria store/ingestão nem trata ausência esperada como falha.
                if kind == "case" and not (store.directory / "ACTIVE").exists():
                    collections[kind] = {"state": "not_published"}
                    continue
                try:
                    if store.embedding != self.encoder.config:
                        raise IncompatibleConfig("Encoder e coleção incompatíveis.")
                    active = stack.enter_context(store.open_active())
                except (CorpusUnavailable, IndexCorrupt, IncompatibleConfig, OSError) as exc:
                    collections[kind] = {"state": "unavailable", "error": type(exc).__name__}
                    continue
                collections[kind] = self._collection_info(kind, active)
                snapshots[kind] = active
                source_ids = {c["source_id"] for c in active.corpus.chunks}
                if restriction is not None:
                    source_ids &= restriction
                allowed = self.authorization.retrieval_source_ids(principal, kind, source_ids)
                authorized_rows[kind] = [i for i, c in enumerate(active.corpus.chunks)
                                         if c["source_id"] in allowed]

            def result(chunks, reason):
                unavailable = any(c["state"] == "unavailable" for c in collections.values())
                status = ("evidence" if chunks else "index_unavailable" if unavailable
                          else "no_evidence")
                context = render_context(chunks)
                return {"status": status, "reason": reason, "trust": "untrusted_data",
                        "chunks": chunks, "context": context,
                        "context_tokens": self.encoder.token_count(context) if context else 0,
                        "collections": collections, "incomplete": unavailable,
                        "metric": METRIC, "higher_is_more_similar": True,
                        "config": asdict(self.config), "threshold_provisional": True}

            if not any(authorized_rows.values()):
                reason = ("index_unavailable" if not snapshots and any(
                    c["state"] == "unavailable" for c in collections.values()) else
                    "empty_index" if snapshots and all(not s.corpus.chunks for s in snapshots.values())
                    else "empty_authorized_scope")
                return result([], reason)
            if (not self.config.max_chunks or not self.config.max_chunks_per_source
                    or not self.config.candidates_per_collection or not self.config.context_max_tokens):
                return result([], "context_disabled")

            # Uma inferência da pergunta, compartilhada por todas as coleções.
            question_vector = validate_vectors(
                np.asarray(self.encoder.encode_question(question)).reshape(1, -1),
                1, self.encoder.config.dimension)[0]
            candidates = []
            for kind, active in snapshots.items():
                rows = authorized_rows[kind]
                if not rows:
                    continue
                # Nenhum vetor não autorizado entra no produto/ranking/top-k.
                scores = active.corpus.vectors[rows] @ question_vector
                ranked, seen = [], set()
                for row, score in zip(rows, scores):
                    chunk = dict(active.corpus.chunks[row])
                    hit = {**chunk, "score": float(np.clip(score, -1.0, 1.0)),
                           "metric": METRIC, "generation": active.generation_id,
                           "source_modified_at": None}
                    ranked.append(hit)
                for hit in sorted(ranked, key=_rank_key):
                    identity = (*_identity(hit), " ".join(hit["content"].split()))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    candidates.append(hit)
                    if len(seen) == self.config.candidates_per_collection:
                        break
            candidates.sort(key=_rank_key)
            selected, counts, selected_ids = [], Counter(), set()

            def covers(bundle):
                text = _normalized("\n".join(c["content"] for c in _context_order(bundle)))
                return all(re.search(pattern, text) for pattern in requirements)

            for hit in candidates:
                if hit["chunk_id"] in selected_ids or hit["score"] < self.config.min_similarity:
                    continue
                identity = _identity(hit)
                others = [c for c in candidates if _identity(c) == identity
                          and c["chunk_id"] != hit["chunk_id"] and c["chunk_id"] not in selected_ids]
                # A unidade de evidência é uma fonte. Nunca completa um passo
                # com instrução de outra fonte/tipo apenas por título ou ID.
                remaining = min(self.config.max_chunks_per_source - counts[identity],
                                self.config.max_chunks - len(selected))
                bundle = None
                for size in range(1, remaining + 1):
                    for extras in itertools.combinations(others, size - 1):
                        trial = [hit, *extras]
                        ordered = _context_order([*selected, *trial])
                        if covers(trial) and self.encoder.token_count(render_context(ordered)) <= self.config.context_max_tokens:
                            bundle = trial
                            break
                    if bundle is not None:
                        break
                if bundle is None:
                    continue
                selected.extend({**c, "selection_reason": "ranked" if i == 0 else "same_source_support"}
                                for i, c in enumerate(bundle))
                counts[identity] += len(bundle)
                selected_ids.update(c["chunk_id"] for c in bundle)
            selected = _context_order(selected)
            return result(selected, "selected" if selected else "insufficient_evidence")


def build_published_retrieval(authorization: AuthorizationService, *,
                              encoder: EmbeddingService | None = None,
                              index_dir: str | Path | None = None,
                              config: RetrievalConfig = RetrievalConfig(),
                              scope_resolver: Callable[[Principal, str], Iterable[int] | None] | None = None
                              ) -> PublishedRetrieval:
    """Ponto de composição RAG-01. Construir não carrega pesos/cria índice/sync."""
    from src.config import INDEX_DIR

    root = Path(index_dir) if index_dir is not None else INDEX_DIR
    encoder = encoder if encoder is not None else EmbeddingService()
    return PublishedRetrieval(
        {kind: LocalIndexStore(root, kind, embedding=encoder.config) for kind in TOOLS},
        authorization=authorization, encoder=encoder,
        sync_ledgers={"article": root.parent / "article_sync_runs.sqlite3"},
        config=config, scope_resolver=scope_resolver)
