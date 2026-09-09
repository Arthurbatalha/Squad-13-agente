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