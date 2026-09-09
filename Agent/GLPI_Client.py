from auth import fazer_login
import requests

client_id = '92e1a8497a5136e410301a573b8282bb'
client_secret = '156df3c0f488cd8be63a5ee3731568da3afa60239bed1018c8cec9f4c5355c17'

'''dados = (fazer_login(client_id, client_secret ))
for k, v in dados.items():
    print(f'{k}:\n\t{v}')'''

class GLPIClient:
    def __init__(self,access_token):
        self.token = access_token

    #Metodo para a criação de cabeçalhos
    def create_header(self, method):

        header = {
            "Authorization": f"Bearer {self.token}",
            "Connection": "close"
        }

        if method != 'GET':
            header['Content-type'] = 'application/json'

        return header

    #Metodo para a coleta de chamados
    def all_call_search(self, endpoint, start=0, limit=25):
        all_calls = []

        while True:

            response = requests.get(
                f'http://localhost:8080/api.php/v2{endpoint}',
                headers = self.create_header('GET'),
                params={
                    "start": start,
                    "limit": limit
                }
                )

            if 199 < response.status_code < 300:
                pass
            else:
              print("STATUS:", response.status_code)
              print("RESPOSTA:", response.text)
              raise Exception("Erro de paginação, algo deu errado")

            calls_frag = response.json()

            all_calls.extend(calls_frag)

            if len(calls_frag) == limit:
                start += limit

            if len(calls_frag) < limit:
                break

        return all_calls

    pass

#Depuração e Edge Case
if __name__ == "__main__":

    client = GLPIClient(access_token=fazer_login(client_id, client_secret)["access_token"])
    artigos = client.all_call_search(
    "/Knowledgebase/Article",
    limit=25
)

    print(f"total de artigos: {len(artigos)}")

    for artigo in artigos:
        print(
            f"ID: {artigo['id']} | "
            f"Título: {artigo['name']}"
        )
