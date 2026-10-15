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


def testar_vpn_windows():
    resultados = buscar_artigos(
        "Como configurar a VPN no Windows?",
        artigos,
    )

    assert resultados
    assert resultados[0]["id"] == 1
    assert resultados[0]["title"] == "Configurar a VPN corporativa no Windows"
    assert resultados[0]["content"] != ""


def testar_vpn_macos():
    resultados = buscar_artigos(
        "Como configurar a VPN no macOS?",
        artigos,
    )

    assert resultados
    assert resultados[0]["id"] == 2
    assert resultados[0]["title"] == "Configurar a VPN corporativa no macOS"
    assert resultados[0]["content"] != ""


def testar_pergunta_sem_resposta():
    resultados = buscar_artigos(
        "Como configurar uma cafeteira?",
        artigos,
    )

    assert resultados == []


if __name__ == "__main__":
    testar_vpn_windows()
    testar_vpn_macos()
    testar_pergunta_sem_resposta()
    print("Todos os testes passaram com sucesso!")