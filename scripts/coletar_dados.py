from collections import Counter

import requests


BASE_URL = "http://localhost:8080"

CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = (
    "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"
)

GLPI_USERNAME = "glpi"
GLPI_PASSWORD = "glpi"


# =========================================================
# AUTENTICAÇÃO OAUTH 2.0
# =========================================================

def obter_token():
    """Obtém um access_token OAuth2 do GLPI 11."""
    url = f"{BASE_URL}/api.php/token"

    payload = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username": GLPI_USERNAME,
        "password": GLPI_PASSWORD,
        "scope": "api",
    }

    resp = requests.post(url, json=payload, timeout=30)

    print(f"Status da autenticação: {resp.status_code}")

    if not resp.ok:
        print("Resposta do GLPI:")
        print(resp.text)

    resp.raise_for_status()

    dados = resp.json()

    if "access_token" not in dados:
        raise RuntimeError(
            "O GLPI respondeu à autenticação, mas não retornou access_token. "
            f"Resposta: {dados}"
        )

    return dados["access_token"]


# =========================================================
# CONSULTAS À API V2
# =========================================================

def buscar_todos(endpoint, token):
    """Busca todos os registros de um endpoint paginado da API v2."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    itens = []
    start = 0
    limit = 50

    while True:
        url = f"{BASE_URL}{endpoint}"
        params = {
            "start": start,
            "limit": limit,
        }

        resp = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=30,
        )

        # A API pode responder 200 (coleção completa) ou 206 (página parcial).
        # Tratar qualquer 2xx como sucesso deixa o código compatível com ambos.
        if not 200 <= resp.status_code < 300:
            print(f"Erro ao consultar {endpoint}: HTTP {resp.status_code}")
            print(resp.text)
            resp.raise_for_status()

        dados = resp.json()

        if isinstance(dados, list):
            lista = dados
        elif isinstance(dados, dict):
            lista = dados.get("data", [])
        else:
            lista = []

        if not lista:
            break

        itens.extend(lista)

        # HTTP 200 normalmente indica que o que foi pedido já cobriu toda a
        # coleção. Também paramos quando vier menos registros que o limite.
        if resp.status_code == 200 or len(lista) < limit:
            break

        start += limit

    return itens


def nome_dropdown(valor, padrao="Não informado"):
    """Extrai um nome legível de dropdowns expandidos da API v2."""
    if isinstance(valor, dict):
        return valor.get("name") or str(valor.get("id", padrao))

    if valor is None or valor == "":
        return padrao

    return str(valor)


# =========================================================
# EXECUÇÃO
# =========================================================

def main():
    print("Autenticando via OAuth 2.0...")

    try:
        token = obter_token()
        print("Token obtido com sucesso!\n")
    except requests.RequestException as e:
        print(f"Erro HTTP ao obter token: {e}")
        return
    except Exception as e:
        print(f"Erro ao obter token: {e}")
        return

    print("Buscando chamados (Tickets)...")

    try:
        chamados = buscar_todos(
            "/api.php/v2/Assistance/Ticket",
            token,
        )
    except requests.RequestException as e:
        print(f"Erro ao buscar chamados: {e}")
        return

    print(f"Total de chamados encontrados: {len(chamados)}")

    # Na API v2, status e category vêm como objetos {id, name}.
    status_contagem = Counter(
        nome_dropdown(ticket.get("status"))
        for ticket in chamados
    )

    categoria_contagem = Counter(
        nome_dropdown(ticket.get("category"))
        for ticket in chamados
    )

    print("\n--- DISTRIBUIÇÃO POR STATUS ---")
    for status, qtd in sorted(status_contagem.items()):
        print(f"{status}: {qtd}")

    print("\n--- DISTRIBUIÇÃO POR CATEGORIA ---")
    for categoria, qtd in sorted(categoria_contagem.items()):
        print(f"{categoria}: {qtd}")

    print("\nBuscando artigos da Base de Conhecimento...")

    try:
        artigos = buscar_todos(
            "/api.php/v2/Knowledgebase/Article",
            token,
        )
    except requests.RequestException as e:
        print(f"Erro ao buscar artigos: {e}")
        return

    print(f"Total de artigos encontrados: {len(artigos)}")


if __name__ == "__main__":
    main()
