"""Orquestração de reconstrução controlada e publicação atômica do índice local (ING-04 — Alternativa C)."""

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from src.rag.chunk_contract import PREPARATION_VERSION, PreparedChunk
from src.rag.corpus import CorpusMetadata, PreparedCorpus
from src.rag.embeddings import IncompatibleConfig, validate_vectors
from src.rag.local_index import GenerationInfo, IndexCorrupt, LocalIndexStore
from src.rag.manifest import load_manifest, save_manifest_atomic


class SyncError(RuntimeError):
    """Erro base da sincronização do índice local."""


class SyncAlreadyRunningError(SyncError):
    """Já existe uma sincronização em andamento para o mesmo índice."""


class IncompleteCollectionError(SyncError):
    """A coleta de origem terminou incompleta; publicação e exclusão foram bloqueadas."""


class CandidateValidationError(SyncError):
    """A geração candidata falhou na validação de completude, IDs ou consulta cosseno."""


@dataclass(frozen=True)
class CollectionBatch:
    """Resultado de uma coleta integral de fontes no escopo da sincronização."""

    articles: list[dict[str, Any]]
    is_complete: bool


@dataclass(frozen=True)
class SyncReport:
    """Resumo observável de uma execução de sincronização."""

    status: str  # "no_changes" | "published"
    generation: str
    previous_generation: str | None
    source_type: str
    source_signature: str
    delta: dict[str, list[int]]
    chunks_total: int
    vectors_computed: int
    manifest_path: Path
    checked_at: str
    published_at: str | None


_LOCKS_GUARD = Lock()
_SYNC_LOCKS: dict[Path, Lock] = {}


@contextmanager
def _exclusive_sync_lock(lock_key: Path):
    """Garante apenas uma execução de sync por vez para o mesmo manifesto/diretório."""
    resolved = lock_key.resolve()
    with _LOCKS_GUARD:
        lock = _SYNC_LOCKS.setdefault(resolved, Lock())

    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise SyncAlreadyRunningError(
            f"Já existe uma sincronização em execução para {resolved}."
        )
    try:
        yield
    finally:
        lock.release()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_title(item: dict[str, Any]) -> Any:
    return item["title"] if "title" in item else item.get("name")


def is_article_eligible(article: dict[str, Any]) -> bool:
    """Verifica se o artigo é elegível para indexação no escopo staff."""
    if not isinstance(article, dict):
        return False
    if article.get("eligible") is False or article.get("is_deleted") is True:
        return False
    article_id = article.get("id")
    if type(article_id) is not int or article_id < 0:
        return False
    title = _extract_title(article)
    content = article.get("content")
    source_ref = article.get("source_reference")
    if not isinstance(title, str) or not title.strip():
        return False
    if not isinstance(content, str) or not content.strip():
        return False
    if source_ref != "/Knowledgebase/Article":
        return False
    return True


def is_source_eligible(item: dict[str, Any], source_type: str = "article") -> bool:
    """Verifica elegibilidade conforme o tipo de índice (article ou case)."""
    if source_type == "article":
        return is_article_eligible(item)
    if source_type != "case":
        raise ValueError(f"source_type não suportado: {source_type!r}.")

    if not isinstance(item, dict):
        return False
    if item.get("eligible") is False or item.get("is_deleted") is True:
        return False
    item_id = item.get("id")
    if type(item_id) is not int or item_id < 0:
        return False
    title = _extract_title(item)
    source_ref = item.get("source_reference")
    if not isinstance(title, str) or not title.strip():
        return False
    if source_ref != "/Assistance/Ticket":
        return False

    body_fields = (item.get("content"), item.get("solution"), item.get("problem"))
    if not any(isinstance(value, str) and value.strip() for value in body_fields):
        return False
    return True


def compute_content_hash(chunks: Sequence[PreparedChunk]) -> str:
    """Hash determinístico do texto tratado e da segmentação em chunks."""
    canonical = [[chunk["chunk_id"], chunk["content"]] for chunk in chunks]
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_metadata_hash(
    title: str,
    source_reference: str,
    source_type: str = "article",
) -> str:
    """Hash determinístico apenas dos metadados da fonte (sem o corpo textual)."""
    canonical = {
        "source_type": source_type,
        "source_reference": source_reference,
        "title": title,
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_source_signature(
    sources_state: dict[int, dict[str, Any]],
    source_type: str = "article",
) -> str:
    """Calcula a assinatura SHA-256 global e determinística do conjunto elegível."""
    ordered_sources = [
        {
            "id": source_id,
            "content_hash": entry["content_hash"],
            "metadata_hash": entry["metadata_hash"],
            "chunk_ids": entry["chunk_ids"],
        }
        for source_id, entry in sorted(sources_state.items())
    ]
    payload = {
        "source_type": source_type,
        "sources": ordered_sources,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_delta(
    manifest_state: dict[int, dict[str, Any]],
    fetched_articles: list[dict[str, Any]],
    is_complete: bool,
    force_reembed: bool = False,
) -> dict[str, list[int]]:
    """Compara o estado publicado com a coleta atual e classifica os IDs em 5 grupos."""
    result: dict[str, list[int]] = {
        "new": [],
        "content_modified": [],
        "metadata_modified": [],
        "same": [],
        "deleted": [],
    }

    id_buffer: set[int] = set()

    for article in fetched_articles:
        article_id = article["id"]
        if article_id in id_buffer:
            raise ValueError(f"ID de fonte duplicado na coleta: {article_id}.")
        id_buffer.add(article_id)

        if article_id not in manifest_state:
            result["new"].append(article_id)
        elif (
            force_reembed
            or manifest_state[article_id]["content_hash"] != article["content_hash"]
        ):
            result["content_modified"].append(article_id)
        elif manifest_state[article_id]["metadata_hash"] != article["metadata_hash"]:
            result["metadata_modified"].append(article_id)
        else:
            result["same"].append(article_id)

    if is_complete:
        for existing_id in manifest_state:
            if existing_id not in id_buffer:
                result["deleted"].append(existing_id)

    return result


def validate_candidate(
    store: LocalIndexStore,
    candidate_generation: str,
    expected_chunks: Sequence[PreparedChunk],
    probe_vector: np.ndarray | None = None,
) -> GenerationInfo:
    """Valida completude, IDs exatos e busca cosseno direta na matriz NumPy da candidata."""
    try:
        info = store.generation_info(candidate_generation)
        corpus = store.read_candidate(candidate_generation)
    except CandidateValidationError:
        raise
    except Exception as exc:
        raise CandidateValidationError(
            f"Falha ao inspecionar a candidata {candidate_generation}: {exc}"
        ) from exc

    if info.source_type != store.source_type:
        raise CandidateValidationError(
            f"Tipo da candidata ({info.source_type}) difere do índice ({store.source_type})."
        )

    expected_ids = [chunk["chunk_id"] for chunk in expected_chunks]
    actual_ids = [chunk["chunk_id"] for chunk in corpus.chunks]

    if info.chunk_count != len(expected_ids) or actual_ids != expected_ids:
        raise CandidateValidationError(
            f"IDs ou contagem divergentes na candidata {candidate_generation}: "
            f"esperado {len(expected_ids)} chunks, encontrado {len(actual_ids)}."
        )

    if expected_ids:
        vector = probe_vector if probe_vector is not None else corpus.vectors[0]
        try:
            raw_vec = np.asarray(vector, dtype=np.float32)
            query_vec = validate_vectors(
                raw_vec[None, :] if raw_vec.ndim == 1 else raw_vec,
                1,
                store.embedding.dimension,
            )
            scores = corpus.vectors @ query_vec[0]
        except Exception as exc:
            raise CandidateValidationError(
                f"Consulta de validação falhou na candidata {candidate_generation}: {exc}"
            ) from exc

        if scores.shape != (len(expected_ids),) or not np.all(np.isfinite(scores)):
            raise CandidateValidationError(
                f"Consulta na candidata {candidate_generation} produziu pontuações inválidas."
            )

        best_idx = int(np.argmax(scores))
        best_chunk_id = corpus.chunks[best_idx]["chunk_id"]
        if best_chunk_id not in set(expected_ids):
            raise CandidateValidationError(
                f"Consulta na candidata {candidate_generation} não retornou um chunk_id válido."
            )

    return info


def reconcile_store_with_manifest(
    store: LocalIndexStore,
    manifest_path: str | Path,
) -> str | None:
    """Alinha o ponteiro ACTIVE do índice local ao manifesto persistido após reinício."""
    manifest = load_manifest(manifest_path)
    manifest_gen = manifest["active_generation"]
    if manifest_gen is None:
        return None

    try:
        current_active = store.active_generation_id()
    except IndexCorrupt:
        current_active = None

    if current_active != manifest_gen:
        store.activate(manifest_gen)
    return manifest_gen


def _build_prepared_corpus(
    *,
    store: LocalIndexStore,
    all_chunks: list[PreparedChunk],
    encode_fn: Callable[[list[PreparedChunk]], np.ndarray],
    preparation_version: str,
    allow_reuse: bool,
) -> tuple[PreparedCorpus, int]:
    """Constrói o PreparedCorpus completo, reaproveitando vetores compatíveis quando permitido."""
    dimension = store.embedding.dimension
    if not all_chunks:
        empty_matrix = np.empty((0, dimension), dtype=np.float32)
        metadata = CorpusMetadata(store.embedding, preparation_version, ())
        return PreparedCorpus((), empty_matrix, metadata), 0

    reused: dict[str, np.ndarray] = {}
    if allow_reuse:
        try:
            reused = store.reusable_vectors(all_chunks)
        except (IncompatibleConfig, IndexCorrupt):
            reused = {}

    missing_chunks = [chunk for chunk in all_chunks if chunk["chunk_id"] not in reused]
    computed_by_id: dict[str, np.ndarray] = {}
    vectors_computed = 0

    if missing_chunks:
        raw_vectors = encode_fn(missing_chunks)
        validated = validate_vectors(raw_vectors, len(missing_chunks), dimension)
        for chunk, vec in zip(missing_chunks, validated, strict=True):
            computed_by_id[chunk["chunk_id"]] = vec
        vectors_computed = len(missing_chunks)

    ordered_vectors = [
        reused[cid] if (cid := chunk["chunk_id"]) in reused else computed_by_id[cid]
        for chunk in all_chunks
    ]
    matrix = np.stack(ordered_vectors).astype(np.float32, copy=False)
    metadata = CorpusMetadata(
        embedding=store.embedding,
        preparation_version=preparation_version,
        chunk_ids=tuple(chunk["chunk_id"] for chunk in all_chunks),
    )
    return PreparedCorpus(tuple(all_chunks), matrix, metadata), vectors_computed


def run_sync(
    *,
    store: LocalIndexStore,
    collect_fn: Callable[[], CollectionBatch],
    prepare_fn: Callable[[dict[str, Any]], list[PreparedChunk]],
    encode_fn: Callable[[list[PreparedChunk]], np.ndarray],
    manifest_path: str | Path | None = None,
    preparation_version: str = PREPARATION_VERSION,
    validator_fn: Callable[..., GenerationInfo] = validate_candidate,
    cleanup_previous: int | None = 1,
    reuse_vectors: bool = True,
) -> SyncReport:
    """Executa um ciclo completo de reconstrução controlada e publicação atômica."""
    resolved_manifest = (
        Path(manifest_path)
        if manifest_path is not None
        else Path(store.directory) / "sync_manifest.json"
    )

    with _exclusive_sync_lock(resolved_manifest):
        manifest_existed = resolved_manifest.exists()
        previous_manifest = load_manifest(resolved_manifest)
        previous_active = previous_manifest["active_generation"]

        # 1. Coleta integral no mesmo escopo
        batch = collect_fn()
        if not isinstance(batch, CollectionBatch):
            raise TypeError("collect_fn deve retornar um CollectionBatch.")
        if not batch.is_complete:
            raise IncompleteCollectionError(
                "Coleta incompleta recebida: exclusões e publicação foram bloqueadas."
            )

        # 2. Filtra elegíveis, prepara chunks e calcula hashes + assinatura global
        source_type = store.source_type
        prepared_sources: list[dict[str, Any]] = []
        all_chunks: list[PreparedChunk] = []
        new_sources_state: dict[int, dict[str, Any]] = {}

        for item in batch.articles:
            if not is_source_eligible(item, source_type=source_type):
                continue

            chunks = list(prepare_fn(item))
            if not chunks:
                continue

            title = _extract_title(item)
            content_hash = compute_content_hash(chunks)
            metadata_hash = compute_metadata_hash(
                title=title,
                source_reference=item["source_reference"],
                source_type=source_type,
            )
            source_id = item["id"]

            prepared_sources.append({
                "id": source_id,
                "content_hash": content_hash,
                "metadata_hash": metadata_hash,
            })
            all_chunks.extend(chunks)
            new_sources_state[source_id] = {
                "content_hash": content_hash,
                "metadata_hash": metadata_hash,
                "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
            }

        source_signature = compute_source_signature(
            new_sources_state,
            source_type=source_type,
        )

        # 3. Detecta mudança de configuração/versão ou inconsistência no índice ativo
        current_embedding_config = asdict(store.embedding)
        try:
            store_active_id = store.active_generation_id()
        except IndexCorrupt:
            store_active_id = None

        active_store_healthy = False
        if previous_active is not None and store_active_id == previous_active:
            try:
                store.generation_info(previous_active)
                active_store_healthy = True
            except (IncompatibleConfig, IndexCorrupt, ValueError):
                active_store_healthy = False

        config_changed = previous_active is not None and (
            previous_manifest["source_type"] != source_type
            or previous_manifest["embedding_config"] != current_embedding_config
            or previous_manifest["preparation_version"] != preparation_version
        )
        force_reembed = config_changed or (previous_active is not None and not active_store_healthy)

        delta = calculate_delta(
            manifest_state=previous_manifest["sources"],
            fetched_articles=prepared_sources,
            is_complete=True,
            force_reembed=force_reembed,
        )

        has_changes = (
            previous_manifest["source_signature"] != source_signature
            or any(
                delta[key]
                for key in ("new", "content_modified", "metadata_modified", "deleted")
            )
        )

        # 4. Caminho rápido sem mudanças: zero embeddings, atualiza apenas last_checked_at
        if previous_active is not None and active_store_healthy and not has_changes and not force_reembed:
            checked_at = _utc_now()
            updated_manifest = {
                **previous_manifest,
                "last_checked_at": checked_at,
            }
            save_manifest_atomic(resolved_manifest, updated_manifest)
            return SyncReport(
                status="no_changes",
                generation=previous_active,
                previous_generation=previous_active,
                source_type=source_type,
                source_signature=source_signature,
                delta=delta,
                chunks_total=len(all_chunks),
                vectors_computed=0,
                manifest_path=resolved_manifest,
                checked_at=checked_at,
                published_at=previous_manifest["last_published_at"],
            )

        # 5. Constrói o PreparedCorpus completo e grava a geração candidata
        corpus, vectors_computed = _build_prepared_corpus(
            store=store,
            all_chunks=all_chunks,
            encode_fn=encode_fn,
            preparation_version=preparation_version,
            allow_reuse=reuse_vectors and not force_reembed and active_store_healthy,
        )
        candidate_info = store.create_candidate(
            corpus,
            source_signature=source_signature,
        )
        candidate_gen = candidate_info.generation_id

        # 6. Valida completude, IDs exatos e consulta cosseno antes da publicação
        validator_fn(store, candidate_gen, all_chunks)

        # 7. Publicação atômica do manifesto + ativação do ponteiro ACTIVE (com rollback em erro)
        now = _utc_now()
        new_manifest = {
            "active_generation": candidate_gen,
            "source_type": source_type,
            "embedding_config": current_embedding_config,
            "preparation_version": preparation_version,
            "source_signature": source_signature,
            "sources": new_sources_state,
            "last_checked_at": now,
            "last_published_at": now,
        }

        save_manifest_atomic(resolved_manifest, new_manifest)
        try:
            store.activate(candidate_gen)
        except BaseException:
            if manifest_existed:
                save_manifest_atomic(resolved_manifest, previous_manifest)
            else:
                resolved_manifest.unlink(missing_ok=True)
            raise

        if cleanup_previous is not None:
            store.cleanup(keep_previous=cleanup_previous)

        return SyncReport(
            status="published",
            generation=candidate_gen,
            previous_generation=previous_active,
            source_type=source_type,
            source_signature=source_signature,
            delta=delta,
            chunks_total=len(all_chunks),
            vectors_computed=vectors_computed,
            manifest_path=resolved_manifest,
            checked_at=now,
            published_at=now,
        )


# Alias de compatibilidade para importações anteriores
run_delta_sync = run_sync