"""RAG-01: retomada real com SQLite temporário e cookie HttpOnly.

Cada aplicação abre sua própria conexão/checkpointer no mesmo arquivo. Um novo
processo (simulado por uma nova instância) precisa reconstruir a sessão a partir
do token e continuar o esclarecimento anterior sem depender da memória antiga.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agent_core import build_graph
from src.api.app import create_app
from src.api.real_backend import DISABLED_TOOLS, SESSION_COOKIE, RealChatBackend
from src.authorization.service import AuthorizationService
from src.model.gemini_adapter import ModelTimeout
from src.rag.retrieval import build_published_retrieval
from src.sessions import SessionService
from tests.rag01_fixtures import (
    CiteAdapter,
    DirectorySpy,
    build_encoder,
    build_index,
)


class AppFactory:
    def __init__(self, root: Path):
        self.root = root
        self.db = root / "state.sqlite3"
        self.encoder = build_encoder()
        build_index(root, self.encoder)
        self.authorization = AuthorizationService(
            None, disabled_tools=DISABLED_TOOLS
        )
        self.retriever = build_published_retrieval(
            self.authorization,
            encoder=self.encoder,
            index_dir=root / "index",
        )
        self.adapters: list[CiteAdapter] = []
        self.next_error: Exception | None = None

    def graph(self, checkpointer):
        adapter = CiteAdapter(error=self.next_error)
        self.next_error = None
        self.adapters.append(adapter)
        return build_graph(checkpointer, model_adapter=adapter)

    def backend(self, graph, state_file):
        return RealChatBackend(
            graph=graph,
            state_file=state_file,
            session_service=SessionService(
                DirectorySpy(), integration_username="glpi"
            ),
            encoder=self.encoder,
            authorization=self.authorization,
            retriever=self.retriever,
        )

    def app(self):
        return create_app(
            backend_factory=self.backend,
            graph_factory=self.graph,
            state_file=self.db,
            frontend_dist=None,
        )


@pytest.fixture()
def factory(tmp_path):
    return AppFactory(tmp_path)


def create(client: TestClient, character_id: int = 42):
    response = client.post(
        "/api/sessions", json={"character_id": character_id}
    )
    assert response.status_code == 201, response.text
    return response.json(), client.cookies.get(SESSION_COOKIE)


def say(client: TestClient, thread: str, text: str):
    return client.post(
        f"/api/sessions/{thread}/messages", json={"text": text}
    )


def test_restart_resumes_clarification_and_short_answer(factory):
    app = factory.app()
    with TestClient(app) as client:
        info, token = create(client)
        first = say(client, info["thread_id"], "Como configuro a VPN?")
        assert first.status_code == 200
        assert first.json()["reply"]["type"] == "clarification"
        assert factory.adapters[-1].calls == []

    # Novo processo: outra conexão, outro SessionService, mesmo SQLite.
    app = factory.app()
    with TestClient(app) as client:
        assert client.get(
            f"/api/sessions/{info['thread_id']}"
        ).status_code == 404
        client.cookies.set(SESSION_COOKIE, token)
        assert client.get(
            f"/api/sessions/{info['thread_id']}"
        ).status_code == 200

        second = say(client, info["thread_id"], "Windows")
        assert second.status_code == 200
        reply = second.json()["reply"]
        assert reply["type"] == "text"
        assert reply["answer_status"] == "answered"
        assert reply["sources"][0]["source_id"] == "12"

        call, = factory.adapters[-1].calls
        assert call.question == "Como configuro a VPN? Windows"
        assert call.history[0] == {
            "role": "user",
            "content": "Como configuro a VPN?",
        }
        assert call.history[1]["role"] == "assistant"
        assert "sistema operacional" in call.history[1]["content"]


def test_cookie_is_httponly_and_never_appears_in_the_body(factory):
    app = factory.app()
    with TestClient(app) as client:
        response = client.post(
            "/api/sessions", json={"character_id": 42}
        )
        assert response.status_code == 201
        token = client.cookies.get(SESSION_COOKIE)
        assert token
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=lax" in header
        assert "path=/api" in header
        assert token not in response.text
        assert token not in json.dumps(response.json())


def test_switch_rotates_cookie_and_old_thread_stops_existing(factory):
    app = factory.app()
    with TestClient(app) as client:
        old, old_token = create(client, 42)
        assert say(
            client, old["thread_id"], "Como configuro a VPN?"
        ).status_code == 200

        switched = client.post(
            f"/api/sessions/{old['thread_id']}/switch",
            json={"character_id": 87},
        )
        assert switched.status_code == 200
        fresh = switched.json()
        fresh_token = client.cookies.get(SESSION_COOKIE)
        assert fresh["thread_id"] != old["thread_id"]
        assert fresh["character"]["id"] == 87
        assert fresh_token and fresh_token != old_token

        assert client.get(
            f"/api/sessions/{old['thread_id']}"
        ).status_code == 404
        assert client.get(
            f"/api/sessions/{fresh['thread_id']}"
        ).status_code == 200
        assert app.state.graph.history(old["thread_id"]) == []
        assert app.state.graph.history(fresh["thread_id"]) == []

    # O cookie antigo não volta a valer em outro processo.
    app = factory.app()
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, old_token)
        assert client.get(
            f"/api/sessions/{old['thread_id']}"
        ).status_code == 404
        client.cookies.set(SESSION_COOKIE, fresh_token)
        assert client.get(
            f"/api/sessions/{fresh['thread_id']}"
        ).status_code == 200


def test_one_cookie_cannot_read_or_write_another_session(factory):
    app = factory.app()
    with TestClient(app) as client:
        ana, ana_token = create(client, 42)
        bruno, bruno_token = create(client, 87)
        assert ana_token != bruno_token

        client.cookies.set(SESSION_COOKIE, ana_token)
        assert client.get(
            f"/api/sessions/{bruno['thread_id']}"
        ).status_code == 404
        assert say(
            client, bruno["thread_id"], "Windows"
        ).status_code == 404
        assert client.get(
            f"/api/sessions/{ana['thread_id']}"
        ).status_code == 200

        client.cookies.set(SESSION_COOKIE, bruno_token)
        assert client.get(
            f"/api/sessions/{ana['thread_id']}"
        ).status_code == 404


def test_model_failure_is_503_sanitized_and_retryable(factory):
    factory.next_error = ModelTimeout("SENTINELA-GEMINI-KEY")
    app = factory.app()
    with TestClient(app) as client:
        info, _ = create(client)
        response = say(
            client, info["thread_id"], "Como configuro a VPN no Windows?"
        )
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "model_timeout"
        assert error["retryable"] is True
        assert "SENTINELA" not in response.text
        assert "reply" not in response.json()

        factory.adapters[-1].error = None
        retry = say(
            client, info["thread_id"], "Como configuro a VPN no Windows?"
        )
        assert retry.status_code == 200
        assert retry.json()["reply"]["answer_status"] == "answered"
