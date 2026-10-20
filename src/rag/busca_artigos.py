import html
import re
from typing import Any, Iterable
from sentence_transformers import SentenceTransformer

MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
model_embbendings = SentenceTransformer(MODEL)


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

def create_chunks(text, chunk_lenght=120, overlap=30):

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


def buscar_artigos(question: str, articles: Iterable[dict[str, Any]], limit: int = 3):

    if limit < 0 or not question:
        return []

    articles_list = list(articles or [])

    chunks = []
    chunk_article_indexes = []

    for article_index, article in enumerate(articles_list):
        title = article.get("name", "")
        content = remover_html(article.get("content", ""))

        full_text = f"{title}. {content}"

        for chunk in create_chunks(full_text):
            chunks.append(chunk)
            chunk_article_indexes.append(article_index)

    if not chunks:
        return[]

    codyfying_texts = [question, *chunks]

    embbedings = model_embbendings.encode(
        codyfying_texts,
        normalize_embeddings=True,
        show_progress_bar=True
    )

    semantic_scores = embbedings[1:] @ embbedings[0]

    top_articles = {}
    for score, article_indx in zip(semantic_scores, chunk_article_indexes):
        float_score = float(score)
        if article_indx not in top_articles or float_score > top_articles[article_indx]:
            top_articles[article_indx] = float_score

    MIN_SIMILARITY = 0.45
    res = []

    for article_indx, max_score in top_articles.items():
        if max_score >= MIN_SIMILARITY:
            original_article = articles_list[article_indx]
            res.append({
                "id":original_article.get("id"),
                "title": original_article.get("name", ""),
                "content": remover_html(original_article.get("content", "")),
                "score": max_score

            })

    res.sort(key=lambda x: x["score"], reverse=True)
    return res[:limit]


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
                f"Pontuação: {resultado['score']} | "
                f"Título: {resultado['title']}"
            )
            print(f"Conteúdo: {resultado['content']}")
