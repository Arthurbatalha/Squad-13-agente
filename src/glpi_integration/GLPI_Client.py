from src.glpi_integration.auth import fazer_login, renovar_token
import requests
from dotenv import load_dotenv
import os
import logging

class GLPIClient:

    def __init__(self, base_url, access_token, refresh_token, client_id, client_secret):
        self.token = access_token
        self.base_url = base_url
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret

    #Metodo para a criação de cabeçalhos
    def create_header(self, method):

        header = {
            "Authorization": f"Bearer {self.token}",
            "Connection": "close"
        }

        if method != 'GET':
            header['Content-type'] = 'application/json'

        return header

    #Motor para requests com verificação de validade de token 
    def _secure_request(self, method, url, **kwargs):

        kwargs["headers"] = self.create_header(method)
        kwargs["timeout"] = 10

        response = requests.request(method, url, **kwargs)

        if response.status_code == 401:
            logging.info("Token Expirado. Auto refreshing em ação...")

            new_data = renovar_token(self.client_id, self.client_secret, self.refresh_token)

            self.token = new_data["access_token"]
            self.refresh_token = new_data["refresh_token"]

            kwargs["headers"] = self.create_header(method)

            response = requests.request(method, url, **kwargs)

        response.raise_for_status()
        return response

    #Metodo para a coleta de dados de um endpoit
    def search_all(self, endpoint, start=0, limit=25):
        all_calls = []

        while True:

            try:
                response = self._secure_request(
                    "GET",
                    f"{self.base_url}{endpoint}",
                    params={"start": start, "limit": limit}
                )

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
            response = self._secure_request(
                "PATCH",
                url,
                json=data
            )
        
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

            response = self._secure_request(
                "POST",
                url,
                json={"content": text}
            )

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

            response = self._secure_request(
                "POST",
                url,
                json={"content": text}
            )

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

            response = self._secure_request("GET", url)

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

            response = self._secure_request(
                "POST",
                url,
                json={
                    "name": title,
                    "content": content,
                    "priority": priority,
                    "category": {"id": category_id}    
                }
            )

            if not response.text.strip():
                raise requests.exceptions.RequestException("Resposta do GLPI vazia, ID do ticket não recebido")

            ticket_id = response.json().get("id")

            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise requests.exceptions.RequestException("GLPI não retornou id válido") 

            return response.json()
        
        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao criar ticket. Detalhes: {e}")
            raise ConnectionError(f"Erro na criação de ticket: {e}")

    #Método para atribuir um membro a um chamado
    def assign_member(self, ticket_id, user_id, role="assigned"):

        url = f"{self.base_url}/Assistance/Ticket/{ticket_id}/TeamMember"

        try:

            response = self._secure_request(
                "POST",
                url,
                json={
                    "type": "User",
                    "id": user_id,
                    "role": role
                }
            )

            if response.text.strip():
                return response.json()
            return {}

        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao atribuir membro ao ticket. Detalhes: {e}")
            raise ConnectionError(f"Erro na atribuição de membro: {e}") from e

    #Abre o ticket atribuindo o requester
    def open_ticket(
        self, title,
        content, category_id, 
        user_id, priority=3
        ):

        ticket = self.add_ticket(title, content, category_id, priority)
        ticket_id = ticket["id"]

        try:

            self.assign_member(
                ticket_id,
                user_id,
                role="requester"
            )

        except Exception as e:
            logging.error(f"Falha ao adicionar requester no novo ticket [OBS: O ticket foi criado ID:{ticket_id}, mas o requester não foi confirmado]. Detalhes: {e}")
            raise RuntimeError(f"Erro na atribuição de requester do ticket {ticket_id}: {e}") from e

        else:
            return ticket
    
#Depuração e Edge Case
if __name__ == "__main__":
    
    load_dotenv()

    CLIENT_ID = os.getenv("GLPI_CLIENT_ID")
    CLIENT_SECRET = os.getenv("GLPI_CLIENT_SECRET")
    BASE_URL = os.getenv("GLPI_BASE_URL_V2")

    dados_login = fazer_login(CLIENT_ID, CLIENT_SECRET)

    client = GLPIClient(
        base_url=BASE_URL, 
        access_token=dados_login["access_token"],
        refresh_token=dados_login.get("refresh_token"), # Usamos .get() por segurança
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET
    )

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