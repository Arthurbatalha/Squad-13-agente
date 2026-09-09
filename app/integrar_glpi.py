import sys

sys.path.append("../agent")

from auth import fazer_login
from GLPI_Client import GLPIClient
from busca_artigos import buscar_artigos


CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"


def carregar_artigos():
    dados_login = fazer_login(CLIENT_ID, CLIENT_SECRET)

    client = GLPIClient(
        access_token=dados_login["access_token"]
    )

    return client.all_call_search(
        "/Knowledgebase/Article",
        limit=25
    )


if __name__ == "__main__":

    artigos = carregar_artigos()

    pergunta = "Como configurar a VPN corporativa no Windows?"

    resultados = buscar_artigos(
        pergunta,
        artigos
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
