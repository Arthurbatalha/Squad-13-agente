import pytest
from pathlib import Path
import sys

PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

from unittest.mock import MagicMock
from src.rag.article_source import source_treatment
from src.glpi_integration.GLPI_Client import GLPICollection, GLPIProtocolError

mock_client = MagicMock()

# Sucesso na coleta de contrato válido
def test_01():
    mock_client.search_all.return_value = GLPICollection(endpoint="/Knowledgebase/Article", items=[
        {"id": 0,"name": "VPN","content": "HTML", "date_mod":"2026-10-31"}
        ], total=1, pages=1)

    res = source_treatment(mock_client)

    assert len(res) == 1
    assert res[0]["title"] == "VPN"
    assert res[0]["source_reference"] == "/Knowledgebase/Article"

# Ignora artigos inválidos
def test_02():
    mock_client.search_all.return_value = GLPICollection(endpoint="/Knowledgebase/Article", items=[
        {"name": "Pão", "content": "HTML", "date_mod": "1971-15-12"},
        {"id": 1, "name": "Batata", "content": None},
        {"id": 45, "name": "Sopa", "content": "", "date_mod": "2006-07-04"}
    ], total=3, pages=1)

    res = source_treatment(mock_client)

    assert len(res) == 0

# Coleta vazia é tratada como válida
def test_03():
    mock_client.search_all.return_value = GLPICollection(endpoint="/Knowledgebase/Article", items=[], total=0,pages=1)

    res = source_treatment(mock_client)

    assert res == []

# Indisponibilidade da API lança erro
def test_04():
    mock_client.search_all.side_effect = GLPIProtocolError("Erro de rede hipotético...")

    with pytest.raises(ConnectionError):
        source_treatment(mock_client)