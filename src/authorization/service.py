"""Serviço único de autorização para tools, API do front e retornos ao modelo.

Ordem de cada operação: ferramenta permitida -> recurso autorizado -> projeção
-> (só então) cálculo ou envio. Nada é guardado em cache: cada chamada lê o
estado atual do GLPI, então revogações valem na chamada seguinte.
"""

from collections import Counter

import requests

from src.glpi_integration.GLPI_Client import GLPICollection, GLPIProtocolError
from src.authorization import policies, projections
from src.authorization.policies import (
    AccessDenied, EmptyAuthorizedSet, Principal, ToolDenied,
)

TICKETS = "/Assistance/Ticket"
ARTICLES = "/Knowledgebase/Article"


def as_model_data(records, *, source: str) -> dict:
    """Envelope para o que vai ao Gemini: dado não confiável, nunca instrução.

    Conjunto vazio é negado em vez de enviado.
    """
    if not records:
        raise EmptyAuthorizedSet()
    return {"trust": "untrusted_data", "source": source, "records": list(records)}


class AuthorizationService:
    def __init__(self, glpi, *, disabled_tools=frozenset()):
        self._glpi = glpi
        self._disabled = frozenset(disabled_tools)

    def authorize_tool(self, principal, tool) -> None:
        if not policies.tool_allowed(principal, tool, self._disabled):
            raise ToolDenied()

    def ranking_global(self, principal):
        """Bloqueada para todos os papéis."""
        self.authorize_tool(principal, "ranking_global")

    # --- leituras autorizadas ------------------------------------------------

    def _collection(self, endpoint):
        items = self._glpi.search_all(endpoint)
        if not isinstance(items, GLPICollection) or items.complete is not True:
            raise GLPIProtocolError(f"Coleção incompleta em {endpoint}.")
        return items

    def _authorized(self, principal):
        """Filtra antes de qualquer cálculo, projeção ou envio."""
        return [t for t in self._collection(TICKETS) if isinstance(t.get("id"), int) and policies.can_read_original(principal, t)]

    def _timeline(self, ticket_id):
        return self._collection(f"{TICKETS}/{ticket_id}/Timeline")

    def get_ticket(self, principal, ticket_id) -> dict:
        self.authorize_tool(principal, "get_ticket")
        if type(ticket_id) is not int or ticket_id <= 0:
            raise AccessDenied()
        try:
            ticket = self._glpi.get_by_id(TICKETS, ticket_id)
        except requests.HTTPError as error:
            if getattr(error.response, "status_code", None) == 404:
                raise AccessDenied() from None
            raise
        if ticket.get("id") != ticket_id or not policies.can_read_original(principal, ticket):
            raise AccessDenied()
        return projections.project_original(principal, ticket, self._timeline(ticket_id))

    def list_tickets(self, principal) -> list:
        self.authorize_tool(principal, "list_tickets")
        tickets = self._authorized(principal)
        if not tickets:
            raise EmptyAuthorizedSet()
        return [projections.project_summary(t) for t in tickets]

    def ticket_statistics(self, principal) -> dict:
        """Cliente: só os próprios chamados. Staff: todos fora da lixeira."""
        self.authorize_tool(principal, "ticket_statistics")
        tickets = self._authorized(principal)
        if not tickets:
            raise EmptyAuthorizedSet()
        names = lambda field: dict(Counter(projections.name_of(t.get(field)) for t in tickets))
        return {
            "scope": "global" if principal.role == "staff" else "own",
            "total": len(tickets),
            "by_status": names("status"),
            "by_category": names("category"),
        }

    def similar_cases(self, principal) -> list:
        """Casos técnicos preparados (com solução pública).

        Mesma fronteira dos originais: cliente só a partir dos próprios chamados;
        o histórico de outras pessoas é exclusivo do staff.
        """
        self.authorize_tool(principal, "similar_cases")
        cases = []
        for ticket in self._authorized(principal):
            if not (ticket.get("date_solve") or ticket.get("date_close")):
                continue  # evita ler a timeline de chamados ainda sem solução
            case = projections.project_case(ticket, self._timeline(ticket["id"]))
            if case:
                cases.append(case)
        if not cases:
            raise EmptyAuthorizedSet()
        return cases

    def list_articles(self, principal) -> list:
        """Artigos são base técnica compartilhada por qualquer sessão válida.

        `is_faq` não é critério de autorização (regra da demonstração).
        """
        self.authorize_tool(principal, "search_articles")
        articles = [a for a in map(projections.project_article, self._collection(ARTICLES)) if a]
        if not articles:
            raise EmptyAuthorizedSet()
        return articles
