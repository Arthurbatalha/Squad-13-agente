"""Testes unitários do manifesto atômico e da lógica de Delta Sync (ING-04)."""

import json
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.manifest import (
    empty_manifest,
    load_manifest,
    save_manifest_atomic,
    validate_manifest,
)
from src.rag.sync import (
    CollectionBatch,
    IncompleteCollectionError,
    SyncAlreadyRunningError,
    calculate_delta,
    compute_content_hash,
    compute_metadata_hash,
    is_article_eligible,
    run_delta_sync,
)


def _make_chunks(
    source_id: int,
    contents: list[str],
    *,
    title: str = "Guia VPN",
    version: str = "ing01-v1",
) -> list[dict]:
    """Monta chunks no contrato PreparedChunk para testes de hash."""
    return [
        {
            "source_type": "article",
            "source_id": source_id,
            "source_reference": "/Knowledgebase/Article",
            "title": title,
            "chunk_id": f"{version}:article:{source_id}:{idx:04d}",
            "content": text,
            "preparation_version": version,
        }
        for idx, text in enumerate(contents)
    ]


class _DummyStore:
    """Stub mínimo de store para testar travas de entrada de run_delta_sync sem Chroma."""

    def __init__(self, persist_dir: Path) -> None:
        self._dir = persist_dir


# ------------------------------------------------------------------ 1. Manifesto


def test_load_manifest_returns_empty_when_file_does_not_exist(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    assert load_manifest(manifest_path) == empty_manifest()


def test_save_and_load_manifest_roundtrip_normalizes_source_ids_to_int(tmp_path: Path) -> None:
    manifest_path = tmp_path / "nested" / "sync_manifest.json"
    original = {
        "active_generation": 2,
        "index_config": {"model": "intfloat/multilingual-e5-small", "dimension": 384},
        "preparation_version": "ing01-v1",
        "sources": {
            10: {
                "content_hash": "hash-c-10",
                "metadata_hash": "hash-m-10",
                "chunk_ids": ["ing01-v1:article:10:0000", "ing01-v1:article:10:0001"],
            }
        },
        "last_checked_at": "2026-11-19T08:00:00+00:00",
        "last_published_at": "2026-11-19T08:00:00+00:00",
    }

    save_manifest_atomic(manifest_path, original)

    raw_json = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "10" in raw_json["sources"]

    loaded = load_manifest(manifest_path)
    assert loaded == original
    assert 10 in loaded["sources"]
    assert all(type(key) is int for key in loaded["sources"])


@pytest.mark.parametrize(
    "invalid_payload",
    [
        "nao-e-dict",
        {"active_generation": 1},
        {**empty_manifest(), "active_generation": True},
        {**empty_manifest(), "active_generation": 0},
        {**empty_manifest(), "sources": {-1: {"content_hash": "a", "metadata_hash": "b", "chunk_ids": []}}},
        {**empty_manifest(), "sources": {"abc": {"content_hash": "a", "metadata_hash": "b", "chunk_ids": []}}},
        {**empty_manifest(), "sources": {10: {"content_hash": "a"}}},
        {**empty_manifest(), "sources": {10: {"content_hash": "a", "metadata_hash": "b", "chunk_ids": [123]}}},
        {**empty_manifest(), "last_checked_at": 12345},
    ],
)
def test_validate_manifest_rejects_invalid_structures(invalid_payload) -> None:
    with pytest.raises(ValueError):
        validate_manifest(invalid_payload)


def test_save_manifest_atomic_preserves_previous_file_and_cleans_tmp_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    initial = {
        **empty_manifest(),
        "active_generation": 1,
        "last_checked_at": "2026-11-19T08:00:00+00:00",
        "last_published_at": "2026-11-19T08:00:00+00:00",
    }
    save_manifest_atomic(manifest_path, initial)

    def _broken_replace(src, dst):
        raise OSError("falha simulada na troca atômica")

    monkeypatch.setattr("src.rag.manifest.os.replace", _broken_replace)

    updated = {**initial, "active_generation": 2}
    with pytest.raises(OSError, match="falha simulada"):
        save_manifest_atomic(manifest_path, updated)

    assert load_manifest(manifest_path) == initial
    assert list(tmp_path.iterdir()) == [manifest_path]


# ------------------------------------------------------------------ 2. Elegibilidade e hashes


def test_is_article_eligible_accepts_valid_and_rejects_invalid_cases() -> None:
    valid = {
        "id": 42,
        "title": "Reset de senha",
        "content": "<p>Passo 1</p>",
        "source_reference": "/Knowledgebase/Article",
    }
    assert is_article_eligible(valid) is True
    assert is_article_eligible({**valid, "eligible": False}) is False
    assert is_article_eligible({**valid, "is_deleted": True}) is False
    assert is_article_eligible({**valid, "id": True}) is False
    assert is_article_eligible({**valid, "id": -5}) is False
    assert is_article_eligible({**valid, "title": "   "}) is False
    assert is_article_eligible({**valid, "content": ""}) is False
    assert is_article_eligible({**valid, "source_reference": "/Assistance/Ticket"}) is False


def test_content_and_metadata_hashes_are_independent_and_detect_chunk_reduction() -> None:
    chunks_5 = _make_chunks(10, [f"Trecho {i}" for i in range(5)], title="Título A")
    chunks_5_new_title = _make_chunks(10, [f"Trecho {i}" for i in range(5)], title="Título B")
    chunks_3 = _make_chunks(10, [f"Trecho {i}" for i in range(3)], title="Título A")

    # Só o título mudou: content_hash permanece igual, metadata_hash muda
    assert compute_content_hash(chunks_5) == compute_content_hash(chunks_5_new_title)
    assert (
        compute_metadata_hash("Título A", "/Knowledgebase/Article")
        != compute_metadata_hash("Título B", "/Knowledgebase/Article")
    )

    # Redução de 5 para 3 chunks: content_hash muda
    assert compute_content_hash(chunks_5) != compute_content_hash(chunks_3)


# ------------------------------------------------------------------ 3. Motor calculate_delta


def test_calculate_delta_initial_load_marks_all_as_new() -> None:
    fetched = [
        {"id": 1, "content_hash": "c1", "metadata_hash": "m1"},
        {"id": 2, "content_hash": "c2", "metadata_hash": "m2"},
    ]
    delta = calculate_delta({}, fetched, is_complete=True)

    assert delta == {
        "new": [1, 2],
        "content_modified": [],
        "metadata_modified": [],
        "same": [],
        "deleted": [],
    }


def test_calculate_delta_no_changes_marks_all_as_same() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},
        2: {"content_hash": "c2", "metadata_hash": "m2"},
    }
    fetched = [
        {"id": 1, "content_hash": "c1", "metadata_hash": "m1"},
        {"id": 2, "content_hash": "c2", "metadata_hash": "m2"},
    ]
    delta = calculate_delta(manifest_state, fetched, is_complete=True)

    assert delta == {
        "new": [],
        "content_modified": [],
        "metadata_modified": [],
        "same": [1, 2],
        "deleted": [],
    }


def test_calculate_delta_classifies_all_five_categories_when_complete() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},  # inalterado
        2: {"content_hash": "c2", "metadata_hash": "m2"},  # texto alterado
        3: {"content_hash": "c3", "metadata_hash": "m3"},  # só metadado alterado
        4: {"content_hash": "c4", "metadata_hash": "m4"},  # removido no GLPI
    }
    fetched = [
        {"id": 1, "content_hash": "c1", "metadata_hash": "m1"},
        {"id": 2, "content_hash": "c2-novo", "metadata_hash": "m2"},
        {"id": 3, "content_hash": "c3", "metadata_hash": "m3-novo"},
        {"id": 5, "content_hash": "c5", "metadata_hash": "m5"},  # novo
    ]
    delta = calculate_delta(manifest_state, fetched, is_complete=True)

    assert delta == {
        "new": [5],
        "content_modified": [2],
        "metadata_modified": [3],
        "same": [1],
        "deleted": [4],
    }


def test_calculate_delta_prioritizes_content_modified_over_metadata_modified() -> None:
    manifest_state = {10: {"content_hash": "c10", "metadata_hash": "m10"}}
    fetched = [{"id": 10, "content_hash": "c10-editado", "metadata_hash": "m10-editado"}]

    delta = calculate_delta(manifest_state, fetched, is_complete=True)

    assert delta["content_modified"] == [10]
    assert delta["metadata_modified"] == []


def test_calculate_delta_force_reembed_moves_unchanged_to_content_modified() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},
        2: {"content_hash": "c2", "metadata_hash": "m2"},
    }
    fetched = [
        {"id": 1, "content_hash": "c1", "metadata_hash": "m1"},
        {"id": 2, "content_hash": "c2", "metadata_hash": "m2-novo"},
    ]
    delta = calculate_delta(manifest_state, fetched, is_complete=True, force_reembed=True)

    assert delta["content_modified"] == [1, 2]
    assert delta["metadata_modified"] == []
    assert delta["same"] == []


def test_calculate_delta_incomplete_collection_never_deletes() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},
        2: {"content_hash": "c2", "metadata_hash": "m2"},
        3: {"content_hash": "c3", "metadata_hash": "m3"},
    }
    fetched = [{"id": 1, "content_hash": "c1", "metadata_hash": "m1"}]

    delta = calculate_delta(manifest_state, fetched, is_complete=False)

    assert delta["same"] == [1]
    assert delta["deleted"] == []


def test_calculate_delta_rejects_duplicate_article_ids() -> None:
    fetched = [
        {"id": 7, "content_hash": "c7", "metadata_hash": "m7"},
        {"id": 7, "content_hash": "c7", "metadata_hash": "m7"},
    ]
    with pytest.raises(ValueError, match="duplicado"):
        calculate_delta({}, fetched, is_complete=True)


# ------------------------------------------------------------------ 4. Travas de run_delta_sync


def test_run_delta_sync_blocks_incomplete_collection_without_touching_manifest(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    initial = {
        **empty_manifest(),
        "active_generation": 1,
        "last_checked_at": "2026-11-19T08:00:00+00:00",
        "last_published_at": "2026-11-19T08:00:00+00:00",
    }
    save_manifest_atomic(manifest_path, initial)

    prepare_called = False
    encode_called = False

    def _prepare(_article):
        nonlocal prepare_called
        prepare_called = True
        return []

    def _encode(_chunks):
        nonlocal encode_called
        encode_called = True
        raise AssertionError("Não deve chamar encode em coleta incompleta.")

    with pytest.raises(IncompleteCollectionError):
        run_delta_sync(
            store=_DummyStore(tmp_path),
            collect_fn=lambda: CollectionBatch(articles=[], is_complete=False),
            prepare_fn=_prepare,
            encode_fn=_encode,
            manifest_path=manifest_path,
        )

    assert prepare_called is False
    assert encode_called is False
    assert load_manifest(manifest_path) == initial


def test_run_delta_sync_rejects_invalid_batch_type(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="CollectionBatch"):
        run_delta_sync(
            store=_DummyStore(tmp_path),
            collect_fn=lambda: [],
            prepare_fn=lambda _a: [],
            encode_fn=lambda _c: None,
            manifest_path=tmp_path / "sync_manifest.json",
        )


def test_run_delta_sync_enforces_single_execution_lock_and_releases_on_error(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    store = _DummyStore(tmp_path)
    nested_blocked = False

    def _reentrant_collect() -> CollectionBatch:
        nonlocal nested_blocked
        try:
            run_delta_sync(
                store=store,
                collect_fn=lambda: CollectionBatch(articles=[], is_complete=False),
                prepare_fn=lambda _a: [],
                encode_fn=lambda _c: None,
                manifest_path=manifest_path,
            )
        except SyncAlreadyRunningError:
            nested_blocked = True
        raise RuntimeError("falha após testar concorrência")

    with pytest.raises(RuntimeError, match="falha após testar concorrência"):
        run_delta_sync(
            store=store,
            collect_fn=_reentrant_collect,
            prepare_fn=lambda _a: [],
            encode_fn=lambda _c: None,
            manifest_path=manifest_path,
        )

    assert nested_blocked is True

    # Após a falha, a trava precisa ter sido liberada (erro esperado agora é da coleta, não do lock)
    with pytest.raises(IncompleteCollectionError):
        run_delta_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=[], is_complete=False),
            prepare_fn=lambda _a: [],
            encode_fn=lambda _c: None,
            manifest_path=manifest_path,
        )