"""Persistência atômica do manifesto de sincronização (ING-04)."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any

REQUIRED_MANIFEST_KEYS = frozenset({
    "active_generation",
    "index_config",
    "preparation_version",
    "sources",
    "last_checked_at",
    "last_published_at",
})

REQUIRED_SOURCE_KEYS = frozenset({
    "content_hash",
    "metadata_hash",
    "chunk_ids",
})


def empty_manifest() -> dict[str, Any]:
    """Retorna o estado inicial padrão antes da primeira sincronização."""
    return {
        "active_generation": None,
        "index_config": None,
        "preparation_version": None,
        "sources": {},
        "last_checked_at": None,
        "last_published_at": None,
    }


def validate_manifest(data: Any) -> dict[str, Any]:
    """Valida a estrutura do manifesto e normaliza chaves de sources para int."""
    if not isinstance(data, dict):
        raise ValueError("O manifesto deve ser um objeto JSON (dict).")

    missing = REQUIRED_MANIFEST_KEYS - data.keys()
    if missing:
        raise ValueError(f"Chaves obrigatórias ausentes no manifesto: {sorted(missing)}.")

    active_gen = data["active_generation"]
    if active_gen is not None and (type(active_gen) is not int or active_gen <= 0):
        raise ValueError("active_generation deve ser inteiro positivo ou None.")

    if data["index_config"] is not None and not isinstance(data["index_config"], dict):
        raise ValueError("index_config deve ser dict ou None.")

    if data["preparation_version"] is not None and not isinstance(data["preparation_version"], str):
        raise ValueError("preparation_version deve ser string ou None.")

    for ts_field in ("last_checked_at", "last_published_at"):
        if data[ts_field] is not None and not isinstance(data[ts_field], str):
            raise ValueError(f"{ts_field} deve ser string ISO-8601 ou None.")

    raw_sources = data["sources"]
    if not isinstance(raw_sources, dict):
        raise ValueError("sources deve ser um dicionário indexado pelo ID da fonte.")

    normalized_sources: dict[int, dict[str, Any]] = {}
    for raw_id, entry in raw_sources.items():
        if isinstance(raw_id, bool):
            raise ValueError("ID da fonte não pode ser booleano.")
        try:
            source_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ID de fonte inválido no manifesto: {raw_id!r}.") from exc

        if source_id < 0:
            raise ValueError(f"ID de fonte não pode ser negativo: {source_id}.")

        if not isinstance(entry, dict):
            raise ValueError(f"Entrada da fonte {source_id} deve ser dict.")

        missing_entry = REQUIRED_SOURCE_KEYS - entry.keys()
        if missing_entry:
            raise ValueError(
                f"Fonte {source_id} sem campos obrigatórios: {sorted(missing_entry)}."
            )

        if not isinstance(entry["content_hash"], str) or not isinstance(entry["metadata_hash"], str):
            raise ValueError(f"Hashes da fonte {source_id} devem ser strings.")

        chunk_ids = entry["chunk_ids"]
        if not isinstance(chunk_ids, list) or not all(isinstance(cid, str) for cid in chunk_ids):
            raise ValueError(f"chunk_ids da fonte {source_id} deve ser lista de strings.")

        normalized_sources[source_id] = {
            "content_hash": entry["content_hash"],
            "metadata_hash": entry["metadata_hash"],
            "chunk_ids": list(chunk_ids),
        }

    return {
        "active_generation": active_gen,
        "index_config": deepcopy(data["index_config"]),
        "preparation_version": data["preparation_version"],
        "sources": normalized_sources,
        "last_checked_at": data["last_checked_at"],
        "last_published_at": data["last_published_at"],
    }


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Carrega o manifesto do disco ou devolve um estado vazio se ainda não existir."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        return empty_manifest()

    raw_text = manifest_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)
    return validate_manifest(data)


def save_manifest_atomic(path: str | Path, manifest: dict[str, Any]) -> None:
    """Grava o manifesto de forma atômica (temporário no mesmo diretório + fsync + os.replace)."""
    validated = validate_manifest(manifest)
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        **validated,
        "sources": {str(source_id): entry for source_id, entry in validated["sources"].items()},
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=manifest_path.parent,
            prefix=f".{manifest_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(serialized)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        os.replace(tmp_path, manifest_path)
    except BaseException:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise