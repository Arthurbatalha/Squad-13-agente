import sys
import os
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Apontamos diretamente para a pasta Agent
agent_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Agent'))
sys.path.append(agent_path)

from GLPI_Client import GLPIClient # Não altere a menos que saiba o que vc está fazendo
from auth import fazer_login # Não altere a menos que saiba o que vc está fazendo

CLIENT_ID = "92e1a8497a5136e410301a573b8282bb"
CLIENT_SECRET = "156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17"

auth = fazer_login(CLIENT_ID, CLIENT_SECRET)["access_token"]
client = GLPIClient(auth)
articles = client.all_call_search("/Knowledgebase/Article", limit=5)

# Limpeza do HTML
def remove_html(text):
    return re.sub(r"<[^>]+>", " ", text)

# pode começar a partir daqui...