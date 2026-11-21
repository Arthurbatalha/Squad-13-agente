"""RAG-03: fixtures sintéticas, encoder espião e LocalIndexStore real em tmp."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from threading import Event

import numpy as np
import pytest
import requests

from src.authorization.policies import Principal, ToolDenied
from src.authorization.service import AuthorizationService
from src.glpi_integration.GLPI_Client import GLPICollection
from src.rag.busca_artigos import recuperar_trechos
from src.rag.chunk_contract import PREPARATION_VERSION
from src.rag.corpus import CorpusMetadata, PreparedCorpus
from src.rag.embeddings import DEFAULT_CONFIG, EmbeddingService, TokenLimitError
from src.rag.local_index import LocalIndexStore
from src.rag.manifest import empty_manifest, save_manifest_atomic
from src.rag.retrieval import PublishedRetrieval, RetrievalConfig, build_published_retrieval, render_context
from src.rag.sync_runtime import ArticleSyncReport, SyncRunLedger
from test.embedding_fakes import ModelSpy, chunk, unit

STAFF = Principal.staff(13)


class CaseGLPI:
    """Metadados estruturais simulados; proíbe coleta completa dos artigos/casos."""

    def __init__(self, tickets=()):
        self.tickets = {t["id"]: t for t in tickets}
        self.reads = []

    def get_by_id(self, path, source_id):
        self.reads.append(source_id)
        if source_id not in self.tickets:
            raise requests.ConnectionError("Falha simulada na checagem de ACL.")
        return self.tickets[source_id]

    def search_all(self, path):
        assert path.endswith("/Timeline"), "Recuperação não deve coletar todo o corpus."
        return GLPICollection(path, [{"type": "Solution", "item": {"content": "Solução pública fixture"}}],
                              total=1, pages=1)


def ticket(source_id, *, requester=13, **overrides):
    return {"id": source_id, "name": "Caso fixture", "content": "Problema fixture",
            "is_deleted": False, "date_solve": "2026-01-01",
            "team": [{"type": "User", "role": "requester", "id": requester}], **overrides}


def publish(root, kind, chunks, vectors=None, config=DEFAULT_CONFIG):
    vectors = (np.stack([unit() for _ in chunks]) if chunks else np.empty((0, 384))) \
        if vectors is None else vectors
    corpus = PreparedCorpus(tuple(chunks), vectors,
                            CorpusMetadata(config, PREPARATION_VERSION, tuple(c["chunk_id"] for c in chunks)))
    store = LocalIndexStore(root, kind, embedding=config)
    generation = store.create_candidate(corpus)
    store.activate(generation.generation_id)
    return store, generation


def service(stores, *, glpi=None, disabled=(), config=None, scope_resolver=None, model=None, **kwargs):
    model = model or ModelSpy()
    encoder = EmbeddingService(model=model)
    retrieval = PublishedRetrieval(stores, authorization=AuthorizationService(glpi, disabled_tools=disabled),
                                   encoder=encoder, config=config or RetrievalConfig(),
                                   scope_resolver=scope_resolver, **kwargs)
    return retrieval, encoder, model


def test_combines_collections_reopened_ids_and_only_one_question_embedding(tmp_path, monkeypatch):
    article, article_gen = publish(tmp_path, "article", [chunk(content="Artigo fixture", source_id=7)])
    case, case_gen = publish(tmp_path, "case", [chunk(content="Caso fixture", source_type="case", source_id=7)])
    # Novas instâncias: metadados e vetores vêm efetivamente do disco.
    stores = {k: LocalIndexStore(tmp_path, k) for k in ("article", "case")}
    retrieval, encoder, model = service(stores, glpi=CaseGLPI([ticket(7)]))
    monkeypatch.setattr(EmbeddingService, "encode_chunks", lambda *_: pytest.fail("Documentos vetorizados na leitura"))
    monkeypatch.setattr(EmbeddingService, "prepare_source", lambda *_a, **_k: pytest.fail("Preparação durante leitura"))
    opened = Counter()
    for kind, store in stores.items():
        original = store.open_active

        def open_once(kind=kind, original=original):
            opened[kind] += 1
            return original()

        monkeypatch.setattr(store, "open_active", open_once)
    result = recuperar_trechos("Dúvida fixture", STAFF, retriever=retrieval)
    assert result["status"] == "evidence"
    assert {(c["source_type"], c["source_id"]) for c in result["chunks"]} == {("article", 7), ("case", 7)}
    assert result["collections"]["article"]["generation"] == article_gen.generation_id
    assert result["collections"]["case"]["generation"] == case_gen.generation_id
    assert opened == {"article": 1, "case": 1}
    assert encoder.stats["question_texts"] == 1 and encoder.stats["document_texts"] == 0
    assert [call[0] for call in model.calls] == [["Dúvida fixture"]]
    for hit in result["chunks"]:
        assert hit["metric"] == "cosine_similarity" and hit["score"] == pytest.approx(1)
        assert hit["source_id"] == int(hit["chunk_id"].split(":")[2])
        assert hit["source_modified_at"] is None
    assert result["trust"] == "untrusted_data" and result["higher_is_more_similar"] is True
    assert result["context_tokens"] == encoder.token_count(result["context"])


def test_authorizes_before_top_k_even_when_forbidden_sources_have_best_scores(tmp_path):
    chunks = [chunk(content=f"Fonte {i}", source_type="case", source_id=i) for i in range(1, 12)]
    scores = [unit() for _ in range(10)] + [(unit() + unit(1)) / np.sqrt(2)]
    store, _ = publish(tmp_path, "case", chunks, np.stack(scores))
    glpi = CaseGLPI([ticket(i, requester=99 if i < 11 else 13) for i in range(1, 12)])
    retrieval, _, _ = service({"case": store}, glpi=glpi, config=RetrievalConfig(candidates_per_collection=1))
    result = retrieval.retrieve("Dúvida", Principal.client(13))
    assert [h["source_id"] for h in result["chunks"]] == [11]
    assert set(glpi.reads) == set(range(1, 12))


@pytest.mark.parametrize("scope", [[], None, [True], ["7"]])
def test_empty_unknown_or_invalid_source_scope_does_not_open_or_encode(tmp_path, monkeypatch, scope):
    store, _ = publish(tmp_path, "article", [chunk()])
    monkeypatch.setattr(store, "open_active", lambda: pytest.fail("Coleção sem escopo foi aberta"))
    retrieval, encoder, _ = service({"article": store}, scope_resolver=lambda _p, _k: scope)
    assert retrieval.retrieve("Dúvida", STAFF)["chunks"] == []
    assert encoder.stats["model_loads"] == 0


def test_scope_is_intersected_with_current_acl_and_recomputed_for_each_principal(tmp_path):
    store, _ = publish(tmp_path, "case", [chunk(source_type="case", source_id=7)])
    glpi = CaseGLPI([ticket(7, requester=13)])
    retrieval, encoder, _ = service({"case": store}, glpi=glpi, scope_resolver=lambda p, k: [7])
    assert retrieval.retrieve("Dúvida", Principal.client(13))["chunks"]
    assert retrieval.retrieve("Dúvida", Principal.client(14))["chunks"] == []
    glpi.tickets[7]["is_deleted"] = True
    assert retrieval.retrieve("Dúvida", STAFF)["chunks"] == []
    assert encoder.stats["question_texts"] == 1


@pytest.mark.parametrize("overrides", [{"is_deleted": None}, {"team": None}, {"date_solve": None}])
def test_unknown_case_authorization_is_closed(tmp_path, overrides):
    store, _ = publish(tmp_path, "case", [chunk(source_type="case", source_id=7)])
    retrieval, encoder, _ = service({"case": store}, glpi=CaseGLPI([ticket(7, **overrides)]))
    assert retrieval.retrieve("Dúvida", STAFF)["chunks"] == []
    assert encoder.stats["question_texts"] == 0


def test_case_acl_network_failure_denies_source(tmp_path):
    store, _ = publish(tmp_path, "case", [chunk(source_type="case", source_id=7)])
    retrieval, encoder, _ = service({"case": store}, glpi=CaseGLPI())
    assert retrieval.retrieve("Dúvida", STAFF)["chunks"] == []
    assert encoder.stats["question_texts"] == 0


def test_disabled_tool_and_forged_principal(tmp_path, monkeypatch):
    store, _ = publish(tmp_path, "article", [chunk()])
    monkeypatch.setattr(store, "open_active", lambda: pytest.fail("Ferramenta desabilitada abriu índice"))
    retrieval, encoder, _ = service({"article": store}, disabled={"search_articles"})
    assert retrieval.retrieve("Dúvida", STAFF)["collections"] == {"article": {"state": "not_authorized"}}
    with pytest.raises(ToolDenied):
        retrieval.retrieve("Dúvida", {"role": "staff", "user_id": 13})
    assert encoder.stats["model_loads"] == 0


def test_deduplicates_text_and_deterministic_ties_global_and_source_limits(tmp_path):
    chunks = [chunk(i, f"Fonte {source_id}, passo distinto {i}", source_id=source_id)
              for source_id in range(1, 7) for i in range(3)]
    chunks.insert(1, chunk(99, chunks[0]["content"], source_id=1))
    store, _ = publish(tmp_path, "article", list(reversed(chunks)))
    retrieval, encoder, _ = service({"article": store}, config=RetrievalConfig(context_max_tokens=1000))
    first = retrieval.retrieve("Dúvida", STAFF)
    second = retrieval.retrieve("Outra dúvida", STAFF)
    assert [h["chunk_id"] for h in first["chunks"]] == [h["chunk_id"] for h in second["chunks"]]
    assert len(first["chunks"]) == 4
    assert max(Counter((h["source_type"], h["source_id"]) for h in first["chunks"]).values()) == 2
    assert len({h["content"] for h in first["chunks"]}) == 4
    assert encoder.stats["question_texts"] == 2 and encoder.stats["document_texts"] == 0


def test_candidates_per_collection_is_respected(tmp_path):
    store, _ = publish(tmp_path, "article", [chunk(content=f"Fonte {i}", source_id=i) for i in range(12)])
    retrieval, _, _ = service({"article": store}, config=RetrievalConfig(candidates_per_collection=2))
    assert len(retrieval.retrieve("Dúvida", STAFF)["chunks"]) == 2


def test_complementary_step_same_source_can_have_lower_score(tmp_path):
    chunks = [chunk(0, "Problema VPN fixture: consulte o passo 2 para continuar.", source_id=7),
              chunk(1, "Passo 2: reinicie o cliente VPN-FIX-691.", source_id=7),
              chunk(0, "Passo 2: instrução de outra fonte.", source_id=8)]
    # Referência a passo 2 no corpo não substitui a instrução do passo 2.
    vectors = np.stack([unit(), unit(1), unit(2)])
    store, _ = publish(tmp_path, "article", chunks, vectors)
    retrieval, encoder, _ = service({"article": store})
    result = retrieval.retrieve("Preciso do passo 2 da VPN fixture", STAFF)
    assert [h["chunk_id"] for h in result["chunks"]] == [c["chunk_id"] for c in chunks[:2]]
    assert result["chunks"][1]["score"] == 0  # suporte complementar, não âncora de ranking
    assert result["chunks"][1]["selection_reason"] == "same_source_support"
    assert result["context_tokens"] <= retrieval.config.context_max_tokens
    assert result["context_tokens"] == encoder.token_count(render_context(result["chunks"]))


@pytest.mark.parametrize("constraint", ["budget", "source_limit", "global_limit", "candidate_limit", "acl"])
def test_missing_complement_returns_insufficient_evidence_with_no_partial_context(tmp_path, constraint):
    chunks = [chunk(0, "Problema VPN fixture.", source_id=7),
              chunk(1, "Solução: reinicie o cliente VPN-FIX-691.", source_id=7)]
    store, _ = publish(tmp_path, "article", chunks, np.stack([unit(), unit(1)]))
    config = RetrievalConfig()
    if constraint == "budget":
        encoder = EmbeddingService(model=ModelSpy())
        one = encoder.token_count(render_context([chunks[0]]))
        config = replace(config, context_max_tokens=one)
    elif constraint == "source_limit":
        config = replace(config, max_chunks_per_source=1)
    elif constraint == "global_limit":
        config = replace(config, max_chunks=1)
    elif constraint == "candidate_limit":
        config = replace(config, candidates_per_collection=1)
    elif constraint == "acl":
        # O complemento de outra fonte não pode completar a fonte autorizada.
        chunks[1] = chunk(0, chunks[1]["content"], source_id=8)
        store, _ = publish(tmp_path, "article", chunks, np.stack([unit(), unit(1)]))
    retrieval, _, _ = service({"article": store}, config=config,
                               scope_resolver=(lambda p, k: [7]) if constraint == "acl" else None)
    result = retrieval.retrieve("Como resolver a VPN fixture?", STAFF)
    assert result["status"] == "no_evidence" and result["reason"] == "insufficient_evidence"
    assert result["chunks"] == [] and result["context"] == "" and result["context_tokens"] == 0


def test_explicit_evidence_requirement_and_exact_budget_boundary(tmp_path):
    chunks = [chunk(0, "Problema VPN fixture.", source_id=7),
              chunk(1, "Solução: reinicie o cliente VPN-FIX-691.", source_id=7)]
    store, _ = publish(tmp_path, "article", chunks, np.stack([unit(), unit(1)]))
    encoder = EmbeddingService(model=ModelSpy())
    budget = encoder.token_count(render_context(chunks))
    retrieval, _, _ = service({"article": store}, config=RetrievalConfig(context_max_tokens=budget))
    result = retrieval.retrieve("Dúvida da VPN", STAFF, required_evidence=["VPN-FIX-691"])
    assert result["status"] == "evidence" and len(result["chunks"]) == 2
    assert result["context_tokens"] == budget


@pytest.mark.parametrize("different_code", ["VPN-FIX-6910", "XVPN-FIX-691", "VPN-FIX-691-A", "ERR-VPN-FIX-691"])
def test_required_error_code_does_not_match_a_different_code(tmp_path, different_code):
    store, _ = publish(tmp_path, "article", [chunk(content=f"Confira o erro {different_code}.")])
    retrieval, _, _ = service({"article": store})
    result = retrieval.retrieve("Dúvida sobre a VPN", STAFF, required_evidence=["VPN-FIX-691"])
    assert result["status"] == "no_evidence"
    assert result["reason"] == "insufficient_evidence" and result["chunks"] == []


@pytest.mark.parametrize("label,question", [
    ("**Solução:**", "Como resolver a VPN?"),
    ("**Solução**:", "Como resolver a VPN?"),
    ("__Solução:__", "Como resolver a VPN?"),
    ("Solução: ***", "Como resolver a VPN?"),
    ("**Passo 2:**", "Qual é o passo 2 da VPN?"),
    ("**Passo 2**:", "Qual é o passo 2 da VPN?"),
    ("__Passo 2:__", "Qual é o passo 2 da VPN?"),
    ("2. **", "Qual é o passo 2 da VPN?"),
])
@pytest.mark.parametrize("has_instruction", [False, True])
def test_markdown_label_alone_is_not_an_instruction(tmp_path, label, question, has_instruction):
    chunks = [chunk(0, f"Problema VPN fixture.\n{label}")]
    if has_instruction:
        chunks.append(chunk(1, "Reinicie o aplicativo VPN fixture."))
    vectors = np.stack([unit(i) for i in range(len(chunks))])
    store, _ = publish(tmp_path, "article", chunks, vectors)
    retrieval, _, _ = service({"article": store})
    result = retrieval.retrieve(question, STAFF)
    if has_instruction:
        assert result["status"] == "evidence" and len(result["chunks"]) == 2
        assert result["chunks"][1]["selection_reason"] == "same_source_support"
    else:
        assert result["status"] == "no_evidence" and result["chunks"] == []


def test_publication_during_query_does_not_mix_generations(tmp_path, monkeypatch):
    old_chunks = [chunk(0, "Primeiro texto antigo", source_id=7), chunk(1, "Segundo texto antigo", source_id=7)]
    store, old = publish(tmp_path, "article", old_chunks)
    entered, proceed = Event(), Event()
    model = ModelSpy()
    original_encode = model.encode

    def blocked_encode(*args, **kwargs):
        entered.set()
        assert proceed.wait(10)
        return original_encode(*args, **kwargs)

    monkeypatch.setattr(model, "encode", blocked_encode)
    retrieval, _, _ = service({"article": store}, model=model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(retrieval.retrieve, "Dúvida", STAFF)
        try:
            assert entered.wait(10)
            _, new = publish(tmp_path, "article", [chunk(0, "Novo texto", source_id=99)])
            assert store.active_generation_id() == new.generation_id
            assert old.generation_id not in store.cleanup(keep_previous=0)
        finally:
            proceed.set()
        result = future.result(timeout=10)
    assert result["collections"]["article"]["generation"] == old.generation_id
    assert {h["source_id"] for h in result["chunks"]} == {7}
    assert {h["generation"] for h in result["chunks"]} == {old.generation_id}
    assert [h["content"] for h in result["chunks"]] == [c["content"] for c in old_chunks]


def test_valid_empty_unavailable_and_stale_generation_are_distinct(tmp_path):
    store = LocalIndexStore(tmp_path, "article")
    retrieval, encoder, _ = service({"article": store})
    assert retrieval.retrieve("Dúvida", STAFF)["status"] == "index_unavailable"
    store, info = publish(tmp_path, "article", [])
    empty, _, _ = service({"article": store})
    result = empty.retrieve("Dúvida", STAFF)
    assert result["status"] == "no_evidence" and result["collections"]["article"]["generation"] == info.generation_id
    store, info = publish(tmp_path, "article", [chunk()])
    ledger = SyncRunLedger(tmp_path / "runs.sqlite3")
    run = ledger.begin("manual", "2026-01-01T00:00:00Z", asdict(DEFAULT_CONFIG))
    ledger.finish(run, ArticleSyncReport(
        status="published", active_generation=info.generation_id, previous_generation=None,
        checked_at="2026-01-01T00:00:01Z", published_at="2026-01-01T00:00:01Z",
        index_config=asdict(DEFAULT_CONFIG), sources_total=1, chunks_total=1),
        finished_at="2026-01-01T00:00:02Z", duration_seconds=2, source_api_status="available")
    failed = ledger.begin("manual", "2026-01-02T00:00:00Z", asdict(DEFAULT_CONFIG))
    ledger.fail(failed, finished_at="2026-01-02T00:00:01Z", duration_seconds=1,
                error_code="ConnectionError", source_api_status="unavailable")
    stale, _, _ = service({"article": store}, sync_ledgers={"article": ledger.path})
    result = stale.retrieve("Dúvida", STAFF)
    assert result["status"] == "evidence"
    assert result["collections"]["article"]["state"] == "stale"
    assert result["collections"]["article"]["update"]["state"] == "failed"
    assert result["collections"]["article"]["update"]["last_checked_at"] == "2026-01-01T00:00:01Z"
    assert result["collections"]["article"]["generation_created_at"] == info.created_at
    assert result["chunks"][0]["source_modified_at"] is None
    assert encoder.stats["model_loads"] == 0


def test_threshold_provisional_and_incompatible_config(tmp_path):
    store, _ = publish(tmp_path, "article", [chunk()], np.stack([unit(1)]))
    retrieval, _, _ = service({"article": store})
    result = retrieval.retrieve("Dúvida", STAFF)
    assert result["status"] == "no_evidence" and result["threshold_provisional"] is True
    foreign = LocalIndexStore(tmp_path, "article", embedding=replace(DEFAULT_CONFIG, revision="a" * 40))
    retrieval, encoder, _ = service({"article": foreign})
    assert retrieval.retrieve("Dúvida", STAFF)["status"] == "index_unavailable"
    assert encoder.stats["question_texts"] == 0


@pytest.mark.parametrize("field", ["max_chunks", "max_chunks_per_source", "candidates_per_collection", "context_max_tokens"])
def test_zero_limits_produce_no_context_without_inference(tmp_path, field):
    store, _ = publish(tmp_path, "article", [chunk()])
    retrieval, encoder, _ = service({"article": store}, config=replace(RetrievalConfig(), **{field: 0}))
    assert retrieval.retrieve("Dúvida", STAFF)["chunks"] == []
    assert encoder.stats["question_texts"] == 0


def test_factory_and_reading_missing_ledger_do_not_create_files(tmp_path):
    encoder = EmbeddingService(model=ModelSpy())
    retrieval = build_published_retrieval(AuthorizationService(None), encoder=encoder, index_dir=tmp_path / "index")
    assert list(tmp_path.iterdir()) == []
    assert retrieval.retrieve("Dúvida", STAFF)["chunks"] == []
    assert list(tmp_path.iterdir()) == []
    assert encoder.stats["model_loads"] == 0


def test_question_limit_is_checked_before_inference(tmp_path):
    store, _ = publish(tmp_path, "article", [chunk()])
    retrieval, encoder, model = service({"article": store})
    with pytest.raises(TokenLimitError):
        retrieval.retrieve("palavra " * 128, STAFF)
    assert model.calls == [] and encoder.stats["question_texts"] == 0


def test_combined_collections_respect_global_limits_and_type_identity(tmp_path):
    stores = {}
    for kind in ("article", "case"):
        chunks = [chunk(i, f"Fonte {kind} {source_id} trecho {i}", source_type=kind, source_id=source_id)
                  for source_id in range(1, 4) for i in range(3)]
        stores[kind], _ = publish(tmp_path, kind, chunks)
    retrieval, _, _ = service(stores, glpi=CaseGLPI([ticket(i) for i in range(1, 4)]),
                               config=RetrievalConfig(context_max_tokens=1000))
    result = retrieval.retrieve("Dúvida", STAFF)
    assert len(result["chunks"]) == 4
    assert all(v <= 2 for v in Counter((h["source_type"], h["source_id"]) for h in result["chunks"]).values())


@pytest.mark.parametrize("reverse_scores", [False, True])
def test_solution_heading_needs_actual_instruction(tmp_path, reverse_scores):
    store, _ = publish(tmp_path, "article", [chunk(0, "Problema fixture.\n# Solução"),
                                           chunk(1, "Reinicie o aplicativo fixture.")],
                       np.stack([unit(1), unit()] if reverse_scores else [unit(), unit(1)]))
    retrieval, _, _ = service({"article": store})
    result = retrieval.retrieve("Como resolver?", STAFF)
    assert len(result["chunks"]) == 2
    assert [h["content"] for h in result["chunks"]] == ["Problema fixture.\n# Solução", "Reinicie o aplicativo fixture."]


def test_sync_manifest_dates_are_used_only_for_pinned_generation(tmp_path):
    store, old = publish(tmp_path, "article", [chunk()])
    manifest = {**empty_manifest(), "active_generation": old.generation_id,
                "source_type": "article", "last_checked_at": "2026-01-01T00:00:00Z",
                "last_published_at": "2026-01-01T00:00:00Z"}
    save_manifest_atomic(store.directory / "sync_manifest.json", manifest)
    retrieval, _, _ = service({"article": store})
    result = retrieval.retrieve("Dúvida", STAFF)
    assert result["collections"]["article"]["update"]["last_checked_at"] == manifest["last_checked_at"]
    # Uma observação de outra geração não serve de data para a capturada.
    manifest["active_generation"] = "outra-geracao"
    save_manifest_atomic(store.directory / "sync_manifest.json", manifest)
    result = retrieval.retrieve("Dúvida", STAFF)
    assert result["collections"]["article"]["update"]["last_checked_at"] is None


def test_corrupt_collection_does_not_hide_failure_as_no_evidence(tmp_path):
    store, info = publish(tmp_path, "article", [chunk()])
    (store.directory / f"gen-{info.generation_id}" / "vectors.npy").write_bytes(b"corrupt fixture")
    retrieval, encoder, _ = service({"article": store})
    result = retrieval.retrieve("Dúvida", STAFF)
    assert result["status"] == "index_unavailable"
    assert result["collections"]["article"]["error"] == "IndexCorrupt"
    assert result["chunks"] == [] and encoder.stats["question_texts"] == 0


def test_partial_availability_is_explicit(tmp_path):
    article, _ = publish(tmp_path, "article", [chunk(source_id=7)])
    case, info = publish(tmp_path, "case", [chunk(source_type="case", source_id=7)])
    (case.directory / f"gen-{info.generation_id}" / "catalog.json").write_bytes(b"corrupt fixture")
    retrieval, encoder, _ = service({"article": article, "case": case}, glpi=CaseGLPI([ticket(7)]))
    result = retrieval.retrieve("Dúvida", STAFF)
    assert result["status"] == "evidence" and result["incomplete"] is True
    assert result["collections"]["case"]["state"] == "unavailable"
    assert {h["source_type"] for h in result["chunks"]} == {"article"}
    assert encoder.stats["question_texts"] == 1


@pytest.mark.parametrize("question", [None, "", "   ", 13])
def test_invalid_question_is_explicit(tmp_path, question):
    retrieval, _, _ = service({})
    with pytest.raises(ValueError):
        retrieval.retrieve(question, STAFF)
