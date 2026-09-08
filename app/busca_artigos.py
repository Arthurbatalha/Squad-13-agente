import re

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
    "se"
}

def remover_html(texto):
    return re.sub(r"<[^>]+>", " ", texto)

def limpar_texto(texto):
    palavras = re.findall(r"\b\w+\b", texto.lower())

    palavras_filtradas = [
        palavra
        for palavra in palavras
        if palavra not in PALAVRAS_IGNORADAS
    ]

    return palavras_filtradas


def buscar_artigos(pergunta, artigos, limite=3):

    palavras = limpar_texto(pergunta)

    resultados = []

    for artigo in artigos:

        titulo = artigo["name"]
        conteudo = remover_html(artigo["content"])

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
              "id": artigo["id"],
              "titulo": artigo["name"],
              "conteudo": conteudo,
              "pontuacao": pontuacao
          })

    resultados.sort(
        key=lambda resultado: resultado["pontuacao"],
        reverse=True
    )

    return resultados[:limite]

if __name__ == "__main__":

    pergunta = "Estou usando Windows e preciso configurar a VPN, como faço?"

    resultados = buscar_artigos(pergunta, artigos)

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
