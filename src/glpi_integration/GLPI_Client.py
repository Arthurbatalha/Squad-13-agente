from src.glpi_integration.auth import fazer_login
import requests
from dotenv import load_dotenv
import os
import logging

class GLPIClient:

    def __init__(self, base_url,access_token):
        self.token = access_token
        self.base_url = base_url

    #Metodo para a criação de cabeçalhos
    def create_header(self, method):

        header = {
            "Authorization": f"Bearer {self.token}",
            "Connection": "close"
        }

        if method != 'GET':
            header['Content-type'] = 'application/json'

        return header

    #Metodo para a coleta de dados de um endpoit
    def search_all(self, endpoint, start=0, limit=25):
        all_calls = []

        while True:

            try:
                response = requests.get(
                    f'{self.base_url}{endpoint}',
                    headers = self.create_header('GET'),
                    params={
                        "start": start,
                        "limit": limit
                    },
                    timeout=10
                    )


                if not (200 <= response.status_code < 300):
                    logging.error(f"Erro na busca ({response.status_code}): {response.text}")
                    response.raise_for_status()

            except requests.exceptions.RequestException as e:
                logging.error(f"Falha de comunicação no search_all: {e}")
                raise ConnectionError(f"Erro ao buscar dados no GLPI: {e}")
            
            calls_frag = response.json()

            all_calls.extend(calls_frag)

            if len(calls_frag) == limit:
                start += limit

            if len(calls_frag) < limit or response.status_code == 200:
                break

        return all_calls

    #Método para atualizar informações de um ticket
    def update_ticket(self, ticket_id, data):

        url = f"{self.base_url}/Assistance/Ticket/{ticket_id}"

        try:
            response = requests.patch(
                url,
                json=data,
                headers=self.create_header("PATCH"),
                timeout=10
            )
            response.raise_for_status()
        
            if response.text.strip():
                return response.json()
            return {"id": ticket_id, "status": "atualizado_com_sucesso"}

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao atualizar o ticket {ticket_id}: {e}")
            raise ConnectionError(f"Não foi possível atualizar o ticket no GLPI: {e}")
        
    #Método para adicionar uma solução ao ticket
    def add_solution(self, ticket_id, text):

        url = f"{self.base_url}/Assistance/Ticket/{ticket_id}/Timeline/Solution"
        try:

            response = requests.post(
                url,
                headers=self.create_header("POST"),
                json={"content": text},
                timeout=10
            )
            response.raise_for_status()

            if response.text.strip():
                return response.json()
            return {"ticket_id": ticket_id, "status": "solucao_adicionada"}

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao adicionar a solução: {e}")
            raise ConnectionError(f"Erro ao criar solução: {e}")

    #Método para adicionar um FollowUp ao ticket
    def add_follow_up(self, ticket_id, text):

        url = f"{self.base_url}/Assistance/Ticket/{ticket_id}/Timeline/Followup"

        try:

            response = requests.post(
                url,
                headers=self.create_header("POST"),
                json={"content": text},
                timeout=10
            )
            response.raise_for_status()

            if response.text.strip():
                return response.json()
            return {"ticket_id": ticket_id, "status": "followup_adicionado"}

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha em adicionar FollowUp ao ticket: {e}")
            raise ConnectionError(f"Erro ao adicionar FollowUp: {e}")

    #Método para coletar dados de id específico
    def get_by_id(self, endpoint, item_id):

        url = f"{self.base_url}{endpoint}/{item_id}"

        try:

            response = requests.get(
                url,
                headers=self.create_header('GET'),
                timeout=10
            )

            response.raise_for_status()

            if response.text.strip():
                return response.json()
            return {}

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha na pesquisa por item. Detalhes: {e}")
            raise ConnectionError(f"Erro, falha ao encontrar id. {e}")

    #Método para adicionar ticket
    def add_ticket(self, title, content, category_id, priority=3):

        url = f"{self.base_url}/Assistance/Ticket"

        try:

            response = requests.post(
                url,
                headers=self.create_header("POST"),
                json={
                    "name": title,
                    "content": content,
                    "priority": priority,
                    "category": {"id": category_id}    
                },
                timeout=10,
            )

            response.raise_for_status()

            if response.text.strip():
                return response.json()
            return {
                "ticket_title": title,
                "category": category_id,
                "priority": priority
                }

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao criar ticket. Detalhes: {e}")
            raise ConnectionError(f"Erro na criação de ticket: {e}")

    #Método para atribuir um membro a um chamado
    def assign_member(self, ticket_id, user_id, role="assigned"):

        url = f"{self.base_url}/Assistance/Ticket/{ticket_id}/TeamMember"

        try:

            response = requests.post(
                url,
                headers=self.create_header("POST"),
                json={
                    "type": "User",
                    "id": user_id,
                    "role": role
                },
                timeout=10
            )
            response.raise_for_status()

            if response.text.strip():
                return response.json()
            return {}

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao atribuir membro ao ticket. Detalhes: {e}")
            raise ConnectionError(f"Erro na atribuição de membro: {e}")

        
#Depuração e Edge Case
if __name__ == "__main__":

    
    load_dotenv()

    CLIENT_ID = os.getenv("GLPI_CLIENT_ID")
    CLIENT_SECRET = os.getenv("GLPI_CLIENT_SECRET")
    BASE_URL = os.getenv("GLPI_BASE_URL_V2")

    client = GLPIClient(BASE_URL, access_token=fazer_login(CLIENT_ID, CLIENT_SECRET)["access_token"])
    artigos = client.search_all(
        "/Knowledgebase/Article",
        limit=25
    )

    print(f"total de artigos: {len(artigos)}")

    for artigo in artigos:
        print(
            f"ID: {artigo['id']} | "
            f"Título: {artigo['name']}"
        )