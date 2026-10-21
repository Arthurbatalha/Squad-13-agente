import runpy
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def mock_module(monkeypatch, name, **attributes):
    """Substitui um módulo durante o teste, evitando serviços externos."""
    module = ModuleType(name)

    for key, value in attributes.items():
        setattr(module, key, value)

    monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("has_results", [True, False])
def test_main_displays_search_results(monkeypatch, capsys, has_results):
    results = [
        {
            "id": 1,
            "title": "VPN no Windows",
            "content": "Abra as configurações de VPN.",
            "score": 0.9,
        }
    ] if has_results else []

    # Fornece configurações fictícias para o teste, sem chamar serviços reais.
    monkeypatch.setenv("GLPI_CLIENT_ID", "test-client")
    monkeypatch.setenv("GLPI_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GLPI_BASE_URL_V1", "http://localhost:8080/api.php")
    monkeypatch.setenv("GLPI_BASE_URL_V2", "http://localhost:8080/api.php/v2")
    monkeypatch.setenv("APP_TIMEZONE", "America/Fortaleza")
    mock_module(monkeypatch, "dotenv", load_dotenv=lambda *args, **kwargs: None)

    # Evita autenticação e consultas ao GLPI.
    mock_module(
        monkeypatch,
        "src.glpi_integration.auth",
        fazer_login=lambda *args, **kwargs: {
            "access_token": "fake-access-token",
            "refresh_token": "fake-refresh-token",
        },
    )

    client = MagicMock()
    client.search_all.return_value = []

    mock_module(
        monkeypatch,
        "src.glpi_integration.GLPI_Client",
        GLPIClient=MagicMock(return_value=client),
    )

    # Simula o contrato devolvido pela recuperação.
    mock_module(
        monkeypatch,
        "src.rag.busca_artigos",
        buscar_artigos=lambda *args, **kwargs: results,
    )

    runpy.run_path(
        str(PROJECT_ROOT / "src" / "main.py"),
        run_name="__main__",
    )

    output = capsys.readouterr().out

    if has_results:
        assert "ID: 1" in output
        assert "Título: VPN no Windows" in output
        assert "Conteúdo: Abra as configurações de VPN." in output
        assert "Pontuação: 0.9" in output
        assert "Nenhum artigo relevante encontrado." not in output
    else:
        assert "Nenhum artigo relevante encontrado." in output
        assert "ID:" not in output


@pytest.mark.parametrize("has_results", [True, False])
def test_search_example_displays_results(monkeypatch, capsys, has_results):
    # Simula os resultados do cálculo de similaridade.
    # O modelo real não é carregado nem baixado.
    scores = [0.9, 0.1] if has_results else [0.1, 0.1]

    embeddings = MagicMock()
    embeddings.__getitem__.return_value.__matmul__.return_value = scores

    model = MagicMock()
    model.encode.return_value = embeddings

    mock_module(
        monkeypatch,
        "sentence_transformers",
        SentenceTransformer=MagicMock(return_value=model),
    )

    runpy.run_path(
        str(PROJECT_ROOT / "src" / "rag" / "busca_artigos.py"),
        run_name="__main__",
    )

    output = capsys.readouterr().out

    if has_results:
        assert "ID: 1" in output
        assert "Título: Configurar a VPN corporativa no Windows" in output
        assert "Conteúdo: Abra Configurações, Rede e Internet" in output
        assert "Pontuação: 0.9" in output
        assert "Nenhum artigo relevante encontrado." not in output
    else:
        assert "Nenhum artigo relevante encontrado." in output
        assert "ID:" not in output