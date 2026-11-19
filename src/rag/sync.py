"""Orquestração do Delta Sync com geração candidata e manifesto atômico (ING-04)."""

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from src.rag.chroma_store import ChromaGenerationStore, GenerationInfo
from src.rag.chunk_contract import PREPARATION_VERSION, PreparedChunk
from src.rag.embeddings import validate_vectors
from src.rag.manifest import load_manifest, save_manifest_atomic


class SyncError(RuntimeError):
    """Erro base da sincronização delta."""


class SyncAlreadyRunningError(SyncError):
    """Já existe uma sincronização em andamento para o mesmo armazenamento."""


class IncompleteCollectionError(SyncError):
    """A coleta de origem terminou incompleta; publicação e exclusão foram bloqueadas."""


class CandidateValidationError(SyncError):
    """A geração candidata falhou na validação de completude, IDs ou consulta."""


@dataclass(frozen=True)
class CollectionBatch:
    """Resultado de uma coleta integral de artigos no escopo do sync."""

    articles: list[dict[str, Any]]
    is_complete: bool


@dataclass(frozen=True)
class SyncReport:
    """Resumo observável de uma execução do delta sync."""

    status: str  # "no_changes" | "published"
    generation: int
    previous_generation: int | None
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
    """Garante apenas uma execução de sync por vez para o mesmo diretório."""
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


def is_article_eligible(article: dict[str, Any]) -> bool:
    """Verifica se o artigo é elegível para indexação no escopo compartilhado."""
    if not isinstance(article, dict):
        return False
    if article.get("eligible") is False or article.get("is_deleted") is True:
        return False
    article_id = article.get("id")
    if type(article_id) is not int or article_id < 0:
        return False
    title = article.get("title")
    content = article.get("content")
    source_ref = article.get("source_reference")
    if not isinstance(title, str) or not title.strip():
        return False
    if not isinstance(content, str) or not content.strip():
        return False
    if source_ref != "/Knowledgebase/Article":
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
            raise ValueError(f"ID de artigo duplicado na coleta: {article_id}.")
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
    store: ChromaGenerationStore,
    candidate_generation: int,
    expected_chunks: Sequence[PreparedChunk],
    probe_vector: np.ndarray | None = None,
) -> GenerationInfo:
    """Valida completude, IDs exatos e consulta real na candidata antes da publicação."""
    try:
        info = store.generation_info(candidate_generation)
        if info.status != "complete":
            raise CandidateValidationError(
                f"Candidata {candidate_generation} não está completa (status: {info.status})."
            )

        snapshot = store.read_generation(candidate_generation)
    except CandidateValidationError:
        raise
    except Exception as exc:
        raise CandidateValidationError(
            f"Falha ao inspecionar a candidata {candidate_generation}: {exc}"
        ) from exc

    expected_ids = [chunk["chunk_id"] for chunk in expected_chunks]
    actual_ids = [chunk["chunk_id"] for chunk in snapshot.chunks]

    if info.chunk_count != len(expected_ids) or actual_ids != expected_ids:
        raise CandidateValidationError(
            f"IDs ou contagem divergentes na candidata {candidate_generation}: "
            f"esperado {len(expected_ids)} chunks, encontrado {len(actual_ids)}."
        )

    if expected_ids:
        vector = probe_vector if probe_vector is not None else snapshot.vectors[0]
        try:
            raw_vec = np.asarray(vector, dtype=np.float32)
            query_vec = validate_vectors(
                raw_vec[None, :] if raw_vec.ndim == 1 else raw_vec,
                1,
                store.config.dimension,
            )
            collection = store._collection(info)
            query_result = collection.query(
                query_embeddings=query_vec.tolist(),
                n_results=1,
                include=["distances"],
            )
        except Exception as exc:
            raise CandidateValidationError(
                f"Consulta de validação falhou na candidata {candidate_generation}: {exc}"
            ) from exc

        returned_ids = query_result.get("ids", [[]])[0]
        returned_distances = query_result.get("distances", [[]])[0]
        if not returned_ids or returned_ids[0] not in set(expected_ids):
            raise CandidateValidationError(
                f"Consulta na candidata {candidate_generation} não retornou um chunk_id válido."
            )
        if not returned_distances or not np.isfinite(returned_distances[0]):
            raise CandidateValidationError(
                f"Consulta na candidata {candidate_generation} retornou distância inválida."
            )

    return info


def reconcile_store_with_manifest(
    store: ChromaGenerationStore,
    manifest_path: str | Path,
) -> int | None:
    """Alinha a geração ativa do store ao manifesto persistido após reinício."""
    manifest = load_manifest(manifest_path)
    manifest_gen = manifest["active_generation"]
    if manifest_gen is not None and store.active_generation() != manifest_gen:
        store.activate(manifest_gen)
    return manifest_gen


def run_delta_sync(
    *,
    store: ChromaGenerationStore,
    collect_fn: Callable[[], CollectionBatch],
    prepare_fn: Callable[[dict[str, Any]], list[PreparedChunk]],
    encode_fn: Callable[[list[PreparedChunk]], np.ndarray],
    manifest_path: str | Path | None = None,
    preparation_version: str = PREPARATION_VERSION,
    validator_fn: Callable[..., GenerationInfo] = validate_candidate,
    cleanup_previous: int | None = 1,
) -> SyncReport:
    """Executa um ciclo completo de delta sync com publicação segura por manifesto."""
    resolved_manifest = (
        Path(manifest_path)
        if manifest_path is not None
        else Path(store._dir) / "sync_manifest.json"
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

        # 2. Filtra elegíveis confirmados e prepara chunks + hashes
        prepared_articles: list[dict[str, Any]] = []
        all_chunks: list[PreparedChunk] = []
        new_sources_state: dict[int, dict[str, Any]] = {}

        for article in batch.articles:
            if not is_article_eligible(article):
                continue

            chunks = list(prepare_fn(article))
            if not chunks:
                continue

            content_hash = compute_content_hash(chunks)
            metadata_hash = compute_metadata_hash(
                title=article["title"],
                source_reference=article["source_reference"],
            )
            article_id = article["id"]

            prepared_articles.append({
                "id": article_id,
                "content_hash": content_hash,
                "metadata_hash": metadata_hash,
            })
            all_chunks.extend(chunks)
            new_sources_state[article_id] = {
                "content_hash": content_hash,
                "metadata_hash": metadata_hash,
                "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
            }

        # 3. Calcula delta considerando versão da preparação e configuração do índice
        current_config = store.config.to_dict()
        force_reembed = previous_active is not None and (
            previous_manifest["index_config"] != current_config
            or previous_manifest["preparation_version"] != preparation_version
        )

        delta = calculate_delta(
            manifest_state=previous_manifest["sources"],
            fetched_articles=prepared_articles,
            is_complete=True,
            force_reembed=force_reembed,
        )

        has_changes = any(
            delta[key] for key in ("new", "content_modified", "metadata_modified", "deleted")
        )

        # 4. Caminho rápido sem mudanças: zero embeddings, atualiza só a verificação
        if previous_active is not None and not has_changes and not force_reembed:
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
                delta=delta,
                chunks_total=len(all_chunks),
                vectors_computed=0,
                manifest_path=resolved_manifest,
                checked_at=checked_at,
                published_at=previous_manifest["last_published_at"],
            )

        # 5. Monta geração candidata (reaproveita vetores compatíveis sem reembutir)
        vectors_computed = 0

        def _counting_encode(missing_chunks: list[PreparedChunk]) -> np.ndarray:
            nonlocal vectors_computed
            vectors = encode_fn(missing_chunks)
            vectors_computed += len(missing_chunks)
            return vectors

        reuse_from = None if force_reembed else previous_active
        candidate_gen = store.create_candidate(
            all_chunks,
            encode_missing=_counting_encode,
            reuse_from=reuse_from,
        )

        # 6. Valida completude, IDs exatos e consulta antes de publicar
        validator_fn(store, candidate_gen, all_chunks)

        # 7. Publicação atômica do manifesto + ativação no store (com rollback em falha)
        now = _utc_now()
        new_manifest = {
            "active_generation": candidate_gen,
            "index_config": current_config,
            "preparation_version": preparation_version,
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
            delta=delta,
            chunks_total=len(all_chunks),
            vectors_computed=vectors_computed,
            manifest_path=resolved_manifest,
            checked_at=now,
            published_at=now,
        )