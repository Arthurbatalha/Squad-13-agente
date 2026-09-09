import sys
from pathlib import Path

# Resolve a pasta Agent a partir deste arquivo, independentemente do diretório
# em que o comando `python app/integrar_glpi.py` for executado.
RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTA_AGENT = RAIZ_PROJETO / "Agent"

if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

if str(PASTA_AGENT) not in sys.path:
    sys.path.insert(0, str(PASTA_AGENT))

from auth import fazer_login
from GLPI_Client import GLPIClient
from app.busca_artigos import buscar_artigos


CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"


def carregar_artigos():
    dados_login = fazer_login(CLIENT_ID, CLIENT_SECRET)

    client = GLPIClient(
        access_token=dados_login["access_token"]
    )

    artigos = client.all_call_search(
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
                f"Pontuação: {resultado['pontuacao']} | "
                f"Título: {resultado['titulo']}"
            )
            print(f"Conteúdo: {resultado['conteudo']}")
