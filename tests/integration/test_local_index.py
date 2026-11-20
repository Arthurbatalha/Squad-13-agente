"""ING-03: índice local por gerações, em diretório temporário, sem modelo/Gemini/Chroma."""

from dataclasses import replace
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rag.chunk_contract import PREPARATION_VERSION
from src.rag.corpus import CorpusMetadata, CorpusUnavailable, PreparedCorpus
from src.rag.embeddings import DEFAULT_CONFIG, IncompatibleConfig
from src.rag.local_index import IndexCorrupt, LocalIndexStore
from test.embedding_fakes import chunk, unit




def corpus_of(chunks, vectors=None, config=DEFAULT_CONFIG):
    vectors = np.stack([unit(i % 384) for i in range(len(chunks))]) if vectors is None and chunks \
        else (np.empty((0, 384), dtype=np.float32) if vectors is None else vectors)
    meta = CorpusMetadata(config, PREPARATION_VERSION, tuple(c["chunk_id"] for c in chunks))
    return PreparedCorpus(tuple(chunks), vectors, meta)


def corpus_v1():
    return corpus_of([chunk(0, "A zero", source_id=17), chunk(1, "A um", source_id=17),
                      chunk(0, "B zero", source_id=29)])


@pytest.fixture
def store(tmp_path):
    return LocalIndexStore(tmp_path, "article")


def publish(store, corpus):
    info = store.create_candidate(corpus)
    store.activate(info.generation_id)
    return info


def test_survives_restart_with_identical_contents(tmp_path):
    original = corpus_v1()
    info = publish(LocalIndexStore(tmp_path, "article"), original)
    reopened = LocalIndexStore(tmp_path, "article")  # "reinício": nova instância, sem estado
    with reopened.open_active() as active:
        assert active.generation_id == info.generation_id
        assert [dict(c) for c in active.corpus.chunks] == [dict(c) for c in original.chunks]
        assert np.array_equal(active.corpus.vectors, original.vectors)
        assert active.corpus.vectors.dtype == np.float32
        assert not active.corpus.vectors.flags.writeable


def test_survives_restart_in_a_new_process(tmp_path):
    publish(LocalIndexStore(tmp_path, "article"), corpus_v1())
    script = (
        "import sys; from src.rag.local_index import LocalIndexStore\n"
        "s = LocalIndexStore(sys.argv[1], 'article')\n"
        "with s.open_active() as a: print(len(a.corpus.chunks), a.corpus.vectors.shape)\n")
    out = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    assert out.split(None, 1)[0] == "3" and "(3, 384)" in out


def test_no_active_generation_is_unavailable_not_empty(store):
    with pytest.raises(CorpusUnavailable):
        store.open_active()
    assert store.active_generation_id() is None


def test_valid_empty_corpus_is_distinct_from_unavailable(store):
    publish(store, corpus_of([]))
    with store.open_active() as active:
        assert active.corpus.chunks == () and active.corpus.vectors.shape == (0, 384)


def test_ids_are_not_duplicated_across_generations_or_within_one(store):
    with pytest.raises(ValueError, match="duplicado"):
        corpus_of([chunk(0, "x"), chunk(0, "y")])
    first, second = publish(store, corpus_v1()), publish(store, corpus_v1())
    assert first.generation_id != second.generation_id
    with store.open_active() as active:
        ids = [c["chunk_id"] for c in active.corpus.chunks]
        assert len(ids) == len(set(ids)) == 3  # nova geração substitui, não acumula


def test_candidate_does_not_change_active_and_is_readable_in_full(store):
    active = publish(store, corpus_v1())
    candidate = store.create_candidate(corpus_of([chunk(0, "novo", source_id=99)]))
    assert store.active_generation_id() == active.generation_id
    assert [c["source_id"] for c in store.read_candidate(candidate.generation_id).chunks] == [99]
    with store.open_active() as current:
        assert len(current.corpus.chunks) == 3


@pytest.mark.parametrize("mutate", [
    lambda c: replace(c, model="outro/modelo"),
    lambda c: replace(c, revision="0" * 40),
    lambda c: replace(c, normalize=False),
    lambda c: replace(c, device="cuda"),
])
def test_rejects_incompatible_embedding_config_even_with_same_dimension(tmp_path, mutate):
    other = mutate(DEFAULT_CONFIG)
    foreign = LocalIndexStore(tmp_path, "article", embedding=other)
    with pytest.raises(IncompatibleConfig):
        LocalIndexStore(tmp_path, "article").create_candidate(corpus_of([chunk(0)], config=other))
    # Índice gravado com a configuração padrão é recusado por quem espera outra.
    info = publish(LocalIndexStore(tmp_path, "article"), corpus_v1())
    with pytest.raises(IncompatibleConfig):
        foreign.read_candidate(info.generation_id)
    with pytest.raises(IncompatibleConfig):
        foreign.activate(info.generation_id)


def test_rejects_incompatible_vectors(store):
    for bad in (np.ones((1, 384), dtype=np.float32),          # sem norma 1
                np.full((1, 384), np.nan, dtype=np.float32),  # não finito
                np.zeros((1, 100), dtype=np.float32)):        # dimensão
        with pytest.raises(ValueError):
            corpus_of([chunk(0)], bad)
    with pytest.raises(ValueError):
        corpus_of([chunk(0), chunk(1)], np.stack([unit(0)]))  # quantidade


def test_rejects_wrong_preparation_version_and_source_type(store):
    old = dict(chunk(0), preparation_version="ing-01-v1")
    with pytest.raises(IncompatibleConfig):
        corpus_of([old])
    with pytest.raises(ValueError, match="somente article"):
        store.create_candidate(corpus_of([chunk(0, source_type="case", source_id=5)]))
    stale = corpus_of([chunk(0)])
    object.__setattr__(stale.metadata, "preparation_version", "ing-01-v1")
    with pytest.raises(IncompatibleConfig):
        store.create_candidate(stale)


def test_detects_tampered_or_missing_files_and_never_activates_them(store):
    info = store.create_candidate(corpus_v1())
    directory = store.directory / f"gen-{info.generation_id}"
    catalog = directory / "catalog.json"
    good = catalog.read_text(encoding="utf-8")
    catalog.write_text(good.replace("A zero", "A ZERO"), encoding="utf-8")
    with pytest.raises(IndexCorrupt):
        store.activate(info.generation_id)
    assert store.active_generation_id() is None
    catalog.write_text(good, encoding="utf-8")
    store.activate(info.generation_id)
    np.save(directory / "vectors.npy", np.stack([unit(0), unit(1), unit(2)])[::-1].copy())
    with pytest.raises(IndexCorrupt):
        store.open_active()
    (directory / "manifest.json").unlink()
    with pytest.raises(IndexCorrupt):
        store.open_active()


def test_corrupt_pointer_is_an_error(store):
    publish(store, corpus_v1())
    (store.directory / "ACTIVE").write_text("gen-inexistente", encoding="ascii")
    with pytest.raises(IndexCorrupt):
        store.open_active()


def test_capture_finishes_in_its_generation_while_active_changes(store):
    first = publish(store, corpus_v1())
    reader = store.open_active()
    second = publish(store, corpus_of([chunk(0, "só a nova", source_id=50)]))
    assert store.active_generation_id() == second.generation_id
    assert reader.generation_id == first.generation_id            # leitor segue na antiga
    assert {c["source_id"] for c in reader.corpus.chunks} == {17, 29}
    with store.open_active() as fresh:                             # novo leitor vê a nova
        assert {c["source_id"] for c in fresh.corpus.chunks} == {50}
    reader.close()


def test_cleanup_keeps_active_previous_pending_and_captured(store):
    g1 = publish(store, corpus_v1()); reader = store.open_active()
    g2 = publish(store, corpus_v1()); g3 = publish(store, corpus_v1())
    pending = store.create_candidate(corpus_v1())                  # candidata não publicada
    assert store.cleanup() == []                                   # g1 capturada; g2 anterior
    assert set(store._generation_ids()) == {g.generation_id for g in (g1, g2, g3, pending)}
    reader.close()
    assert store.cleanup() == [g1.generation_id]
    assert set(store._generation_ids()) == {g.generation_id for g in (g2, g3, pending)}
    assert store.cleanup(keep_previous=0) == [g2.generation_id]
    with store.open_active() as active:                            # ativa intacta
        assert active.generation_id == g3.generation_id and len(active.corpus.chunks) == 3
    assert store.read_candidate(pending.generation_id).chunks


def test_cleanup_without_active_removes_nothing_and_drops_stale_temp_dirs(store):
    candidate = store.create_candidate(corpus_v1())
    assert store.cleanup() == []
    publish(store, corpus_v1())
    (store.directory / ".tmp-interrompida").mkdir()
    store.cleanup()
    assert not (store.directory / ".tmp-interrompida").exists()
    assert (store.directory / f"gen-{candidate.generation_id}").exists()


def test_failed_write_leaves_active_untouched_and_no_partial_generation(store, monkeypatch):
    active = publish(store, corpus_v1())
    before = store._generation_ids()
    monkeypatch.setattr("src.rag.local_index._write_file",
                        lambda path, data: (_ for _ in ()).throw(OSError("disco cheio")))
    with pytest.raises(OSError):
        store.create_candidate(corpus_of([chunk(0, "x", source_id=1)]))
    monkeypatch.undo()
    assert store._generation_ids() == before
    assert not list(store.directory.glob(".tmp-*"))
    with store.open_active() as current:
        assert current.generation_id == active.generation_id


def test_article_and_case_indexes_are_independent(tmp_path):
    articles, cases = LocalIndexStore(tmp_path, "article"), LocalIndexStore(tmp_path, "case")
    publish(articles, corpus_v1())
    publish(cases, corpus_of([chunk(0, "caso", source_type="case", source_id=7)]))
    with articles.open_active() as a, cases.open_active() as c:
        assert {x["source_type"] for x in a.corpus.chunks} == {"article"}
        assert {x["source_type"] for x in c.corpus.chunks} == {"case"}
    publish(articles, corpus_of([chunk(0, "novo")]))  # publicar artigos não mexe em casos
    with cases.open_active() as c:
        assert [x["source_id"] for x in c.corpus.chunks] == [7]


def test_source_records_are_separate_from_generation_info(store):
    info = store.create_candidate(corpus_v1(), source_signature="sha-fontes")
    directory = store.directory / f"gen-{info.generation_id}"
    catalog = json.loads((directory / "catalog.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert {s["source_id"]: len(s["chunk_ids"]) for s in catalog["sources"]} == {17: 2, 29: 1}
    assert all("vector" not in c for c in catalog["chunks"]) and "created_at" not in catalog
    assert manifest["embedding"]["model"] == DEFAULT_CONFIG.model and manifest["source_signature"] == "sha-fontes"
    assert store.generation_info(info.generation_id).source_signature == "sha-fontes"


def test_reusable_vectors_copy_only_identical_chunks(store):
    publish(store, corpus_v1())
    new = [chunk(0, "A zero", source_id=17),      # igual
           chunk(1, "A um EDITADO", source_id=17),  # mesmo ID, conteúdo mudou
           chunk(0, "C", source_id=40)]           # novo
    reused = store.reusable_vectors(new)
    assert set(reused) == {new[0]["chunk_id"]}
    assert np.array_equal(reused[new[0]["chunk_id"]], unit(0))
    reused[new[0]["chunk_id"]][:] = 0                               # cópia, não a matriz ativa
    with store.open_active() as active:
        assert np.array_equal(active.corpus.vectors[0], unit(0))
    assert LocalIndexStore(store.directory.parent, "case").reusable_vectors([chunk(0, source_type="case")]) == {}


def test_does_not_import_chroma_or_models_or_decide_authorization():
    script = (
        "import importlib.abc, sys\n"
        "class G(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, n, p=None, t=None):\n"
        "        if n.split('.')[0] in ('chromadb','sentence_transformers','torch','transformers'):\n"
        "            raise AssertionError(n)\n"
        "sys.meta_path.insert(0, G())\n"
        "import src.rag.local_index\n")
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True)
