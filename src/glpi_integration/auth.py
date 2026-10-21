import requests
import sys
from pathlib import Path
import logging

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.config import load_settings

REQUEST_TIMEOUT_SECONDS = 10


class GLPIAuthenticationError(ValueError):
    """Raised when GLPI rejects credentials or a refresh token."""


class GLPIProtocolError(RuntimeError):
    """Raised when GLPI returns an invalid token response."""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def _token_url(settings):
    base_url = settings.glpi_base_url_v1
    if not base_url:
        raise ValueError("GLPI_BASE_URL_V1 não configurada no .env")
    return f"{base_url.rstrip('/')}/token"


def _auth_context(client_id, client_secret):
    settings = load_settings()
    client_id = settings.glpi_client_id if client_id is None else client_id
    client_secret = settings.glpi_client_secret if client_secret is None else client_secret

    missing = [
        name for name, value in (
            ("GLPI_CLIENT_ID", client_id),
            ("GLPI_CLIENT_SECRET", client_secret),
        )
        if not isinstance(value, str) or not value.strip()
    ]
    if missing:
        raise ValueError("Configuração GLPI ausente: " + ", ".join(missing))

    _token_url(settings)
    return settings, client_id.strip(), client_secret.strip()


def _request_token(settings, payload, authentication_message):
    try:
        response = requests.post(
            _token_url(settings),
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise ConnectionError("Não foi possível comunicar com o servidor do GLPI.") from exc

    if response.status_code == 401:
        raise GLPIAuthenticationError(authentication_message)

    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise ConnectionError("O GLPI falhou ao processar a autenticação.") from exc

    try:
        token_data = response.json()
    except ValueError as exc:
        raise GLPIProtocolError("O GLPI retornou uma resposta de token inválida.") from exc

    if not isinstance(token_data, dict):
        raise GLPIProtocolError("O GLPI retornou uma resposta de token inválida.")

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise GLPIProtocolError("A resposta do GLPI não contém um access_token válido.")
    if refresh_token is not None and (
        not isinstance(refresh_token, str) or not refresh_token.strip()
    ):
        raise GLPIProtocolError("A resposta do GLPI contém um refresh_token inválido.")

    return token_data


def fazer_login(client_id, client_secret, username=None, password=None):
    """Realiza o login inicial usando credenciais fornecidas pelo backend."""
    settings, client_id, client_secret = _auth_context(client_id, client_secret)
    username = settings.glpi_username if username is None else username
    password = settings.glpi_password if password is None else password
    if not isinstance(username, str) or not username.strip():
        raise ValueError("GLPI_USERNAME não configurado.")
    if not isinstance(password, str) or not password.strip():
        raise ValueError("GLPI_PASSWORD não configurado.")

    payload = {
        "grant_type": "password",
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username.strip(),
        "password": password,
        "scope": "api"
    }

    return _request_token(
        settings,
        payload,
        "Client ID, secret, usuário ou senha inválidos.",
    )


def renovar_token(client_id, client_secret, refresh_token):
    """Gera um novo access_token usando o refresh_token."""
    settings, client_id, client_secret = _auth_context(client_id, client_secret)
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise GLPIAuthenticationError("Refresh token ausente ou inválido.")

    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token.strip(),
        "scope": "api"
    }

    return _request_token(settings, payload, "Refresh token inválido ou expirado.")

# Teste do script
if __name__ == "__main__":
    # Colar credenciais
    settings = load_settings(require_glpi=True)
    CLIENT_ID = settings.glpi_client_id
    CLIENT_SECRET = settings.glpi_client_secret
    
    # Ajustado o nome da constante

    try:
        logging.info("1. Testando Login Inicial")
        dados_login = fazer_login(CLIENT_ID, CLIENT_SECRET)
        token_atualizado = dados_login["refresh_token"]

        logging.info("Login realizado com sucesso.")
        
        logging.info("2. Testando Refresh de Token")
        dados_refresh = renovar_token(CLIENT_ID, CLIENT_SECRET, token_atualizado)
        logging.info("Refresh realizado com sucesso.")

    except ValueError as e:
        logging.error(f"Falha na validação: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado: {e}")