import sys
import os
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# 1. Apontamos diretamente para a pasta Agent
agent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Agent'))
sys.path.append(agent_path)

# 2. Como a pasta Agent agora é a base, importamos os arquivos diretamente!
from GLPI_Client import GLPIClient
from auth import fazer_login

CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"

auth = fazer_login(CLIENT_ID, CLIENT_SECRET)["access_token"]
client = GLPIClient(auth)
articles = client.all_call_search("/Knowledgebase/Article", limit=5)

# 3. Limpeza do HTML
def remove_html(text):
    return re.sub(r"<[^>]+>", " ", text)

clean_texts = [remove_html(article["content"]) for article in articles]

# 4. Inicializando e treinando o motor de busca lexical
vectorizer = TfidfVectorizer()
matriz_tfidf = vectorizer.fit_transform(clean_texts)
question_vet = vectorizer.transform(["A rede da empresa fica desconectando sozinha"])
response = cosine_similarity(question_vet, matriz_tfidf)[0]
response_top3 = response.argsort()[-1:-4:-1]

print(f"Matriz matemática gerada com sucesso! Formato: {matriz_tfidf.shape}")

for i in range(len(response_top3)):
    print(f"{i+1} -- {articles[response_top3[i]]["name"]} -- {response[response_top3[i]]:.3f}")