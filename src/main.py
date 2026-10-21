import sys
from pathlib import Path

# Resolve a raiz do projeto (Squad-13-agente) a partir de src/main.py
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.config import load_settings
from src.glpi_integration.auth import fazer_login
from src.glpi_integration.GLPI_Client import GLPIClient
from src.rag.busca_artigos import buscar_artigos

def carregar_artigos():
    settings = load_settings(require_glpi=True)
    dados_login = fazer_login(
        settings.glpi_client_id,
        settings.glpi_client_secret,
        username=settings.glpi_username,
        password=settings.glpi_password,
    )

    client = GLPIClient(
        base_url=settings.glpi_base_url_v2,
        access_token=dados_login["access_token"],
        refresh_token=dados_login.get("refresh_token"), 
        client_id=settings.glpi_client_id,
        client_secret=settings.glpi_client_secret
    )

    artigos = client.search_all(
        "/Knowledgebase/Article",
        limit=25,
    )

    # A API deve devolver uma lista. Isso deixa o erro mais claro caso o
    # formato da resposta mude ou a integração retorne algo inesperado.
    if not isinstance(artigos, list):
        raise TypeError("A API do GLPI não retornou uma lista de artigos.")

    return artigos


if __name__ == "__main__":
    try:
        artigos = carregar_artigos()
    except Exception as erro:
        print(f"Erro ao carregar artigos do GLPI: {erro}")
        raise SystemExit(1)

    pergunta = "Como configurar a VPN corporativa no Windows?"

    resultados = buscar_artigos(
        pergunta,
        artigos,
    )

    if not resultados:
        print("Nenhum artigo relevante encontrado.")
    else:
        for resultado in resultados:
            print(
                f"ID: {resultado['id']} | "
                f"Pontuação: {resultado['score']} | "
                f"Título: {resultado['title']}"
            )
            print(f"Conteúdo: {resultado['content']}")
