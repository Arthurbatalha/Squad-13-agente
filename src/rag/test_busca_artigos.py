import sys
import pathlib as pth

PROJECT_ROOT = pth.Path(__file__).resolve().parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from .busca_artigos import buscar_artigos
    from .artigos_teste import artigos
except ImportError:
    # Permite executar o arquivo diretamente dentro da pasta app.
    from src.rag.busca_artigos import buscar_artigos
    from src.rag.artigos_teste import artigos


import pytest
from src.rag.corpus import CorpusService
from src.rag.embeddings import EmbeddingService
from test.embedding_fakes import ModelSpy, unit


@pytest.fixture
def search():
    def vector(text):
        key = text.casefold()
        index = 0 if "windows" in key else 1 if "macos" in key else 3 if "cafeteira" in key else 2
        return unit(index)
    return CorpusService(EmbeddingService(model=ModelSpy(vector)))


def test_vpn_windows(search):
    resultados = buscar_artigos(
        "Como configurar a VPN no Windows?",
        artigos, service=search,
    )

    assert resultados
    assert resultados[0]["id"] == 1
    assert resultados[0]["title"] == "Configurar a VPN corporativa no Windows"
    assert resultados[0]["content"] != ""


def test_vpn_macos(search):
    resultados = buscar_artigos(
        "Como configurar a VPN no macOS?",
        artigos, service=search,
    )

    assert resultados
    assert resultados[0]["id"] == 2
    assert resultados[0]["title"] == "Configurar a VPN corporativa no macOS"
    assert resultados[0]["content"] != ""


def test_pergunta_sem_resposta(search):
    resultados = buscar_artigos(
        "Como configurar uma cafeteira?",
        artigos, service=search,
    )

    assert resultados == []


if __name__ == "__main__":
    for question in ("Como configurar a VPN no Windows?", "Como configurar a VPN no macOS?"):
        print(buscar_artigos(question, artigos))
