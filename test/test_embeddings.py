"""ING-02: contratos e reutilização com modelo injetado, sem pesos/rede."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from threading import Barrier
import threading
import time
from types import ModuleType
from unittest.mock import Mock
import numpy as np
import pytest
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.rag.busca_artigos import buscar_artigos
from src.rag.chunk_contract import MINILM_MODEL, MINILM_REVISION, PREPARATION_VERSION
from src.rag.corpus import CorpusService, CorpusUnavailable, PreparedCorpus
from src.rag.embeddings import (
    DEFAULT_CONFIG, EmbeddingService, EmbeddingUnavailable, IncompatibleConfig,
    TokenLimitError, validate_vectors,
)
from test.embedding_fakes import ModelSpy, articles, chunk, unit


def test_imports_and_construction_do_not_import_or_download_models():
    script = '''
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('sentence_transformers', 'transformers', 'torch'):
            raise AssertionError('Importacao de modelo durante importacao de modulo')
sys.meta_path.insert(0, Guard())
from src.rag.embeddings import EmbeddingService
from src.rag.corpus import CorpusService, get_search_service
from src.rag.busca_artigos import buscar_artigos
assert EmbeddingService().stats['model_loads'] == 0
assert get_search_service() is get_search_service()
assert buscar_artigos('', []) == []
'''
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                   check=True, capture_output=True, text=True, timeout=30)


def test_real_loader_receives_same_fixed_revision_and_cpu(monkeypatch):
    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = Mock(return_value=ModelSpy())
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    hub = ModuleType("huggingface_hub")
    snapshot = f"/cache/snapshots/{MINILM_REVISION}"
    hub.snapshot_download = Mock(return_value=snapshot)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    service = EmbeddingService(local_files_only=True)
    assert module.SentenceTransformer.call_count == 0
    service.load()
    service.encode_question("pergunta")
    assert hub.snapshot_download.call_args.args == (MINILM_MODEL,)
    assert hub.snapshot_download.call_args.kwargs["revision"] == MINILM_REVISION
    assert hub.snapshot_download.call_args.kwargs["local_files_only"] is True
    module.SentenceTransformer.assert_called_once_with(
        snapshot, revision=MINILM_REVISION, device="cpu", local_files_only=True, trust_remote_code=False,
    )
    assert service.runtime_info()["weights_and_tokenizer_snapshot"] == snapshot


def test_concurrent_calls_share_one_loaded_instance_and_serialized_encoder():
    class ConcurrentSpy(ModelSpy):
        def __init__(self):
            super().__init__()
            self.active, self.maximum = 0, 0
            self.counter_lock = threading.Lock()

        def encode(self, texts, **kwargs):
            with self.counter_lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            try:
                time.sleep(0.01)  # Libera o GIL para detectar sobreposição de chamadas.
                return super().encode(texts, **kwargs)
            finally:
                with self.counter_lock:
                    self.active -= 1
    spy = ConcurrentSpy()
    factory = Mock(return_value=spy)
    service = EmbeddingService(model_factory=factory)
    barrier = Barrier(4)
    def query(_):
        barrier.wait()
        return service.encode_question("pergunta")
    with ThreadPoolExecutor(max_workers=4) as pool:
        vectors = list(pool.map(query, range(4)))
    assert factory.call_count == 1 and service.stats["model_loads"] == 1
    assert spy.maximum == 1
    assert service.stats["question_texts"] == 4
    assert all(np.array_equal(vector, unit()) for vector in vectors)


def test_batches_preserve_exact_input_order_and_plain_text_configuration():
    spy = ModelSpy()
    service = EmbeddingService(model=spy, batch_size=2)
    chunks = [chunk(i, f"  FONTE_{'B' if i % 2 else 'A'} passo {i}\n") for i in range(5)]
    original = deepcopy(chunks)
    vectors = service.encode_chunks(chunks)
    assert [len(texts) for texts, _ in spy.calls] == [2, 2, 1]
    assert [text for texts, _ in spy.calls for text in texts] == [item["content"] for item in chunks]
    for _, options in spy.calls:
        assert options == {"batch_size": 2, "normalize_embeddings": True, "convert_to_numpy": True,
                           "show_progress_bar": False, "precision": "float32", "prompt": "", "device": "cpu"}
    assert vectors.shape == (5, 384) and vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    assert np.array_equal(vectors[1], unit(1)) and np.array_equal(vectors[2], unit(0))
    assert chunks == original


@pytest.mark.parametrize("output", [np.zeros((1, 384)), np.ones((1, 384)),
    np.full((1, 384), np.nan), np.full((1, 384), np.inf), np.zeros((2, 384)),
    np.zeros((1, 383)), np.zeros(384), np.full((1, 384), "1"), np.ones((1, 384), dtype=bool)])
def test_invalid_encoder_output_is_rejected(output):
    spy = ModelSpy()
    spy.transform = lambda _: output
    with pytest.raises(ValueError):
        EmbeddingService(model=spy).encode_question("pergunta")


@pytest.mark.parametrize("question", ["", "  ", "\n", None, 17, ["texto"]])
def test_empty_or_invalid_question_is_explicit_before_loading(question):
    factory = Mock()
    with pytest.raises((TypeError, ValueError)):
        EmbeddingService(model_factory=factory).encode_question(question)
    factory.assert_not_called()


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5])
def test_invalid_batch_size(batch_size):
    with pytest.raises(ValueError):
        EmbeddingService(batch_size=batch_size)


def test_limits_include_special_tokens_and_validate_all_inputs_before_encode():
    spy = ModelSpy()
    service = EmbeddingService(model=spy, batch_size=1)
    exact = "palavra " * 126  # 126 + 2 especiais = 128
    assert service.encode_question(exact).shape == (384,)
    assert spy.calls[-1][0] == [exact]
    spy.calls.clear()
    with pytest.raises(TokenLimitError, match="129 tokens, limite 128"):
        service.encode_question("palavra " * 127)
    with pytest.raises(TokenLimitError, match="Documento"):
        service.encode_chunks([chunk(0), chunk(1, "palavra " * 127)])
    assert spy.calls == []


@pytest.mark.parametrize("field,value", [("max_seq_length", 512), ("get_sentence_embedding_dimension", lambda: 383)])
def test_effective_model_configuration_is_checked(field, value):
    spy = ModelSpy()
    setattr(spy, field, value)
    with pytest.raises(IncompatibleConfig):
        EmbeddingService(model=spy).load()
    assert not spy.calls


@pytest.mark.parametrize("change", [{"model": "outro-modelo"}, {"revision": "outra-revisao"},
    {"normalize": False}, {"max_tokens": 512}, {"input_format": "query/passage"}, {"device": "cuda"}])
def test_unsupported_config_rejected_even_with_384_dimensions(change):
    with pytest.raises(IncompatibleConfig):
        EmbeddingService(config=replace(DEFAULT_CONFIG, **change))


@pytest.mark.parametrize("change", [{"content": " "}, {"source_id": True}, {"source_type": "ticket"},
    {"source_reference": "/outro"}, {"preparation_version": "ing-01-v0"}])
def test_invalid_prepared_metadata_does_not_reach_encoder(change):
    spy = ModelSpy()
    item = {**chunk(), **change}
    with pytest.raises(ValueError):
        EmbeddingService(model=spy).encode_chunks([item])
    assert spy.calls == []


def test_empty_corpus_is_valid_without_loading_but_absent_corpus_is_unavailable():
    factory = Mock()
    service = CorpusService(EmbeddingService(model_factory=factory))
    with pytest.raises(CorpusUnavailable):
        service.search("pergunta")
    empty = service.prepare_chunks([])
    assert empty.vectors.shape == (0, 384) and empty.metadata.chunk_ids == ()
    assert service.search("pergunta") == []
    factory.assert_not_called()


def test_prepare_and_two_normal_search_calls_encode_documents_only_once():
    spy = ModelSpy()
    search = CorpusService(EmbeddingService(model=spy))
    source = articles()
    first = buscar_artigos("pergunta FONTE_A", source, service=search)
    corpus = search.corpus
    second = buscar_artigos("pergunta FONTE_B", deepcopy(source), service=search)
    assert search.corpus is corpus
    assert first[0]["id"] == 17 and second[0]["id"] == 29
    assert [texts for texts, _ in spy.calls] == [["FONTE_A", "FONTE_B"], ["pergunta FONTE_A"], ["pergunta FONTE_B"]]
    assert search.encoder.stats == {"model_loads": 1, "document_batches": 1, "document_texts": 2,
                                    "question_batches": 2, "question_texts": 2}
    assert corpus.metadata.chunk_ids == tuple(item["chunk_id"] for item in corpus.chunks)
    assert all(key in first[0] for key in ("id", "title", "content", "score"))


def test_same_title_and_same_id_in_distinct_source_types_remain_aligned():
    search = CorpusService(EmbeddingService(model=ModelSpy()), min_similarity=-1)
    source = articles()[0]
    source["source_reference"] = "/Knowledgebase/Article"
    case = {**source, "source_reference": "/Assistance/Ticket", "content": "<p>FONTE_B</p>"}
    corpus = search.prepare_sources([("article", source), ("case", case)])
    results = buscar_artigos("FONTE_B", corpus, service=search)
    assert results[0]["source_type"] == "case" and results[0]["id"] == 17
    assert results[0]["chunk_id"] == corpus.chunks[1]["chunk_id"]
    assert {item["source_type"] for item in results} == {"article", "case"}


def test_multiple_chunks_keep_source_score_and_full_text_in_original_order():
    search = CorpusService(EmbeddingService(model=ModelSpy()), min_similarity=-1)
    corpus = search.prepare_chunks([chunk(0, "FONTE_A\n"), chunk(1, "FONTE_B\n"), chunk(0, "outra", source_id=29)])
    result = search.search("FONTE_B", corpus=corpus)[0]
    assert result["id"] == 17 and result["content"] == "FONTE_A\nFONTE_B\n"
    assert result["chunk_id"] == chunk(1)["chunk_id"] and result["score"] == pytest.approx(1)


def test_failed_partial_batch_preserves_previous_corpus_and_reusable_vectors():
    spy = ModelSpy()
    search = CorpusService(EmbeddingService(model=spy, batch_size=1))
    previous = search.prepare_articles(articles())
    spy.fail_on = len(spy.calls) + 2
    changed = articles()
    changed[0]["content"] = "<p>novo FONTE_A</p>"
    with pytest.raises(EmbeddingUnavailable):
        buscar_artigos("pergunta", changed, service=search)
    assert search.corpus is previous
    spy.fail_on = None
    before = search.encoder.stats["document_texts"]
    assert buscar_artigos("FONTE_B", articles(), service=search)[0]["id"] == 29
    assert search.encoder.stats["document_texts"] == before


def test_invalid_source_or_vector_publication_preserves_previous_corpus():
    spy = ModelSpy()
    search = CorpusService(EmbeddingService(model=spy))
    previous = search.prepare_articles(articles())
    with pytest.raises(ValueError):
        search.prepare_sources([("article", {**articles()[0], "source_reference": "/Knowledgebase/Article", "content": "<p></p>"})])
    spy.transform = lambda values: values[:-1]
    with pytest.raises(ValueError):
        search.prepare_chunks([chunk()])
    assert search.corpus is previous


@pytest.mark.parametrize("change", [{"revision": "outra"}, {"model": "outro"}, {"input_format": "passage"}, {"normalize": False}])
def test_incompatible_corpus_config_rejected_without_encoding_question(change):
    spy = ModelSpy()
    search = CorpusService(EmbeddingService(model=spy))
    corpus = search.prepare_chunks([chunk()])
    foreign = replace(corpus, metadata=replace(corpus.metadata, embedding=replace(DEFAULT_CONFIG, **change)))
    before = len(spy.calls)
    with pytest.raises(IncompatibleConfig):
        search.search("pergunta", corpus=foreign)
    assert len(spy.calls) == before


def test_snapshot_is_immutable_and_checks_order_and_duplicates():
    search = CorpusService(EmbeddingService(model=ModelSpy()))
    chunks = [chunk(0), chunk(1, "FONTE_B")]
    corpus = search.prepare_chunks(chunks)
    chunks[0]["title"] = "alterado externamente"
    assert corpus.chunks[0]["title"] != chunks[0]["title"]
    with pytest.raises(TypeError):
        corpus.chunks[0]["title"] = "alterar"
    with pytest.raises(ValueError):
        corpus.vectors.setflags(write=True)
    with pytest.raises(ValueError):
        replace(corpus, metadata=replace(corpus.metadata, chunk_ids=tuple(reversed(corpus.metadata.chunk_ids))))
    with pytest.raises(ValueError):
        search.prepare_chunks([chunk(), chunk()])


def test_canonical_title_takes_precedence_and_changed_source_rebuilds_explicitly():
    spy = ModelSpy()
    search = CorpusService(EmbeddingService(model=spy))
    source = [{**articles()[0], "title": "Canônico", "name": "Legado"}]
    assert buscar_artigos("pergunta", source, service=search)[0]["title"] == "Canônico"
    before = search.encoder.stats["document_texts"]
    source[0]["content"] = "<p>texto modificado</p>"
    buscar_artigos("pergunta", source, service=search)
    assert search.encoder.stats["document_texts"] == before + 1


@pytest.mark.parametrize("question,limit", [("", 3), ("   ", 3), (None, 3), ("pergunta", 0), ("pergunta", -1)])
def test_legacy_noop_inputs_neither_prepare_nor_load(question, limit):
    service = Mock()
    assert buscar_artigos(question, object(), limit, service=service) == []
    assert service.mock_calls == []


def test_legacy_none_and_empty_articles_are_valid_empty_corpus():
    factory = Mock()
    search = CorpusService(EmbeddingService(model_factory=factory))
    assert buscar_artigos("pergunta", None, service=search) == []
    assert buscar_artigos("pergunta", [], service=search) == []
    factory.assert_not_called()


@pytest.mark.parametrize("change", [{"max_tokens": 128.0}, {"dimension": 384.0}, {"normalize": 1}])
def test_config_types_are_not_accepted_by_numeric_equality(change):
    with pytest.raises(ValueError):
        replace(DEFAULT_CONFIG, **change)


def test_load_failure_is_explicit_and_retry_does_not_cache_a_broken_model():
    factory = Mock(side_effect=[OSError("Falha sintética de carga"), ModelSpy()])
    service = EmbeddingService(model_factory=factory)
    with pytest.raises(EmbeddingUnavailable):
        service.load()
    service.encode_question("pergunta")
    assert factory.call_count == 2 and service.stats["model_loads"] == 1


def test_chunk_identity_must_match_source_and_preparation_version():
    with pytest.raises(ValueError, match="chunk_id"):
        EmbeddingService(model=ModelSpy()).encode_chunks([{**chunk(), "source_id": 29}])
