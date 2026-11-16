"""ING-03: Chroma real em diretório temporário, coleções por geração."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pytest

from src.rag.chroma_config import IndexConfig
from src.rag.chroma_store import (
    ChromaGenerationStore, GenerationNotFound, IncompatibleIndex, NoActiveGeneration,
)
from src.rag.chunk_contract import PREPARATION_VERSION

DIM = 384
CONFIG = IndexConfig(model="intfloat/multilingual-e5-small", revision="rev-teste", dimension=DIM)


def vector_for(content: str) -> np.ndarray:
    seed = int(hashlib.sha256(content.encode()).hexdigest()[:8], 16)
    raw = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return raw / np.linalg.norm(raw)


def make_chunk(source_id, ordinal, content, *, title=None, source_type="article"):
    return {
        "source_type": source_type, "source_id": source_id,
        "source_reference": "/Knowledgebase/Article" if source_type == "article" else "/Assistance/Ticket",
        "title": title or f"Artigo {source_id}", "content": content,
        "chunk_id": f"{PREPARATION_VERSION}:{source_type}:{source_id}:{ordinal:04d}",
        "preparation_version": PREPARATION_VERSION,
    }


def corpus():
    chunks = [make_chunk(1, 0, "VPN corporativa não conecta"), make_chunk(1, 1, "Reinstale o cliente VPN"),
              make_chunk(2, 0, "Impressora sem papel")]
    return chunks, np.stack([vector_for(c["content"]) for c in chunks])


@pytest.fixture
def store(tmp_path):
    return ChromaGenerationStore(tmp_path / "chroma", CONFIG)


def published(store):
    chunks, vectors = corpus()
    generation = store.create_candidate(chunks, vectors)
    store.activate(generation)
    return generation, chunks, vectors


def test_index_survives_real_process_restart(tmp_path):
    first = ChromaGenerationStore(tmp_path / "chroma", CONFIG)
    generation, chunks, vectors = published(first)
    code = (
        "import json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import numpy as np\n"
        "from src.rag.chroma_config import IndexConfig\n"
        "from src.rag.chroma_store import ChromaGenerationStore\n"
        "config = IndexConfig(model='intfloat/multilingual-e5-small', revision='rev-teste', dimension=384)\n"
        "store = ChromaGenerationStore(sys.argv[2], config)\n"
        "with store.capture_active() as reader:\n"
        "    hits = reader.query(np.array(json.loads(sys.argv[3]), dtype=np.float32), limit=1)\n"
        "    print(json.dumps({'generation': reader.generation, 'chunk_id': hits[0]['chunk_id']}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT), str(tmp_path / "chroma"), json.dumps(vectors[2].tolist())],
        capture_output=True, text=True, check=True, timeout=120,
    )
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"generation": generation, "chunk_id": chunks[2]["chunk_id"]}


def test_duplicate_chunk_ids_are_rejected_and_nothing_is_created(store):
    chunks, vectors = corpus()
    with pytest.raises(ValueError, match="duplicado"):
        store.create_candidate(chunks + [chunks[0]], np.vstack([vectors, vectors[:1]]))
    assert store.generations() == []


def test_same_corpus_twice_does_not_duplicate_ids_inside_a_generation(store):
    chunks, vectors = corpus()
    first = store.create_candidate(chunks, vectors)
    second = store.create_candidate(chunks, vectors)
    assert first != second
    for generation in (first, second):
        snapshot = store.read_generation(generation)
        assert [c["chunk_id"] for c in snapshot.chunks] == [c["chunk_id"] for c in chunks]


@pytest.mark.parametrize("bad", ["dimension", "count", "norm", "nan"])
def test_incompatible_vectors_are_rejected_without_leftovers(store, bad):
    chunks, vectors = corpus()
    if bad == "dimension":
        vectors = vectors[:, :100]
    elif bad == "count":
        vectors = vectors[:2]
    elif bad == "norm":
        vectors = vectors * 2
    else:
        vectors = vectors.copy()
        vectors[0, 0] = np.nan
    with pytest.raises(ValueError):
        store.create_candidate(chunks, vectors)
    assert store.generations() == []


def test_store_with_other_embedding_config_cannot_activate_or_read(tmp_path):
    generation, *_ = published(ChromaGenerationStore(tmp_path / "chroma", CONFIG))
    other_model = IndexConfig(model="intfloat/multilingual-e5-base", revision="rev-teste", dimension=DIM)
    other_dim = IndexConfig(model=CONFIG.model, revision=CONFIG.revision, dimension=768)
    for config in (other_model, other_dim):
        other = ChromaGenerationStore(tmp_path / "chroma", config)
        with pytest.raises(IncompatibleIndex):
            other.capture_active()
        with pytest.raises(IncompatibleIndex):
            other.read_generation(generation)
        with pytest.raises(IncompatibleIndex):
            other.activate(generation)


def test_similarity_is_cosine_not_euclidean(store):
    base = np.zeros(DIM, dtype=np.float32)
    base[0] = 1
    query = np.zeros(DIM, dtype=np.float32)
    query[0], query[1] = 0.5, np.sqrt(0.75)  # 60 graus: cosseno 0,5 (L2 ao quadrado daria score 0)
    generation = store.create_candidate([make_chunk(1, 0, "a")], base[None, :])
    store.activate(generation)
    with store.capture_active() as reader:
        (hit,) = reader.query(query, limit=1)
    assert hit["score"] == pytest.approx(0.5, abs=1e-4)


def test_query_rejects_unnormalized_or_wrong_dimension_vectors(store):
    published(store)
    with store.capture_active() as reader:
        with pytest.raises(ValueError):
            reader.query(np.ones(DIM, dtype=np.float32), limit=1)
        with pytest.raises(ValueError):
            reader.query(vector_for("x")[:10], limit=1)


def test_complete_candidate_is_readable_but_not_active_until_activated(store):
    chunks, vectors = corpus()
    generation = store.create_candidate(chunks, vectors)
    snapshot = store.read_generation(generation)
    assert [c["chunk_id"] for c in snapshot.chunks] == [c["chunk_id"] for c in chunks]
    assert [c["content"] for c in snapshot.chunks] == [c["content"] for c in chunks]
    np.testing.assert_allclose(snapshot.vectors, vectors, atol=1e-6)
    assert snapshot.info.status == "complete"
    assert store.active_generation() is None
    with pytest.raises(NoActiveGeneration):
        store.capture_active()
    store.activate(generation)
    assert store.active_generation() == generation


def test_unknown_generation_is_reported(store):
    with pytest.raises(GenerationNotFound):
        store.read_generation(99)
    with pytest.raises(GenerationNotFound):
        store.activate(99)


def test_source_records_are_separate_from_generation_info(store):
    generation, chunks, _ = published(store)
    sources = {(s["source_type"], s["source_id"]): s for s in store.sources(generation)}
    assert sources[("article", 1)] == {
        "source_type": "article", "source_id": 1, "source_reference": "/Knowledgebase/Article",
        "title": "Artigo 1", "chunk_ids": [chunks[0]["chunk_id"], chunks[1]["chunk_id"]],
    }
    info = store.generation_info(generation)
    assert (info.chunk_count, info.source_count, info.active) == (3, 2, True)
    assert not hasattr(info, "title") and "Artigo 1" not in repr(info)


def test_compatible_vectors_are_copied_and_only_new_or_changed_chunks_are_encoded(store):
    generation, chunks, vectors = published(store)
    changed = make_chunk(2, 0, "Impressora sem toner")
    new = make_chunk(3, 0, "Senha expirada")
    requested = []

    def encode_missing(missing):
        requested.extend(c["chunk_id"] for c in missing)
        return np.stack([vector_for(c["content"]) for c in missing])

    candidate = store.create_candidate([chunks[0], chunks[1], changed, new],
                                       encode_missing=encode_missing, reuse_from=generation)
    assert requested == [changed["chunk_id"], new["chunk_id"]]
    snapshot = store.read_generation(candidate)
    np.testing.assert_allclose(snapshot.vectors[:2], vectors[:2], atol=1e-6)
    np.testing.assert_allclose(snapshot.vectors[2], vector_for("Impressora sem toner"), atol=1e-6)


def test_reuse_from_incompatible_generation_is_refused(tmp_path):
    other = ChromaGenerationStore(tmp_path / "chroma", IndexConfig(model="outro", revision="r", dimension=DIM))
    chunks, vectors = corpus()
    old = other.create_candidate(chunks, vectors)
    store = ChromaGenerationStore(tmp_path / "chroma", CONFIG)
    with pytest.raises(IncompatibleIndex):
        store.create_candidate(chunks, encode_missing=lambda m: vectors[: len(m)], reuse_from=old)


def test_missing_vectors_without_encoder_are_an_error(store):
    chunks, _ = corpus()
    with pytest.raises(ValueError):
        store.create_candidate(chunks)
    assert store.generations() == []


def test_failed_candidate_leaves_active_generation_untouched(store):
    generation, chunks, vectors = published(store)

    def boom(missing):
        raise OSError("falha ao embutir")

    with pytest.raises(OSError):
        store.create_candidate([make_chunk(9, 0, "novo")], encode_missing=boom, reuse_from=generation)
    assert [g.generation for g in store.generations()] == [generation]
    with store.capture_active() as reader:
        assert reader.query(vectors[0], limit=1)[0]["chunk_id"] == chunks[0]["chunk_id"]


def test_captured_reader_finishes_in_its_generation_and_cleanup_waits_for_it(store):
    old, chunks, vectors = published(store)
    reader = store.capture_active()
    new = store.create_candidate([make_chunk(7, 0, "Conteúdo novo")], np.stack([vector_for("Conteúdo novo")]))
    store.activate(new)
    assert store.active_generation() == new
    assert reader.generation == old
    assert reader.query(vectors[0], limit=1)[0]["chunk_id"] == chunks[0]["chunk_id"]
    assert store.cleanup(keep_previous=0) == []  # há leitor na geração anterior
    assert reader.query(vectors[2], limit=1)[0]["chunk_id"] == chunks[2]["chunk_id"]
    reader.close()
    assert store.cleanup(keep_previous=0) == [old]
    with pytest.raises(GenerationNotFound):
        store.read_generation(old)
    with store.capture_active() as fresh:
        assert fresh.generation == new
        assert fresh.query(vector_for("Conteúdo novo"), limit=1)[0]["source_id"] == 7


def test_cleanup_never_touches_active_or_newer_candidates_and_honours_keep_previous(store):
    chunks, vectors = corpus()
    gens = [store.create_candidate(chunks, vectors) for _ in range(4)]
    store.activate(gens[2])
    assert store.cleanup(keep_previous=1) == [gens[0]]
    assert [g.generation for g in store.generations()] == [gens[1], gens[2], gens[3]]
    assert store.active_generation() == gens[2]
    snapshot = store.read_generation(gens[2])
    assert len(snapshot.chunks) == 3


def test_cleanup_removes_leftover_building_generation_from_a_crash(store, tmp_path):
    generation, *_ = published(store)
    with sqlite3.connect(tmp_path / "chroma" / "control.sqlite3") as db:
        db.execute("INSERT INTO generations (status, config_json, chunk_count, source_count, created_at, collection)"
                   " VALUES ('building', '{}', 0, 0, '2026-01-01T00:00:00+00:00', 'chunks_g000999')")
    assert [g.status for g in store.generations()] == ["complete", "building"]
    assert len(store.cleanup(keep_previous=1)) == 1
    assert [g.generation for g in store.generations()] == [generation]


def test_activating_a_building_generation_is_refused(store, tmp_path):
    published(store)
    with sqlite3.connect(tmp_path / "chroma" / "control.sqlite3") as db:
        db.execute("INSERT INTO generations (status, config_json, chunk_count, source_count, created_at, collection)"
                   " VALUES ('building', '{}', 0, 0, '2026-01-01T00:00:00+00:00', 'chunks_g000999')")
        building = db.execute("SELECT MAX(id) FROM generations").fetchone()[0]
    with pytest.raises(ValueError, match="complet"):
        store.activate(building)


def test_empty_candidate_is_a_valid_complete_generation(store):
    generation = store.create_candidate([], np.empty((0, DIM), dtype=np.float32))
    store.activate(generation)
    with store.capture_active() as reader:
        assert reader.query(vector_for("qualquer"), limit=3) == []
    assert store.read_generation(generation).chunks == ()
