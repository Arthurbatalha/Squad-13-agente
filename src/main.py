import logging
import sys
from pathlib import Path

# Resolve a raiz do projeto (Squad-13-agente) a partir de src/main.py
RAIZ_PROJETO = Path(__file__).resolve().parent.parent

if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.config import load_settings
from src.glpi_integration.auth import fazer_login
from src.glpi_integration.GLPI_Client import GLPIClient
from src.rag.article_source import source_treatment

if __name__ == "__main__":

    settings = load_settings(require_glpi=True)
    auth = fazer_login(
        settings.glpi_client_id,
        settings.glpi_client_secret
    )
    client = GLPIClient(
        settings.glpi_base_url_v2,
        auth.get("access_token"),
        auth.get("refresh_token"),
        settings.glpi_client_id,
        settings.glpi_client_secret
    )
    try:
        data_list = source_treatment(client)

        if data_list:
            print(f"Tudo está rodando corretamente... Artigos Carregados:{len(data_list)}")
        else:
            print("Coleta bem-sucedida, mas a base de artigos está vazia.")
    
    except (ConnectionError, ValueError) as e:
        logging.error(f"Erro nas ferramentas: {e}")
        print(f"Erro na coleta de artigos: {e}")