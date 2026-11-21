"""Testes unitários do manifesto atômico e da lógica de reconstrução controlada (ING-04 — Alternativa C)."""

import json
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src").is_dir()
)
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
    compute_source_signature,
    is_article_eligible,
    is_source_eligible,
    run_sync,
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
    """Stub mínimo de LocalIndexStore para testar travas de entrada sem tocar no índice."""

    def __init__(self, persist_dir: Path, source_type: str = "article") -> None:
        self.directory = persist_dir
        self.source_type = source_type


# ------------------------------------------------------------------ 1. Manifesto


def test_load_manifest_returns_empty_when_file_does_not_exist(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    assert load_manifest(manifest_path) == empty_manifest()


def test_save_and_load_manifest_roundtrip_normalizes_source_ids_to_int(tmp_path: Path) -> None:
    manifest_path = tmp_path / "nested" / "sync_manifest.json"
    original = {
        "active_generation": "00000000000000000001-abcdef",
        "source_type": "article",
        "embedding_config": {
            "model": "paraphrase-multilingual-MiniLM-L12-v2",
            "dimension": 384,
        },
        "preparation_version": "ing01-v1",
        "source_signature": "sig-abc123",
        "sources": {
            10: {
                "content_hash": "hash-c-10",
                "metadata_hash": "hash-m-10",
                "chunk_ids": ["ing01-v1:article:10:0000", "ing01-v1:article:10:0001"],
            }
        },
        "last_checked_at": "2026-11-21T01:00:00+00:00",
        "last_published_at": "2026-11-21T01:00:00+00:00",
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
        {"active_generation": "gen-1"},
        {**empty_manifest(), "active_generation": 1},
        {**empty_manifest(), "active_generation": "   "},
        {**empty_manifest(), "source_type": "ticket"},
        {**empty_manifest(), "source_type": ["article"]},
        {**empty_manifest(), "embedding_config": "invalido"},
        {**empty_manifest(), "preparation_version": ""},
        {**empty_manifest(), "source_signature": "   "},
        {**empty_manifest(), "sources": {-1: {"content_hash": "a", "metadata_hash": "b", "chunk_ids": []}}},
        {**empty_manifest(), "sources": {"abc": {"content_hash": "a", "metadata_hash": "b", "chunk_ids": []}}},
        {**empty_manifest(), "sources": {10: {"content_hash": "a"}}},
        {**empty_manifest(), "sources": {10: {"content_hash": "a", "metadata_hash": "b", "chunk_ids": [123]}}},
        {**empty_manifest(), "last_checked_at": 12345},
        {**empty_manifest(), "last_published_at": ""},
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
        "active_generation": "00000000000000000001-aaaaaa",
        "source_type": "article",
        "source_signature": "sig-v1",
        "last_checked_at": "2026-11-21T01:00:00+00:00",
        "last_published_at": "2026-11-21T01:00:00+00:00",
    }
    save_manifest_atomic(manifest_path, initial)

    def _broken_replace(src, dst):
        raise OSError("falha simulada na troca atômica")

    monkeypatch.setattr("src.rag.manifest.os.replace", _broken_replace)

    updated = {**initial, "active_generation": "00000000000000000002-bbbbbb"}
    with pytest.raises(OSError, match="falha simulada"):
        save_manifest_atomic(manifest_path, updated)

    assert load_manifest(manifest_path) == initial
    assert list(tmp_path.iterdir()) == [manifest_path]


# ------------------------------------------------------------------ 2. Elegibilidade, hashes e assinatura


def test_is_article_eligible_accepts_valid_and_name_fallback() -> None:
    valid = {
        "id": 42,
        "title": "Reset de senha",
        "content": "<p>Passo 1</p>",
        "source_reference": "/Knowledgebase/Article",
    }
    valid_with_name = {
        "id": 43,
        "name": "Artigo com campo name",
        "content": "Conteúdo",
        "source_reference": "/Knowledgebase/Article",
    }
    assert is_article_eligible(valid) is True
    assert is_article_eligible(valid_with_name) is True
    assert is_article_eligible({**valid, "eligible": False}) is False
    assert is_article_eligible({**valid, "is_deleted": True}) is False
    assert is_article_eligible({**valid, "id": True}) is False
    assert is_article_eligible({**valid, "id": -5}) is False
    assert is_article_eligible({**valid, "title": "   "}) is False
    assert is_article_eligible({**valid, "content": ""}) is False
    assert is_article_eligible({**valid, "source_reference": "/Assistance/Ticket"}) is False


def test_is_source_eligible_supports_case_type() -> None:
    valid_case = {
        "id": 100,
        "title": "Erro VPN Windows",
        "solution": "Reinstalar o cliente VPN",
        "source_reference": "/Assistance/Ticket",
    }
    assert is_source_eligible({**valid_case, "source_reference": "/Assistance/Ticket/100"}, source_type="case") is False
    assert is_source_eligible(valid_case, source_type="case") is True
    assert is_source_eligible({**valid_case, "eligible": False}, source_type="case") is False
    assert is_source_eligible({**valid_case, "solution": "   "}, source_type="case") is False
    assert is_source_eligible({**valid_case, "source_reference": "/Knowledgebase/Article"}, source_type="case") is False
    with pytest.raises(ValueError, match="source_type"):
        is_source_eligible(valid_case, source_type="unknown")


def test_content_metadata_hashes_and_global_signature_are_deterministic() -> None:
    chunks_5 = _make_chunks(10, [f"Trecho {i}" for i in range(5)], title="Título A")
    chunks_5_new_title = _make_chunks(10, [f"Trecho {i}" for i in range(5)], title="Título B")
    chunks_3 = _make_chunks(10, [f"Trecho {i}" for i in range(3)], title="Título A")

    assert compute_content_hash(chunks_5) == compute_content_hash(chunks_5_new_title)
    assert (
        compute_metadata_hash("Título A", "/Knowledgebase/Article")
        != compute_metadata_hash("Título B", "/Knowledgebase/Article")
    )
    assert compute_content_hash(chunks_5) != compute_content_hash(chunks_3)

    state_a = {
        2: {"content_hash": "c2", "metadata_hash": "m2", "chunk_ids": ["k2"]},
        1: {"content_hash": "c1", "metadata_hash": "m1", "chunk_ids": ["k1"]},
    }
    state_b = {
        1: {"content_hash": "c1", "metadata_hash": "m1", "chunk_ids": ["k1"]},
        2: {"content_hash": "c2", "metadata_hash": "m2", "chunk_ids": ["k2"]},
    }
    assert compute_source_signature(state_a) == compute_source_signature(state_b)
    assert compute_source_signature(state_a, "article") != compute_source_signature(state_a, "case")


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


def test_calculate_delta_classifies_all_five_categories_when_complete() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},
        2: {"content_hash": "c2", "metadata_hash": "m2"},
        3: {"content_hash": "c3", "metadata_hash": "m3"},
        4: {"content_hash": "c4", "metadata_hash": "m4"},
    }
    fetched = [
        {"id": 1, "content_hash": "c1", "metadata_hash": "m1"},
        {"id": 2, "content_hash": "c2-novo", "metadata_hash": "m2"},
        {"id": 3, "content_hash": "c3", "metadata_hash": "m3-novo"},
        {"id": 5, "content_hash": "c5", "metadata_hash": "m5"},
    ]
    delta = calculate_delta(manifest_state, fetched, is_complete=True)

    assert delta == {
        "new": [5],
        "content_modified": [2],
        "metadata_modified": [3],
        "same": [1],
        "deleted": [4],
    }


def test_calculate_delta_prioritizes_content_modified_and_supports_force_reembed() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},
        2: {"content_hash": "c2", "metadata_hash": "m2"},
    }
    fetched = [
        {"id": 1, "content_hash": "c1-novo", "metadata_hash": "m1-novo"},
        {"id": 2, "content_hash": "c2", "metadata_hash": "m2"},
    ]
    normal = calculate_delta(manifest_state, fetched, is_complete=True)
    assert normal["content_modified"] == [1]
    assert normal["metadata_modified"] == []
    assert normal["same"] == [2]

    forced = calculate_delta(manifest_state, fetched, is_complete=True, force_reembed=True)
    assert forced["content_modified"] == [1, 2]
    assert forced["same"] == []


def test_calculate_delta_incomplete_collection_never_deletes_and_rejects_duplicates() -> None:
    manifest_state = {
        1: {"content_hash": "c1", "metadata_hash": "m1"},
        2: {"content_hash": "c2", "metadata_hash": "m2"},
    }
    delta = calculate_delta(
        manifest_state,
        [{"id": 1, "content_hash": "c1", "metadata_hash": "m1"}],
        is_complete=False,
    )
    assert delta["same"] == [1]
    assert delta["deleted"] == []

    with pytest.raises(ValueError, match="duplicado"):
        calculate_delta(
            {},
            [
                {"id": 7, "content_hash": "c7", "metadata_hash": "m7"},
                {"id": 7, "content_hash": "c7", "metadata_hash": "m7"},
            ],
            is_complete=True,
        )


# ------------------------------------------------------------------ 4. Travas de run_sync


def test_run_sync_blocks_incomplete_collection_without_touching_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    initial = {
        **empty_manifest(),
        "active_generation": "00000000000000000001-aaaaaa",
        "source_type": "article",
        "source_signature": "sig-v1",
        "last_checked_at": "2026-11-21T01:00:00+00:00",
        "last_published_at": "2026-11-21T01:00:00+00:00",
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
        run_sync(
            store=_DummyStore(tmp_path),
            collect_fn=lambda: CollectionBatch(articles=[], is_complete=False),
            prepare_fn=_prepare,
            encode_fn=_encode,
            manifest_path=manifest_path,
        )

    assert prepare_called is False
    assert encode_called is False
    assert load_manifest(manifest_path) == initial


def test_run_sync_rejects_invalid_batch_type(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="CollectionBatch"):
        run_sync(
            store=_DummyStore(tmp_path),
            collect_fn=lambda: [],
            prepare_fn=lambda _a: [],
            encode_fn=lambda _c: None,
            manifest_path=tmp_path / "sync_manifest.json",
        )


def test_run_sync_enforces_single_execution_lock_and_releases_on_error(tmp_path: Path) -> None:
    manifest_path = tmp_path / "sync_manifest.json"
    store = _DummyStore(tmp_path)
    nested_blocked = False

    def _reentrant_collect() -> CollectionBatch:
        nonlocal nested_blocked
        try:
            run_sync(
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
        run_sync(
            store=store,
            collect_fn=_reentrant_collect,
            prepare_fn=lambda _a: [],
            encode_fn=lambda _c: None,
            manifest_path=manifest_path,
        )

    assert nested_blocked is True

    # Após a falha, a trava foi liberada no finally
    with pytest.raises(IncompleteCollectionError):
        run_sync(
            store=store,
            collect_fn=lambda: CollectionBatch(articles=[], is_complete=False),
            prepare_fn=lambda _a: [],
            encode_fn=lambda _c: None,
            manifest_path=manifest_path,
        )