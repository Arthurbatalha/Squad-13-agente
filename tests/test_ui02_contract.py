"""Extensões UI-02 com mock + SES-01 e diretório fictício, sem GLPI."""
import json

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.mock_backend import MockChatBackend
from src.sessions import SessionUnavailable


@pytest.fixture
def api():
    backend = MockChatBackend()
    return TestClient(create_app(backend, frontend_dist=None)), backend


def start(client, character=101):
    response = client.post("/api/sessions", json={"character_id": character})
    assert response.status_code == 201
    return response.json()["thread_id"]


def preview(client, thread, text="abrir chamado"):
    return client.post(f"/api/sessions/{thread}/messages", json={"text": text}).json()["reply"]["action"]


def decide(client, thread, action, decision="yes", **extra):
    return client.post(f"/api/sessions/{thread}/decisions", json={
        "action_id": action["action_id"], "version": action["version"], "decision": decision, **extra,
    })


@pytest.mark.parametrize("character", [101, 102])
def test_switch_invalidates_old_context_and_pending_in_ses01(api, character):
    client, backend = api
    old = start(client)
    action = preview(client, old)
    credential = backend._sessions[old].session_id
    switched = client.post(f"/api/sessions/{old}/switch", json={"character_id": character})
    assert switched.status_code == 200
    info = switched.json()
    assert info["thread_id"] != old and info["character"]["id"] == character
    assert info["role"] == "staff" and info["pending_action"] is None and info["last_write_result"] is None
    assert client.get(f"/api/sessions/{old}").status_code == 404
    assert decide(client, old, action).status_code == 404
    with pytest.raises(SessionUnavailable):
        backend._session_service.resume(credential, old)
    assert credential not in json.dumps(info)


def test_failed_switch_preserves_context_and_forbids_extra_fields(api):
    client, _ = api
    thread = start(client)
    action = preview(client, thread)
    assert client.post(f"/api/sessions/{thread}/switch", json={"character_id": 999}).status_code == 404
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] == action
    assert client.post(f"/api/sessions/{thread}/switch", json={"character_id": 102, "role": "admin"}).status_code == 422


@pytest.mark.parametrize("text", ["sim?", "s.i.m", "sim, se alterar", "não cancelar", "talvez"])
def test_legacy_messages_does_not_decide_ambiguous_text(api, text):
    client, backend = api
    thread = start(client)
    action = preview(client, thread)
    response = client.post(f"/api/sessions/{thread}/messages", json={"text": text})
    assert response.status_code == 409 and response.json()["error"]["code"] == "action_pending"
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] == action
    assert backend._next_ticket_id == 9001


@pytest.mark.parametrize("scenario,status,ticket", [("", "succeeded", 9001), ("simular parcial", "partial", 9001), ("simular incerto", "uncertain", None)])
def test_result_is_recoverable_without_repeating_decision(api, scenario, status, ticket):
    client, backend = api
    thread = start(client)
    action = preview(client, thread, f"abrir {scenario}")
    result = decide(client, thread, action).json()["reply"]
    assert result["status"] == status and result["ticket_id"] == ticket
    snapshot = client.get(f"/api/sessions/{thread}").json()
    assert snapshot["last_write_result"] == result and snapshot["pending_action"] is None
    assert client.get(f"/api/sessions/{start(client)}").json()["last_write_result"] is None
    assert decide(client, thread, action).json()["reply"] == result
    assert backend._next_ticket_id == 9002


def test_edited_version_required_even_after_completion_and_cancel_is_recoverable(api):
    client, _ = api
    thread = start(client)
    old = preview(client, thread)
    edited = decide(client, thread, old, "edit", text="Correção\nLinha 2").json()["reply"]["action"]
    assert edited["version"] == 2 and "Correção\nLinha 2" in edited["preview_text"]
    assert client.get(f"/api/sessions/{thread}").json()["pending_action"] == edited
    assert decide(client, thread, edited, "no").json()["reply"]["status"] == "cancelled"
    assert decide(client, thread, old).json()["error"]["code"] == "stale_action_version"
    assert client.get(f"/api/sessions/{thread}").json()["last_write_result"]["status"] == "cancelled"
