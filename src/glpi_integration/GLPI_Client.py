import sys
from pathlib import Path
import re

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
if str(RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROJETO))

from src.glpi_integration.auth import (
    REQUEST_TIMEOUT_SECONDS,
    GLPIAuthenticationError,
    GLPIProtocolError,
    fazer_login,
    renovar_token,
)
import requests
from src.config import load_settings
import logging

class TicketRequesterAssignError(RuntimeError):
    def __init__(self, ticket_id, message, *, outcome_uncertain=False):
        self.ticket_id = ticket_id
        self.outcome_uncertain = outcome_uncertain
        super().__init__(message)


class GLPIWriteOutcomeUnknownError(ConnectionError):
    """A write may have reached GLPI; check remote state before retrying."""


class GLPICollection(list):
    """A complete paginated collection, retaining list compatibility."""

    def __init__(self, endpoint, items, total, pages):
        super().__init__(items)
        self.endpoint = endpoint
        self.total = total
        self.pages = pages
        self.complete = True


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

    def _send_request(self, method, url, kwargs):
        try:
            return requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                raise GLPIWriteOutcomeUnknownError(
                    "A conexão falhou durante uma escrita; o resultado no GLPI é incerto. "
                    "Verifique o estado remoto antes de tentar novamente."
                ) from exc
            raise ConnectionError("Não foi possível comunicar com o servidor do GLPI.") from exc

    def _secure_request(self, method, url, **kwargs):
        """Renew once after 401; never retry transport failures automatically."""
        kwargs["headers"] = self.create_header(method)
        kwargs["timeout"] = REQUEST_TIMEOUT_SECONDS
        response = self._send_request(method, url, kwargs)

        if response.status_code != 401:
            response.raise_for_status()
            return response

        logging.info("GLPI rejeitou o access token; tentando uma renovação.")
        if not self.refresh_token:
            raise GLPIAuthenticationError("Refresh token ausente; sessão não renovada.")

        new_data = renovar_token(self.client_id, self.client_secret, self.refresh_token)
        if not isinstance(new_data, dict):
            raise GLPIProtocolError("Resposta de renovação do GLPI inválida.")

        access_token = new_data.get("access_token")
        refresh_token = new_data.get("refresh_token", self.refresh_token)
        if not isinstance(access_token, str) or not access_token.strip():
            raise GLPIProtocolError("Resposta de renovação sem access_token válido.")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise GLPIProtocolError("Resposta de renovação sem refresh_token válido.")

        self.token = access_token
        self.refresh_token = refresh_token
        kwargs["headers"] = self.create_header(method)
        response = self._send_request(method, url, kwargs)

        if response.status_code == 401:
            raise GLPIAuthenticationError(
                "GLPI rejeitou a requisição após a renovação; nenhuma nova tentativa foi feita."
            )

        response.raise_for_status()
        return response

    @staticmethod
    def _decode_collection(response, endpoint):
        try:
            items = response.json()
        except ValueError as exc:
            raise GLPIProtocolError(
                f"Resposta JSON inválida ao listar {endpoint}."
            ) from exc

        if not isinstance(items, list):
            raise GLPIProtocolError(
                f"Resposta inválida ao listar {endpoint}: era esperada uma lista."
            )
        if any(not isinstance(item, dict) for item in items):
            raise GLPIProtocolError(
                f"Resposta inválida ao listar {endpoint}: item não é um objeto."
            )
        return items

    @staticmethod
    def _content_range(response, endpoint, requested_start, item_count):
        content_range = response.headers.get("Content-Range")
        match = re.fullmatch(r"(\d+)-(\d+)/(\d+)", content_range or "")
        if not match:
            raise GLPIProtocolError(
                f"Resposta parcial de {endpoint} sem Content-Range válido."
            )

        range_start, range_end, total = map(int, match.groups())
        if (
            range_start != requested_start
            or range_end < range_start
            or range_end >= total
            or range_end - range_start + 1 != item_count
        ):
            raise GLPIProtocolError(
                f"Content-Range inconsistente ao listar {endpoint}."
            )
        return range_end, total

    # Método para a coleta de todos os dados de um endpoint
    def search_all(self, endpoint, start=0, limit=25):
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise ValueError("start deve ser um inteiro não negativo.")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit deve ser um inteiro positivo.")

        items = []
        seen_ids = set()
        pages = 0
        expected_total = None
        initial_start = start

        while True:
            response = self._secure_request(
                "GET",
                f"{self.base_url}{endpoint}",
                params={"start": start, "limit": limit},
            )
            pages += 1
            if response.status_code not in (200, 206):
                raise GLPIProtocolError(
                    f"Status HTTP inesperado ao listar {endpoint}: "
                    f"{response.status_code}."
                )

            page = self._decode_collection(response, endpoint)
            if response.status_code == 200:
                content_range = response.headers.get("Content-Range")
                if content_range:
                    range_end, total = self._content_range(
                        response, endpoint, start, len(page)
                    )
                    if range_end + 1 != total:
                        raise GLPIProtocolError(
                            f"Resposta HTTP 200 incompleta ao listar {endpoint}."
                        )
                    if expected_total is not None and expected_total != total:
                        raise GLPIProtocolError(
                            f"Total de registros mudou durante a leitura de {endpoint}."
                        )
                    expected_total = total
            else:
                if not page:
                    raise GLPIProtocolError(
                        f"Página HTTP 206 vazia ao listar {endpoint}; "
                        "não é possível confirmar a completude."
                    )
                if len(page) > limit:
                    raise GLPIProtocolError(
                        f"Página maior que o limite solicitado ao listar {endpoint}."
                    )
                range_end, total = self._content_range(
                    response, endpoint, start, len(page)
                )
                if expected_total is not None and expected_total != total:
                    raise GLPIProtocolError(
                        f"Total de registros mudou durante a leitura de {endpoint}."
                    )
                expected_total = total

            for item in page:
                item_id = item.get("id")
                if isinstance(item_id, (str, int)) and not isinstance(item_id, bool):
                    normalized_id = str(item_id)
                    if normalized_id in seen_ids:
                        raise GLPIProtocolError(
                            f"Registro duplicado na paginação de {endpoint}."
                        )
                    seen_ids.add(normalized_id)

            items.extend(page)

            if response.status_code == 200:
                total = expected_total if expected_total is not None else len(items)
                if total != initial_start + len(items):
                    raise GLPIProtocolError(
                        f"Quantidade recebida não corresponde ao total de {endpoint}."
                    )
                return GLPICollection(endpoint, items, total, pages)

            if range_end + 1 == expected_total:
                return GLPICollection(endpoint, items, expected_total, pages)
            start = range_end + 1

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

    # Método para coletar dados de id específico
    def get_by_id(self, endpoint, item_id):

        url = f"{self.base_url}{endpoint}/{item_id}"

        response = self._secure_request("GET", url)
        if response.status_code != 200:
            raise GLPIProtocolError(
                f"Status HTTP inesperado ao consultar {endpoint}/{item_id}: "
                f"{response.status_code}."
            )

        try:
            item = response.json()
        except ValueError as exc:
            raise GLPIProtocolError(
                f"Resposta JSON inválida ao consultar {endpoint}/{item_id}."
            ) from exc
        if not isinstance(item, dict) or not item:
            raise GLPIProtocolError(
                f"Resposta inválida ao consultar {endpoint}/{item_id}: "
                "era esperado um objeto."
            )
        return item

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

        except GLPIWriteOutcomeUnknownError as e:
            logging.error(
                "A atribuição de requester do ticket %s tem resultado incerto.",
                ticket_id,
            )
            raise TicketRequesterAssignError(
                ticket_id,
                "Resultado incerto ao atribuir requester; verifique o GLPI antes de repetir.",
                outcome_uncertain=True,
            ) from e
        except Exception as e:
            logging.error(f"Falha ao adicionar requester no novo ticket [OBS: O ticket foi criado ID:{ticket_id}, mas o requester não foi confirmado]. Detalhes: {e}")
            raise TicketRequesterAssignError(ticket_id ,f"Erro na atribuição de requester do ticket {ticket_id}: {e}") from e

        else:
            return ticket
    
#Depuração e Edge Case
if __name__ == "__main__":
    
    settings = load_settings(require_glpi=True)
    CLIENT_ID = settings.glpi_client_id
    CLIENT_SECRET = settings.glpi_client_secret
    BASE_URL = settings.glpi_base_url_v2

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