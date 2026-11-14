import html
import re
from typing import Any, Iterable
from src.rag.chunk_contract import MINILM_MODEL
from src.rag.corpus import PreparedCorpus, get_search_service, validate_query

MODEL = MINILM_MODEL


def remover_html(texto: Any) -> str:
    """Helper legado; a busca usa agora o preparador html2text da ING-01."""
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

def create_chunks(text, chunk_lenght=120, overlap=30):
    """Helper legado por palavras; não é usado para gerar embeddings da ING-02."""

    words = text.split()
    if not words:
        return []

    step = chunk_lenght - overlap

    if step <= 0:
        step = 1

    return [
        " ".join(words [i : i + chunk_lenght])
        for i in range(0, len(words), step)
    ]


def buscar_artigos(question: str, articles: Iterable[dict[str, Any]] | PreparedCorpus,
                   limit: int = 3, *, service=None):
    """Busca pública: prepara uma vez e codifica somente cada pergunta posterior.

    Uma instância compartilhada é usada por padrão. O chamador também pode
    injetar CorpusService ou passar um PreparedCorpus já gerado. Erros não são
    convertidos em corpus vazio; a publicação anterior sobrevive a uma falha.
    """
    if not validate_query(question, limit):
        return []
    search = service if service is not None else get_search_service()
    corpus = articles if isinstance(articles, PreparedCorpus) else search.prepare_articles(articles)
    return search.search(question, corpus=corpus, limit=limit)


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
                f"Pontuação: {resultado['score']:.3f} | "
                f"Título: {resultado['title']}"
            )
            print(f"Conteúdo: {resultado['content']}")
