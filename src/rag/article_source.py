from pathlib import Path
from sys import path

PROJ_ROOT = Path(__file__).resolve().parents[2]
if str(PROJ_ROOT) not in path:
    path.insert(0, str(PROJ_ROOT))

from src.glpi_integration.auth import fazer_login
from src.glpi_integration.GLPI_Client import (
    GLPIClient,
    GLPICollection,
    GLPIProtocolError
)
import logging

def source_treatment(instancia: GLPIClient)-> list:
    """
    Coleta e sanitiza os artigos da Base de Conhecimento do GLPI.
    
    Regra de Negócio (Decisão 1 e 4): 
    Todos os artigos retornados são considerados base técnica compartilhada para a demonstração.
    O sistema NÃO deve utilizar o campo 'is_faq' isoladamente como bloqueio de autorização.
    
    Amostra do Contrato de Saída (Sanitizado):
    [
        {
            "id": 123,
            "title": "Como configurar a VPN",
            "content": "<p>Passo a passo da VPN...</p>",
            "date_mod": "2026-10-20 14:30:00",
            "source_reference": "/Knowledgebase/Article"
        }
    ]
    """
    
    try:
        raw_data = instancia.search_all("/Knowledgebase/Article")

        if not isinstance(raw_data, GLPICollection):
            raise GLPIProtocolError("Ocorreur um erro no retorno dos dados!!")

        clean_data = []

        for data in raw_data:
            if not isinstance(data.get("id"), int) or not data.get("content"):

                logging.warning(f"o artigo {data.get('name')} retornou inválido")
                continue

            dict_data = {
                "id": data.get("id"),
                "title": data.get("name"),
                "content": data.get("content"),
                "date_mod": data.get("date_mod"),
                "source_reference": "/Knowledgebase/Article"
            }

            clean_data.append(dict_data)

        return clean_data

    except (TypeError, AttributeError) as e:
        logging.error(f"Falha no tratamento dos dados dos artigos: {__name__}")
        raise ValueError(f"Falha no tratamento dos dados vindos dos artigos")

    except GLPIProtocolError as e:
        logging.error(f"Dados inválidos:\n{__name__}-->\n{e}")
        raise ConnectionError(f"Dados retornados são inválidos: {__name__} --> {e}")
    
if __name__ == "__main__":
    from src.config import load_settings
    import os

    settings = load_settings(require_glpi=True)
    auth = fazer_login(settings.glpi_client_id, settings.glpi_client_secret)
    
    client = GLPIClient(
        settings.glpi_base_url_v2,
        auth.get("access_token"),
        auth.get("refresh_token"),
        settings.glpi_client_id,
        settings.glpi_client_secret
    )
    for i,e in enumerate(source_treatment(client)):
        print(f"{i}: {e['title']}")