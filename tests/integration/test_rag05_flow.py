"""Duas jornadas VPN com artigos sintéticos, índice publicado e gerador controlado."""

import os

from src.authorization.policies import Principal
from src.authorization.service import AuthorizationService
from src.model.gemini_adapter import GeminiAdapter
from src.rag.corpus import CorpusService
from src.rag.embeddings import EmbeddingService
from src.rag.evidence_policy import respond
from src.rag.local_index import LocalIndexStore
from src.rag.retrieval import build_published_retrieval
from test.embedding_fakes import ModelSpy, unit


class CiteFirstChunk:
    """Cita o primeiro trecho recebido, permitindo observar o ranking pela saída."""

    def invoke(self, messages):
        prompt = messages if isinstance(messages, str) else messages[-1].content
        chunk_id = next(line.removeprefix("chunk_id: ") for line in prompt.splitlines()
                        if line.startswith("chunk_id: "))
        return f"Consulte o procedimento [{chunk_id}]."


def test_clarification_to_published_source(tmp_path):
    if os.environ.get("RAG05_TEST_REAL_MINILM") == "1":
        encoder = EmbeddingService(local_files_only=True)
    else:
        encoder = EmbeddingService(model=ModelSpy(lambda text: unit(int("macOS" in text))))
    systems = {12: "Windows", 20: "macOS"}
    sources = [
        ("article", {"id": source_id, "title": f"VPN no {system} (fixture)",
                     "content": f"<p>Como configurar a VPN no {system}?</p>"
                                f"<p>Abra o cliente de VPN do {system}.</p>",
                     "source_reference": "/Knowledgebase/Article"})
        for source_id, system in systems.items()
    ]
    store = LocalIndexStore(tmp_path, "article", embedding=encoder.config)
    corpus = CorpusService(encoder).prepare_sources(sources)
    generation = store.create_candidate(corpus).generation_id
    store.activate(generation)
    reader = build_published_retrieval(AuthorizationService(None), encoder=encoder, index_dir=tmp_path)
    principal = Principal.staff(13)
    queries = []

    def retrieve(question):
        queries.append(question)
        result = reader.retrieve(question, principal)
        assert result["collections"]["article"]["generation"] == generation
        return result

    generate = GeminiAdapter(CiteFirstChunk()).generate
    question = "Como configuro a VPN?"
    before = encoder.stats
    first = respond(question, retrieve=retrieve, generate=generate)
    assert first.kind == "clarification" and queries == []
    history = [("user", question), ("assistant", first.reply.question)]
    for source_id, system in systems.items():
        result = respond(system, history=history, retrieve=retrieve, generate=generate)
        assert result.kind == "answered" and result.validation.ok
        source, = result.reply.sources
        assert source.chunk_id == f"ing-01-v2:article:{source_id}:0000"
        assert source.reference == "/Knowledgebase/Article"
    assert queries == [f"{question} {system}" for system in systems.values()]
    assert encoder.stats["document_texts"] == before["document_texts"]
    assert encoder.stats["question_texts"] == before["question_texts"] + 2
