"""UI-01 — testes de contrato da API com o adaptador simulado.

Rodar (na raiz do repositório):  python -m pytest tests/test_api_contract.py -v
Isto valida o CONTRATO com um mock. Não prova integração com GLPI, índice ou Gemini.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.backend import ChatBackendError
from src.api.mock_backend import MockChatBackend


@pytest.fixture()
def client():
    return TestClient(create_app(MockChatBackend(), cors_origins=["http://localhost:5173"]))


def new_session(client, character_id=101):
    response = client.post("/api/sessions", json={"character_id": character_id})
    assert response.status_code == 201, response.text
    return response.json()


def say(client, thread_id, text):
    return client.post(f"/api/sessions/{thread_id}/messages", json={"text": text})


def preview(client, thread_id):
    response = say(client, thread_id, "quero abrir um chamado para a VPN")
    assert response.status_code == 200, response.text
    reply = response.json()["reply"]
    assert reply["type"] == "preview"
    return reply["action"]


def decide(client, thread_id, action, decision, text=None):
    body = {"action_id": action["action_id"], "version": action["version"], "decision": decision}
    if text is not None:
        body["text"] = text
    return client.post(f"/api/sessions/{thread_id}/decisions", json=body)


# --- sessão e identidade ----------------------------------------------------
def test_health_identifies_the_adapter(client):
    assert client.get("/api/health").json() == {"status": "ok", "adapter": "mock"}


def test_session_is_always_staff_and_has_own_thread(client):
    a, b = new_session(client, 101), new_session(client, 102)
    assert a["role"] == b["role"] == "staff"
    assert a["thread_id"] != b["thread_id"]
    assert a["character"]["id"] == 101 and b["character"]["id"] == 102
    assert a["adapter"] == "mock"
    assert a["pending_action"] is None


def test_client_cannot_choose_role_or_send_credentials(client):
    for extra in ({"role": "admin"}, {"role": "staff"}, {"access_token": "x"}):
        response = client.post("/api/sessions", json={"character_id": 101, **extra})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


def test_unknown_character_and_unknown_session(client):
    response = client.post("/api/sessions", json={"character_id": 999})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "character_not_found"
    assert say(client, "nao-existe", "oi").status_code == 404
    assert client.get("/api/sessions/nao-existe").json()["error"]["code"] == "session_not_found"


def test_responses_never_expose_tokens(client):
    session = new_session(client)
    payloads = [session, say(client, session["thread_id"], "vpn").json()]
    text = json.dumps(payloads).lower()
    for forbidden in ("token", "secret", "bearer", "client_id"):
        assert forbidden not in text


# --- respostas de leitura ---------------------------------------------------
def test_text_reply_with_sources(client):
    thread = new_session(client)["thread_id"]
    body = say(client, thread, "Como configuro a VPN?").json()
    assert body["thread_id"] == thread
    reply = body["reply"]
    assert reply["type"] == "text" and reply["answer_status"] == "answered"
    source = reply["sources"][0]
    assert {"source_type", "source_id", "title", "reference"} <= set(source)
    assert source["source_type"] in ("article", "case")


def test_no_evidence_and_index_unavailable_are_distinct(client):
    thread = new_session(client)["thread_id"]
    no_evidence = say(client, thread, "pergunta sem relacao").json()["reply"]
    unavailable = say(client, thread, "indisponível").json()["reply"]
    assert no_evidence["answer_status"] == "no_evidence" and no_evidence["sources"] == []
    assert unavailable["answer_status"] == "index_unavailable"


def test_clarification_reply(client):
    thread = new_session(client)["thread_id"]
    reply = say(client, thread, "problema na impressora").json()["reply"]
    assert reply["type"] == "clarification" and reply["question"]


# --- validação de entrada e formato de erro ---------------------------------
@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_invalid_message_text(client, text):
    thread = new_session(client)["thread_id"]
    response = say(client, thread, text)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_validation_error_does_not_echo_input(client):
    thread = new_session(client)["thread_id"]
    response = client.post(
        f"/api/sessions/{thread}/messages", json={"text": "", "token": "SEGREDO-123"}
    )
    assert response.status_code == 422
    assert "SEGREDO-123" not in response.text


def test_edit_decision_requires_text(client):
    thread = new_session(client)["thread_id"]
    action = preview(client, thread)
    assert decide(client, thread, action, "edit").status_code == 422


# --- escrita: prévia, confirmação, cancelamento, versão ---------------------
def test_open_ticket_preview_contract(client):
    session = new_session(client, 101)
    thread = session["thread_id"]
    action = preview(client, thread)
    assert action["version"] == 1 and action["status"] == "pending"
    assert action["operation"] == "open_ticket"
    assert action["staff_user_id"] == 101
    assert {"title", "description", "category_id", "priority", "requester_id"} == set(
        action["payload"]
    )
    # a prévia mostrada corresponde ao payload que será executado
    assert str(action["payload"]["requester_id"]) in action["preview_text"]
    assert action["payload"]["title"] in action["preview_text"]
    # o estado pendente sobrevive à releitura da sessão
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] == action


def test_followup_preview_is_public_only(client):
    thread = new_session(client)["thread_id"]
    reply = say(client, thread, "adicionar acompanhamento no chamado").json()["reply"]
    assert reply["type"] == "preview"
    assert reply["action"]["operation"] == "add_public_followup"
    assert reply["action"]["payload"]["is_private"] is False


def test_nothing_is_written_before_confirmation(client):
    thread = new_session(client)["thread_id"]
    preview(client, thread)
    # mensagem ambígua com ação pendente: recusada, continua pendente
    response = say(client, thread, "talvez")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "action_pending"
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] is not None


def test_confirm_by_decision_and_repeat_is_idempotent(client):
    thread = new_session(client)["thread_id"]
    action = preview(client, thread)
    first = decide(client, thread, action, "yes").json()["reply"]
    assert first["type"] == "write_result" and first["status"] == "succeeded"
    assert isinstance(first["ticket_id"], int)
    again = decide(client, thread, action, "yes").json()["reply"]
    assert again == first  # mesmo ticket, sem nova criação
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] is None


def test_confirm_by_text_sim_and_nao(client):
    thread = new_session(client)["thread_id"]
    preview(client, thread)
    assert say(client, thread, "Sim!").json()["reply"]["status"] == "succeeded"
    preview(client, thread)
    reply = say(client, thread, "não").json()["reply"]
    assert reply["status"] == "cancelled" and reply["ticket_id"] is None


def test_cancel_by_decision(client):
    thread = new_session(client)["thread_id"]
    action = preview(client, thread)
    reply = decide(client, thread, action, "no").json()["reply"]
    assert reply["status"] == "cancelled"
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] is None


def test_edit_creates_new_version_and_invalidates_old_one(client):
    thread = new_session(client)["thread_id"]
    v1 = preview(client, thread)
    v2 = decide(client, thread, v1, "edit", text="descrição corrigida").json()["reply"]["action"]
    assert v2["version"] == 2 and v2["action_id"] == v1["action_id"]
    assert "descrição corrigida" in v2["preview_text"]
    stale = decide(client, thread, v1, "yes")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_action_version"
    assert decide(client, thread, v2, "yes").json()["reply"]["status"] == "succeeded"


def test_decision_without_pending_action(client):
    thread = new_session(client)["thread_id"]
    fake = {"action_id": "x", "version": 1}
    assert decide(client, thread, fake, "yes").json()["error"]["code"] == "no_pending_action"


def test_pending_action_is_isolated_between_sessions(client):
    a, b = new_session(client)["thread_id"], new_session(client)["thread_id"]
    action = preview(client, a)
    assert client.get(f"/api/sessions/{b}").json()["pending_action"] is None
    assert decide(client, b, action, "yes").status_code == 409
    assert client.get(f"/api/sessions/{a}").json()["pending_action"] is not None


# --- infraestrutura ---------------------------------------------------------
def test_backend_errors_use_the_error_format():
    class Broken(MockChatBackend):
        def handle_message(self, thread_id, text):
            raise ChatBackendError("backend_unavailable", "Fora do ar.", 503, retryable=True)

    client = TestClient(create_app(Broken(), cors_origins=[]))
    thread = new_session(client)["thread_id"]
    response = say(client, thread, "oi")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "backend_unavailable",
            "message": "Fora do ar.",
            "retryable": True,
            "details": [],
        }
    }


def test_cors_allows_only_the_configured_origin(client):
    def preflight(origin):
        return client.options(
            "/api/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    ok = preflight("http://localhost:5173")
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = preflight("http://evil.example")
    assert "access-control-allow-origin" not in other.headers


def test_openapi_exposes_the_contract_routes(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/api/health",
        "/api/characters",
        "/api/sessions",
        "/api/sessions/{thread_id}",
        "/api/sessions/{thread_id}/messages",
        "/api/sessions/{thread_id}/decisions",
    } <= paths
