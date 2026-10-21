import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import src.glpi_integration.GLPI_Client as client_module
import src.glpi_integration.auth as auth_module
from src.glpi_integration.GLPI_Client import GLPIClient, GLPIWriteOutcomeUnknownError
from src.glpi_integration.auth import (
    GLPIAuthenticationError,
    GLPIProtocolError,
    REQUEST_TIMEOUT_SECONDS,
    fazer_login,
    renovar_token,
)


def fake_settings(**overrides):
    values = {
        "glpi_base_url_v1": "http://glpi.test/api.php/",
        "glpi_client_id": "backend-client-id",
        "glpi_client_secret": "backend-client-secret",
        "glpi_username": "backend-user",
        "glpi_password": "backend-password",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def response(status_code=200, body=None):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = body
    result.text = "ok"
    return result


def make_client():
    return GLPIClient(
        "http://glpi.test/api.php/v2",
        "old-access-token",
        "old-refresh-token",
        "backend-client-id",
        "backend-client-secret",
    )


def test_login_and_refresh_reuse_timeout_and_backend_credentials(monkeypatch):
    monkeypatch.setattr(auth_module, "load_settings", lambda: fake_settings())
    post = Mock(return_value=response(body={
        "access_token": "access-new",
        "refresh_token": "refresh-new",
    }))
    monkeypatch.setattr(auth_module.requests, "post", post)

    login_result = fazer_login(None, None)
    refresh_result = renovar_token(None, None, "refresh-old")

    assert login_result["access_token"] == "access-new"
    assert refresh_result["access_token"] == "access-new"
    assert post.call_count == 2
    for call in post.call_args_list:
        assert call.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS
        assert call.args[0] == "http://glpi.test/api.php/token"
        assert call.kwargs["json"]["client_id"] == "backend-client-id"
        assert call.kwargs["json"]["client_secret"] == "backend-client-secret"


@pytest.mark.parametrize(
    "overrides,missing_name",
    [
        ({"glpi_base_url_v1": None}, "GLPI_BASE_URL_V1"),
        ({"glpi_client_id": None}, "GLPI_CLIENT_ID"),
        ({"glpi_client_secret": None}, "GLPI_CLIENT_SECRET"),
    ],
)
def test_missing_auth_configuration_fails_before_network(monkeypatch, overrides, missing_name):
    monkeypatch.setattr(auth_module, "load_settings", lambda: fake_settings(**overrides))
    post = Mock()
    monkeypatch.setattr(auth_module.requests, "post", post)

    with pytest.raises(ValueError, match=missing_name):
        fazer_login(None, None)

    post.assert_not_called()


@pytest.mark.parametrize(
    "status,body,error",
    [
        (401, {}, GLPIAuthenticationError),
        (200, [], GLPIProtocolError),
        (200, {"refresh_token": "refresh-only"}, GLPIProtocolError),
    ],
)
def test_login_rejects_invalid_auth_or_token_responses(monkeypatch, status, body, error):
    monkeypatch.setattr(auth_module, "load_settings", lambda: fake_settings())
    post = Mock(return_value=response(status_code=status, body=body))
    monkeypatch.setattr(auth_module.requests, "post", post)

    with pytest.raises(error):
        fazer_login("client-id", "client-secret")

    post.assert_called_once()


def test_auth_network_failure_is_connection_error_without_secrets_in_message(monkeypatch):
    monkeypatch.setattr(auth_module, "load_settings", lambda: fake_settings())
    monkeypatch.setattr(
        auth_module.requests,
        "post",
        Mock(side_effect=requests.Timeout("network unavailable")),
    )

    with pytest.raises(ConnectionError) as error:
        fazer_login("private-client-id", "private-client-secret")

    assert "private-client-secret" not in str(error.value)


def test_refresh_updates_bearer_and_reuses_timeout(monkeypatch, caplog):
    client = make_client()
    request = Mock(side_effect=[response(status_code=401), response()])
    refresh = Mock(return_value={
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
    })
    monkeypatch.setattr(client_module.requests, "request", request)
    monkeypatch.setattr(client_module, "renovar_token", refresh)

    client._secure_request("GET", "http://glpi.test/resource")

    assert request.call_count == 2
    assert request.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer old-access-token"
    assert request.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer new-access-token"
    assert all(call.kwargs["timeout"] == REQUEST_TIMEOUT_SECONDS for call in request.call_args_list)
    assert client.token == "new-access-token"
    assert client.refresh_token == "new-refresh-token"
    refresh.assert_called_once_with("backend-client-id", "backend-client-secret", "old-refresh-token")
    for secret in ("old-access-token", "new-access-token", "old-refresh-token", "new-refresh-token"):
        assert secret not in caplog.text


def test_invalid_refresh_does_not_repeat_api_request(monkeypatch):
    client = make_client()
    request = Mock(return_value=response(status_code=401))
    refresh = Mock(side_effect=GLPIAuthenticationError("refresh inválido"))
    monkeypatch.setattr(client_module.requests, "request", request)
    monkeypatch.setattr(client_module, "renovar_token", refresh)

    with pytest.raises(GLPIAuthenticationError):
        client._secure_request("GET", "http://glpi.test/resource")

    request.assert_called_once()
    refresh.assert_called_once()


def test_persistent_401_stops_after_single_refresh(monkeypatch):
    client = make_client()
    request = Mock(side_effect=[response(status_code=401), response(status_code=401)])
    monkeypatch.setattr(client_module.requests, "request", request)
    monkeypatch.setattr(
        client_module,
        "renovar_token",
        Mock(return_value={"access_token": "new-access", "refresh_token": "new-refresh"}),
    )

    with pytest.raises(GLPIAuthenticationError):
        client._secure_request("GET", "http://glpi.test/resource")

    assert request.call_count == 2


def test_unexpected_refresh_response_does_not_replay(monkeypatch):
    client = make_client()
    request = Mock(return_value=response(status_code=401))
    monkeypatch.setattr(client_module.requests, "request", request)
    monkeypatch.setattr(client_module, "renovar_token", Mock(return_value=[]))

    with pytest.raises(GLPIProtocolError):
        client._secure_request("GET", "http://glpi.test/resource")

    request.assert_called_once()


def test_network_failure_and_post_timeout_are_not_retried(monkeypatch):
    client = make_client()
    request = Mock(side_effect=requests.Timeout("network unavailable"))
    monkeypatch.setattr(client_module.requests, "request", request)

    with pytest.raises(ConnectionError):
        client._secure_request("GET", "http://glpi.test/resource")
    request.assert_called_once()

    request.reset_mock()
    with pytest.raises(GLPIWriteOutcomeUnknownError, match="resultado no GLPI é incerto"):
        client._secure_request("POST", "http://glpi.test/resource", json={"content": "x"})
    request.assert_called_once()