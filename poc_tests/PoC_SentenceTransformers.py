import html
import os
import re
import sys

from sentence_transformers import SentenceTransformer

# Permite reutilizar a autenticação e o cliente GLPI já existentes.
agent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Agent"))
sys.path.append(agent_path)

from GLPI_Client import GLPIClient
from auth import fazer_login

CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"

QUESTION = "Como redefino minha senha?"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
ARTICLE_LIMIT = 40
CHUNK_SIZE = 120
CHUNK_OVERLAP = 30
TOP_K = 3


def clean_html(text):
    """Remove HTML e espaços excedentes do conteúdo retornado pelo GLPI."""
    text_without_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text_without_tags)).strip()


def create_chunks(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Cria chunks por palavras, mantendo contexto entre blocos consecutivos."""
    words = text.split()
    if not words:
        return []

    step = chunk_size - overlap
    if step <= 0:
        raise ValueError("CHUNK_SIZE deve ser maior que CHUNK_OVERLAP.")

    return [
        " ".join(words[start : start + chunk_size])
        for start in range(0, len(words), step)
    ]


def get_top_semantic_articles(article_texts):
    """Busca semanticamente nos chunks e mantém o melhor score de cada artigo."""
    chunks = []
    chunk_article_indexes = []

    for article_index, article_text in enumerate(article_texts):
        for chunk in create_chunks(article_text):
            chunks.append(chunk)
            chunk_article_indexes.append(article_index)

    if not chunks:
        raise RuntimeError("Não foi possível criar chunks a partir dos artigos.")

    model = SentenceTransformer(MODEL_NAME)
    embeddings = model.encode(
        [QUESTION, *chunks],
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    # Embeddings normalizados: produto escalar equivale à similaridade do cosseno.
    semantic_scores = embeddings[1:] @ embeddings[0]
    best_score_by_article = {}

    for score, chunk, article_index in zip(
        semantic_scores, chunks, chunk_article_indexes
    ):
        current_result = best_score_by_article.get(article_index)
        if current_result is None or score > current_result[0]:
            best_score_by_article[article_index] = (float(score), chunk)

    ranking = sorted(
        best_score_by_article.items(), key=lambda result: result[1][0], reverse=True
    )[:TOP_K]
    return ranking, len(chunks)


def main():
    access_token = fazer_login(CLIENT_ID, CLIENT_SECRET)["access_token"]
    client = GLPIClient(access_token)

    # O método do cliente pode paginar além do limite; o slice mantém o teste
    # estritamente nos cinco primeiros artigos, como definido para esta PoC.
    articles = client.all_call_search(
        "/Knowledgebase/Article", limit=ARTICLE_LIMIT
    )

    article_pairs = [
        (article, clean_html(article.get("content", "")))
        for article in articles
        if clean_html(article.get("content", ""))
    ]
    if not article_pairs:
        raise RuntimeError("Nenhum dos cinco artigos possui conteúdo indexável.")

    valid_articles, article_texts = map(list, zip(*article_pairs))
    semantic_ranking, chunk_count = get_top_semantic_articles(article_texts)

    print(f"Artigos analisados: {len(valid_articles)}")
    print(f"Chunks semânticos gerados: {chunk_count}")
    print(f"Pergunta: {QUESTION}")

    print("\nRanking semântico (Sentence Transformers + chunks)")
    for position, (article_index, (score, best_chunk)) in enumerate(
        semantic_ranking, start=1
    ):
        article_name = valid_articles[article_index].get("name", "Artigo sem título")
        
        print(f"{position} -- {article_name} -- {score:.3f}")
        print(f"     Trecho mais semelhante: {best_chunk}")


if __name__ == "__main__":
    main()
