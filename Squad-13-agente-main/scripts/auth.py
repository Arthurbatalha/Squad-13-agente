import requests

BASE_URL = "http://localhost:8080/api.php"

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

    response = requests.post(url, json=payload)

    # Tratamento de erro da credencial (Item 3 da task)
    if response.status_code == 401:
        raise ValueError("Erro de autenticação: Client ID ou Secret inválidos.")

    response.raise_for_status() # lança erro para outro problemas
    return response.json()

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

    response = requests.post(url, json=payload)

    if response.status_code == 401:
        raise ValueError("Erro ao renovar: Refresh token inválido ou expirado.")

    response.raise_for_status()
    return response.json()


# Teste do script
if __name__ == "__main__":
    # Colar credenciais
    MEU_CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
    MEU_CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17" # Ajustado o nome da constante

    try:
        print("1. Testando Login Inicial")
        dados_login = fazer_login(MEU_CLIENT_ID, MEU_CLIENT_SECRET)
        token_acesso = dados_login["access_token"]  # CORRIGIDO: Nome da chave correto
        token_atualizado = dados_login["refresh_token"]

        print(f"Login com sucesso! \nAccess Token obtido (primeiros 20 chars): {token_acesso[:20]}...\n")
        
        print("2. Testando Refresh de Token")
        dados_refresh = renovar_token(MEU_CLIENT_ID, MEU_CLIENT_SECRET, token_atualizado)
        novo_token_acesso = dados_refresh["access_token"]

        print(f"Refresh com sucesso! \nNovo Access Token obtido (primeiros 20 chars): {novo_token_acesso[:20]}...\n") # CORRIGIDO: Adicionado aspas duplas no final

    except ValueError as e:
        print(f"Falha na validação: {e}")
    except Exception as e:
        print(f"Erro inesperado: {e}")