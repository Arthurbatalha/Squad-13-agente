"""Apoio dos testes RAG-01: índice publicado real, SQLite real e provedor fake.

Nada aqui importa SentenceTransformers, Gemini ou GLPI. O encoder é o espião
determinístico da ING-02 e o diretório de personagens é uma coleção fictícia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from pathlib import Path
from threading import Event
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from src.agent_core import build_graph
from src.api.real_backend import DISABLED_TOOLS, RealChatBackend
from src.authorization.service import AuthorizationService
from src.glpi_integration.GLPI_Client import GLPICollection
from src.model.gemini_adapter import GenerationResult
from src.rag.corpus import CorpusService
from src.rag.embeddings import EmbeddingService
from src.rag.local_index import LocalIndexStore
from src.rag.retrieval import build_published_retrieval
from src.session_store import init_db
from src.sessions import SessionService
from test.embedding_fakes import ModelSpy, unit


WINDOWS_ARTICLE = {
    "id": 12,
    "title": "Configurar a VPN no Windows",
    "content": (
        "<p>Como configurar a VPN no Windows?</p>"
        "<p>Abra o cliente de VPN do Windows e informe o servidor corporativo.</p>"
    ),
    "source_reference": "/Knowledgebase/Article",
}
MACOS_ARTICLE = {
    "id": 20,
    "title": "Configurar a VPN no macOS",
    "content": (
        "<p>Como configurar a VPN no macOS?</p>"
        "<p>Abra Ajustes de Rede do macOS e adicione a configuração de VPN.</p>"
    ),
    "source_reference": "/Knowledgebase/Article",
}

TECHNICIANS = [
    {"id": 42, "username": "ana.ribeiro"},
    {"id": 87, "username": "bruno.tavares"},
]


class DirectorySpy:
    """Diretório fictício; conta chamadas para provar que mensagens não o usam."""

    def __init__(self, rows=None):
        self.rows = list(rows or TECHNICIANS)
        self.calls = 0

    def __call__(self) -> GLPICollection:
        self.calls += 1
        rows = [dict(row) for row in self.rows]
        return GLPICollection(
            "/Administration/User", rows, total=len(rows), pages=1
        )


@dataclass(frozen=True)
class AdapterCall:
    question: str
    evidence: tuple[dict[str, Any], ...]
    history: tuple[dict[str, str], ...]


@dataclass
class CiteAdapter:
    """Cita o primeiro trecho recebido e registra exatamente o que viu."""

    text: str | None = None
    error: Exception | None = None
    chunk_id: str | None = None
    calls: list[AdapterCall] = field(default_factory=list)

    def generate(self, question, evidence, history) -> GenerationResult:
        evidence = tuple(dict(item) for item in evidence)
        self.calls.append(AdapterCall(question, evidence, tuple(history)))
        if self.error is not None:
            raise self.error
        if not evidence:
            raise AssertionError("O modelo não pode ser chamado sem evidência.")
        chunk_id = self.chunk_id or evidence[0]["chunk_id"]
        text = self.text or f"Consulte o procedimento [{chunk_id}]."
        return GenerationResult(
            text, "fake-gemini", 10, prompt_evidence=evidence
        )


class BlockingAdapter(CiteAdapter):
    """Segura a geração até o teste liberar, simulando resposta atrasada."""

    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def generate(self, question, evidence, history):
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise AssertionError("O teste não liberou a geração bloqueada.")
        return super().generate(question, evidence, history)


@dataclass
class Harness:
    root: Path
    db: Path
    encoder: EmbeddingService
    authorization: AuthorizationService
    retriever: Any
    directory: DirectorySpy
    sessions: SessionService
    adapter: Any
    graph: Any
    backend: RealChatBackend
    conn: sqlite3.Connection

    def close(self) -> None:
        self.conn.close()

    def start(self, character_id: int = 42):
        return self.backend.create_session_credential(character_id)


def build_encoder() -> EmbeddingService:
    def vector_for(text: str):
        if "macOS" in text:
            return unit(1)
        if "Windows" in text or "VPN" in text:
            return unit(0)
        return unit(2)

    return EmbeddingService(model=ModelSpy(vector_for))


def build_index(root: Path, encoder: EmbeddingService) -> None:
    store = LocalIndexStore(root / "index", "article", embedding=encoder.config)
    corpus = CorpusService(encoder).prepare_sources([
        ("article", WINDOWS_ARTICLE),
        ("article", MACOS_ARTICLE),
    ])
    generation = store.create_candidate(corpus).generation_id
    store.activate(generation)


def make_harness(
    tmp_path: Path,
    *,
    adapter: Any | None = None,
    authorization: AuthorizationService | None = None,
    with_index: bool = True,
    max_history_messages: int = 20,
    recursion_limit: int = 8,
) -> Harness:
    root = Path(tmp_path)
    db = root / "state.sqlite3"
    init_db(db)
    encoder = build_encoder()
    if with_index:
        build_index(root, encoder)

    authorization = authorization or AuthorizationService(
        None, disabled_tools=DISABLED_TOOLS
    )
    retriever = build_published_retrieval(
        authorization, encoder=encoder, index_dir=root / "index"
    )
    directory = DirectorySpy()
    sessions = SessionService(directory, integration_username="glpi")
    adapter = adapter or CiteAdapter()

    conn = sqlite3.connect(db, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    graph = build_graph(
        saver,
        model_adapter=adapter,
        max_history_messages=max_history_messages,
        recursion_limit=recursion_limit,
    )
    backend = RealChatBackend(
        graph=graph,
        state_file=db,
        session_service=sessions,
        encoder=encoder,
        authorization=authorization,
        retriever=retriever,
    )
    return Harness(
        root=root,
        db=db,
        encoder=encoder,
        authorization=authorization,
        retriever=retriever,
        directory=directory,
        sessions=sessions,
        adapter=adapter,
        graph=graph,
        backend=backend,
        conn=conn,
    )
