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
def test_main_reports_article_collection(monkeypatch, capsys, has_results):
    articles = [
        {
            "id": 1,
            "title": "VPN no Windows",
            "content": "Abra as configurações de VPN.",
            "date_mod": "2026-11-04 10:00:00",
            "source_reference": "/Knowledgebase/Article",
        }
    ] if has_results else []

    # Configuração fictícia: não lê o .env real.
    settings = MagicMock(
        glpi_base_url_v2="http://glpi.test/api.php/v2",
        glpi_client_id="test-client",
        glpi_client_secret="test-secret",
    )

    mock_module(
        monkeypatch,
        "src.config",
        load_settings=MagicMock(return_value=settings),
    )

    # Simula autenticação, sem acessar o GLPI.
    mock_module(
        monkeypatch,
        "src.glpi_integration.auth",
        fazer_login=MagicMock(
            return_value={
                "access_token": "fake-access-token",
                "refresh_token": "fake-refresh-token",
            }
        ),
    )

    client = MagicMock()

    mock_module(
        monkeypatch,
        "src.glpi_integration.GLPI_Client",
        GLPIClient=MagicMock(return_value=client),
    )

    # Simula o coletor que o main.py utiliza atualmente.
    collect_articles = MagicMock(return_value=articles)

    mock_module(
        monkeypatch,
        "src.rag.article_source",
        source_treatment=collect_articles,
    )

    # runpy simula `python src/main.py` sem herdar os argumentos do pytest.
    monkeypatch.setattr(
        sys, "argv", [str(PROJECT_ROOT / "src" / "main.py")]
    )
    runpy.run_path(
        str(PROJECT_ROOT / "src" / "main.py"),
        run_name="__main__",
    )

    output = capsys.readouterr().out

    collect_articles.assert_called_once_with(client)
    assert "Erro na coleta de artigos:" not in output

    if has_results:
        assert "Artigos Carregados:1" in output
        assert "a base de artigos está vazia" not in output
    else:
        assert "Coleta bem-sucedida, mas a base de artigos está vazia." in output
        assert "Artigos Carregados:" not in output


@pytest.mark.parametrize("has_results", [True, False])
def test_search_example_displays_results(monkeypatch, capsys, has_results):
    # Simula os resultados do cálculo de similaridade.
    # O modelo real não é carregado nem baixado.
    import numpy as np
    from src.rag.corpus import CorpusService
    from src.rag.embeddings import EmbeddingService
    from test.embedding_fakes import ModelSpy, unit

    def vector(text):
        if text.startswith("Estou usando"):
            result = np.zeros(384)
            result[:3] = [0.9, np.sqrt(0.19), 0] if has_results else [0.1, 0.1, np.sqrt(0.98)]
            return result
        return unit(1 if "IKEv2" in text else 0)

    search = CorpusService(EmbeddingService(model=ModelSpy(vector)))
    monkeypatch.setattr("src.rag.corpus.get_search_service", lambda: search)

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
