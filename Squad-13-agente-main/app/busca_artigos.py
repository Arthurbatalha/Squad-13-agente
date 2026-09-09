import html
import re
from typing import Any, Iterable

PALAVRAS_IGNORADAS = {
    "a", "o", "as", "os",
    "um", "uma",
    "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas",
    "para", "por",
    "e",
    "como",
    "que",
    "qual",
    "quais",
    "me",
    "se",
}


def remover_html(texto: Any) -> str:
    """Converte o conteúdo HTML do artigo do GLPI para texto simples."""
    if texto is None:
        return ""

    texto = str(texto)
    texto = re.sub(r"<\s*br\s*/?\s*>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"</\s*(p|li|h[1-6]|div|ol|ul)\s*>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = html.unescape(texto)

    # Evita espaços/quebras excessivos depois da remoção das tags.
    linhas = [re.sub(r"\s+", " ", linha).strip() for linha in texto.splitlines()]
    return "\n".join(linha for linha in linhas if linha)


def limpar_texto(texto: Any) -> list[str]:
    if texto is None:
        return []

    palavras = re.findall(r"\b\w+\b", str(texto).lower(), flags=re.UNICODE)

    return [
        palavra
        for palavra in palavras
        if palavra not in PALAVRAS_IGNORADAS
    ]


def buscar_artigos(pergunta: str, artigos: Iterable[dict[str, Any]], limite: int = 3):
    """Retorna os artigos mais relevantes para uma pergunta.

    Palavras encontradas no título valem 3 pontos e palavras encontradas
    somente no conteúdo valem 1 ponto. Apenas resultados com 4 ou mais
    pontos são retornados.
    """
    if limite <= 0:
        return []

    palavras = limpar_texto(pergunta)
    if not palavras:
        return []

    resultados = []

    for artigo in artigos or []:
        if not isinstance(artigo, dict):
            continue

        artigo_id = artigo.get("id")
        titulo = artigo.get("name", "")
        conteudo = remover_html(artigo.get("content", ""))

        # Ignora registros incompletos em vez de derrubar toda a busca.
        if artigo_id is None or not titulo:
            continue

        palavras_titulo = limpar_texto(titulo)
        palavras_conteudo = limpar_texto(conteudo)

        pontuacao = 0

        for palavra in palavras:
            if palavra in palavras_titulo:
                pontuacao += 3
            elif palavra in palavras_conteudo:
                pontuacao += 1

        if pontuacao >= 4:
            resultados.append({
                "id": artigo_id,
                "titulo": titulo,
                "conteudo": conteudo,
                "pontuacao": pontuacao,
            })

    resultados.sort(
        key=lambda resultado: resultado["pontuacao"],
        reverse=True,
    )

    return resultados[:limite]


if __name__ == "__main__":
    # Exemplo local para permitir executar este arquivo sem depender do GLPI.
    artigos_exemplo = [
        {
            "id": 1,
            "name": "Configurar a VPN corporativa no Windows",
            "content": "<p>Abra Configurações, Rede e Internet e depois VPN.</p>",
        },
        {
            "id": 2,
            "name": "Configurar a VPN corporativa no macOS",
            "content": "<p>Abra Ajustes do Sistema, Rede e adicione uma VPN IKEv2.</p>",
        },
    ]

    pergunta = "Estou usando Windows e preciso configurar a VPN, como faço?"
    resultados = buscar_artigos(pergunta, artigos_exemplo)

    if not resultados:
        print("Nenhum artigo relevante encontrado.")
    else:
        for resultado in resultados:
            print(
                f"ID: {resultado['id']} | "
                f"Pontuação: {resultado['pontuacao']} | "
                f"Título: {resultado['titulo']}"
            )
            print(f"Conteúdo: {resultado['conteudo']}")
