import requests
import os
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

load_dotenv()

BASE_URL = os.getenv("GLPI_BASE_URL_V1")

def fazer_login(client_id, client_secret, username="glpi", password="glpi"):
    """Realiza o login inicial usando usuário e senha."""
    url = f"{BASE_URL}/token"
    payload = {
        "grant_type": "password",
        "client_id": client_id,          # CORRIGIDO: Agora usa o parâmetro da função
        "client_secret": client_secret,  # CORRIGIDO: Agora usa o parâmetro da função
        "username": username,
        "password": password,
        "scope": "api"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        # Tratamento de erro da credencial (Item 3 da task)
        if response.status_code == 401:
            raise ValueError("Erro de autenticação: Client ID ou Secret inválidos.")

        response.raise_for_status() # lança erro para outro problemas
        return response.json()

    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"Não é possível se comunicar com o servidor do GLPI no momento {e}")

def renovar_token(client_id, client_secret, refresh_token): # CORRIGIDO: Nome do parâmetro arrumado
    """Gera um novo access_token usando o refresh_token."""
    url = f"{BASE_URL}/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scope": "api"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 401:
            raise ValueError("Erro ao renovar: Refresh token inválido ou expirado.")

        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Não é possível se comunicar com o servidor do GLPI no momento: {e}")

# Teste do script
if __name__ == "__main__":
    # Colar credenciais
    CLIENT_ID = os.getenv("GLPI_CLIENT_ID")
    CLIENT_SECRET = os.getenv("GLPI_CLIENT_SECRET")
    
    # Ajustado o nome da constante

    try:
        logging.info("1. Testando Login Inicial")
        dados_login = fazer_login(CLIENT_ID, CLIENT_SECRET)
        token_acesso = dados_login["access_token"]  # CORRIGIDO: Nome da chave correto
        token_atualizado = dados_login["refresh_token"]

        logging.info(f"Login com sucesso! \nAccess Token obtido (primeiros 20 chars): {token_acesso[:20]}...\n")
        
        logging.info("2. Testando Refresh de Token")
        dados_refresh = renovar_token(CLIENT_ID, CLIENT_SECRET, token_atualizado)
        novo_token_acesso = dados_refresh["access_token"]

        logging.info(f"Refresh com sucesso! \nNovo Access Token obtido (primeiros 20 chars): {novo_token_acesso[:20]}...\n") # CORRIGIDO: Adicionado aspas duplas no final

    except ValueError as e:
        logging.error(f"Falha na validação: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado: {e}")