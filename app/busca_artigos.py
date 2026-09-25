from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class BuscadorArtigos:
    """
    Classe responsável por indexar artigos de conhecimento e realizar buscas
    por similaridade de texto usando a técnica TF-IDF.
    """

    def __init__(self, artigos):
        """
        Recebe a lista de artigos e constrói a matriz TF-IDF.
        Cada artigo deve ser um dicionário contendo ao menos 'titulo' e 'conteudo'.
        """
        self.artigos = artigos
        self.vectorizer = TfidfVectorizer(lowercase=True)

        # Junta título e conteúdo para formar o texto completo do artigo
        corpus = [f"{a.get('titulo', '')} {a.get('conteudo', '')}" for a in self.artigos]

        # Treina o vetorizador e cria a matriz TF-IDF da base
        self.matriz_tfidf = self.vectorizer.fit_transform(corpus)

    def buscar(self, query: str, top_k: int = 3) -> list:
        """
        Recebe uma consulta em texto e retorna os 'top_k' artigos mais relevantes.
        """
        if not query or not query.strip() or not self.artigos:
            return []

        # Converte a consulta do usuário para o vetor TF-IDF
        query_vector = self.vectorizer.transform([query])

        # Calcula a similaridade de cosseno entre a consulta e todos os artigos
        similaridades = cosine_similarity(query_vector, self.matriz_tfidf)[0]

        # Pega os índices dos artigos ordenados da maior para a menor similaridade
        indices_ordenados = similaridades.argsort()[::-1]

        resultados = []
        for idx in indices_ordenados[:top_k]:
            score = float(similaridades[idx])

            # Descarta artigos sem nenhuma relevância (score zero)
            if score > 0.0:
                artigo = self.artigos[idx].copy()
                artigo["score_relevancia"] = round(score, 4)
                resultados.append(artigo)

        return resultados