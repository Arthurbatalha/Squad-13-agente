try:
    from .busca_artigos import buscar_artigos
    from .artigos_teste import artigos
except ImportError:
    # Permite executar o arquivo diretamente dentro da pasta app.
    from busca_artigos import buscar_artigos
    from artigos_teste import artigos


def testar_vpn_windows():
    resultados = buscar_artigos(
        "Como configurar a VPN no Windows?",
        artigos,
    )

    assert resultados
    assert resultados[0]["id"] == 1
    assert resultados[0]["titulo"] == "Configurar a VPN corporativa no Windows"
    assert resultados[0]["conteudo"] != ""


def testar_vpn_macos():
    resultados = buscar_artigos(
        "Como configurar a VPN no macOS?",
        artigos,
    )

    assert resultados
    assert resultados[0]["id"] == 2
    assert resultados[0]["titulo"] == "Configurar a VPN corporativa no macOS"
    assert resultados[0]["conteudo"] != ""


def testar_pergunta_sem_resposta():
    resultados = buscar_artigos(
        "Como configurar uma cafeteira?",
        artigos,
    )

    assert resultados == []


print("Todos os testes passaram com sucesso!")