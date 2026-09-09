import sys
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PASTA_AGENT = RAIZ_PROJETO / "Agent"

if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))
    
if str(PASTA_AGENT) not in sys.path:
    sys.path.insert(0, str(PASTA_AGENT))
    

from scripts.auth import fazer_login
from GLPI_Client import GLPIClient
from app.busca_artigos import remover_html

CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"

CAMINHO_SAIDA = RAIZ_PROJETO / "data" / "artigos.json"


def extrair_artigos():
    dados_login = fazer_login(CLIENT_ID, CLIENT_SECRET)
    client = GLPIClient(access_token=dados_login["access_token"])
    
    artigos = client.all_call_search(
        "/Knowledgebase/Article",
        limit=25
    )
    
    artigos_limpos = []
    for artigo in artigos:
        busca = {"id": artigo["id"], "titulo": artigo["name"],}
    
if __name__ == "__main__":