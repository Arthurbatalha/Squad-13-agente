"""Testes da recuperação semântica sem chamada real a modelo/API."""

try:
    from .recuperacao_artigos import RecuperadorArtigos, criar_chunks_texto, remover_html
except ImportError:
    from recuperacao_artigos import RecuperadorArtigos, criar_chunks_texto, remover_html


ARTIGOS = [
    {
        "id": 1,
        "name": "Configurar a VPN corporativa no Windows",
        "content": (
            "<p>No Windows 10 e 11, abra Configurações, Rede e Internet.</p>"
            "<p>Entre em VPN e adicione a conexão corporativa.</p>"
        ),
    },
    {
        "id": 2,
        "name": "Configurar a VPN corporativa no macOS",
        "content": (
            "<p>No macOS, abra Ajustes do Sistema e depois Rede.</p>"
            "<p>Adicione uma configuração IKEv2.</p>"
        ),
    },
    {
        "id": 3,
        "name": "Instalar impressora de rede",
        "content": "<p>Conecte-se ao servidor de impressão e selecione a fila do seu andar.</p>",
    },
]


class EmbedderFalso:
    """Vetores previsíveis para testar ranking, threshold e ambiguidade."""

    @staticmethod
    def _vetor(texto: str):
        texto = texto.lower()

        # Perguntas usadas pelos testes.
        if "home office" in texto or "férias" in texto or "ferias" in texto:
            return [0.0, 0.0, 0.0, 1.0]
        if "vpn" in texto and "windows" in texto and "título:" not in texto:
            return [1.0, 0.0, 0.0, 0.0]
        if "vpn" in texto and "macos" in texto and "título:" not in texto:
            return [0.0, 1.0, 0.0, 0.0]
        if texto.strip() == "como configuro a vpn?":
            return [0.71, 0.70, 0.0, 0.0]
        if "impressora" in texto and "título:" not in texto:
            return [0.0, 0.0, 1.0, 0.0]

        # Chunks indexados: o título está incluído no texto_para_embedding.
        if "título:" in texto and "vpn" in texto and "windows" in texto:
            return [1.0, 0.05, 0.0, 0.0]
        if "título:" in texto and "vpn" in texto and "macos" in texto:
            return [0.05, 1.0, 0.0, 0.0]
        if "título:" in texto and "impressora" in texto:
            return [0.0, 0.0, 1.0, 0.0]

        return [0.0, 0.0, 0.0, 0.0]

    def encode(self, textos):
        return [self._vetor(texto) for texto in textos]


def criar_recuperador():
    return RecuperadorArtigos(
        artigos=ARTIGOS,
        embedder=EmbedderFalso(),
        tamanho_max_palavras=30,
        sobreposicao_palavras=5,
    )


def test_remove_html_sem_perder_texto():
    texto = remover_html("<p>Abra <strong>Configurações</strong>.</p><p>Depois VPN.</p>")
    assert "Configurações" in texto
    assert "Depois VPN" in texto
    assert "<p>" not in texto


def test_chunking_respeita_limite_e_cria_mais_de_um_chunk():
    texto = " ".join(f"palavra{i}." for i in range(40))
    chunks = criar_chunks_texto(texto, tamanho_max_palavras=12, sobreposicao_palavras=3)

    assert len(chunks) > 1
    assert all(len(chunk.split()) <= 15 for chunk in chunks)


def test_busca_retorna_windows_em_primeiro():
    recuperador = criar_recuperador()
    resultado = recuperador.buscar(
        "Como configurar a VPN no Windows?",
        top_n=3,
        threshold=0.40,
    )

    assert resultado["status"] == "ok"
    assert resultado["deve_recusar"] is False
    assert resultado["resultados"]
    assert resultado["resultados"][0]["artigo_id"] == 1


def test_busca_respeita_top_n():
    recuperador = criar_recuperador()
    resultado = recuperador.buscar(
        "Como configuro a VPN?",
        top_n=1,
        threshold=0.40,
    )

    assert resultado["status"] == "ok"
    assert len(resultado["resultados"]) == 1


def test_pergunta_fora_da_base_dispara_recusa_honesta():
    recuperador = criar_recuperador()
    resultado = recuperador.buscar(
        "Qual é a política de home office?",
        top_n=5,
        threshold=0.40,
    )

    assert resultado["status"] == "sem_contexto"
    assert resultado["deve_recusar"] is True
    assert resultado["resultados"] == []
    assert "Não encontrei informação suficiente" in resultado["mensagem"]


def test_threshold_realmente_filtra_resultados():
    recuperador = criar_recuperador()

    baixo = recuperador.buscar(
        "Como configuro a VPN?",
        top_n=5,
        threshold=0.40,
    )
    alto = recuperador.buscar(
        "Como configuro a VPN?",
        top_n=5,
        threshold=0.9999,
    )

    assert baixo["status"] == "ok"
    assert alto["status"] == "sem_contexto"
    assert alto["deve_recusar"] is True


def test_busca_ambigua_sinaliza_empate_entre_artigos():
    recuperador = criar_recuperador()
    resultado = recuperador.buscar(
        "Como configuro a VPN?",
        top_n=5,
        threshold=0.40,
        margem_ambiguidade=0.05,
    )

    ids = {item["artigo_id"] for item in resultado["resultados"][:2]}
    assert ids == {1, 2}
    assert resultado["ambiguo"] is True


def test_fonte_sempre_tem_id_titulo_e_conteudo():
    recuperador = criar_recuperador()
    resultado = recuperador.buscar(
        "Como instalar uma impressora?",
        top_n=2,
        threshold=0.40,
    )

    assert resultado["status"] == "ok"
    fonte = resultado["resultados"][0]
    assert fonte["artigo_id"] == 3
    assert fonte["titulo"]
    assert fonte["conteudo"]
    assert 0.0 <= fonte["similaridade"] <= 1.0
