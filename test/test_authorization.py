"""Políticas de acesso e projeção de dados, com GLPI simulado.

Usa test/fixtures/authorization/tickets.json (sintética, sem relação com o seed).
Usuários: 101=cliente A, 102=cliente B, 103=cliente C (sem chamados),
7 e 8=técnicos.
"""

import copy
import json
from pathlib import Path

import pytest
import requests

from src.glpi_integration.GLPI_Client import GLPICollection
from src.authorization import (
    AccessDenied, AuthorizationService, EmptyAuthorizedSet, Principal,
    ToolDenied, as_model_data,
)
from src.sessions import SessionService, SessionUnavailable

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "authorization" / "tickets.json").read_text(encoding="utf-8")
)

A, B, C = Principal.client(101), Principal.client(102), Principal.client(103)
TECH_7, TECH_8 = Principal.staff(7), Principal.staff(8)

PRIVATE_MARKERS = (
    "SENTINELA-PRIVADO", "SENTINELA-SEM-FLAG", "SENTINELA-TAREFA", "SENTINELA-LIXEIRA",
    "SENTINELA-ENTIDADE",
)


class FakeGLPI:
    """Mesma superfície de leitura do GLPIClient; registra cada chamada."""

    def __init__(self, data=None):
        self.data = copy.deepcopy(data or FIXTURE)
        self.calls = []

    def _ticket(self, ticket_id):
        for ticket in self.data["tickets"]:
            if str(ticket["id"]) == str(ticket_id):
                return ticket
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError("404", response=response)

    def get_by_id(self, endpoint, item_id):
        self.calls.append(("get_by_id", endpoint, item_id))
        assert endpoint == "/Assistance/Ticket"
        ticket = self._ticket(item_id)
        return {k: v for k, v in ticket.items() if k != "timeline"}

    def search_all(self, endpoint, start=0, limit=25):
        self.calls.append(("search_all", endpoint))
        if endpoint == "/Assistance/Ticket":
            rows = [{k: v for k, v in t.items() if k != "timeline"} for t in self.data["tickets"]]
        elif endpoint == "/Knowledgebase/Article":
            rows = self.data["articles"]
        elif endpoint.startswith("/Assistance/Ticket/") and endpoint.endswith("/Timeline"):
            rows = self._ticket(endpoint.split("/")[3])["timeline"]
        else:
            raise AssertionError(f"endpoint inesperado: {endpoint}")
        return GLPICollection(endpoint, copy.deepcopy(rows), len(rows), 1)


@pytest.fixture
def glpi():
    return FakeGLPI()


@pytest.fixture
def service(glpi):
    return AuthorizationService(glpi)


def dump(*values):
    return json.dumps(values, ensure_ascii=False, default=str)


# --- Identidade ------------------------------------------------------------

def test_principal_is_built_only_from_trusted_values():
    for role, user_id in (("admin", 1), ("client", True), ("staff", "7"), ("client", 0), ("staff", -3)):
        with pytest.raises(ValueError):
            Principal(role, user_id)
    with pytest.raises(AttributeError):
        A.role = "staff"


def test_staff_principal_comes_from_the_bound_session():
    users = GLPICollection("/Administration/User", [{"id": 42, "username": "ana.ribeiro"}], 1, 1)
    sessions = SessionService(lambda: users, integration_username="glpi")
    key, view = sessions.start(staff_user_id=42)
    assert Principal.from_session(sessions, key, view["thread_id"]) == Principal.staff(42)
    with pytest.raises(SessionUnavailable):
        Principal.from_session(sessions, key, "thread-de-outra-pessoa")


# --- Cliente: originais via team/requester ------------------------------------

def test_client_reads_own_original_with_whitelisted_projection(service):
    ticket = service.get_ticket(A, 1)
    assert ticket["id"] == 1 and ticket["title"] == "VPN cai (A)"
    assert ticket["status"] == "Fechado" and ticket["category"] == "rede"
    assert [f["content"] for f in ticket["followups"]] == ["PUBLICO-A: reiniciei o cliente."]
    assert ticket["solution"]["content"] == "SOLUCAO-A: atualizar o cliente VPN."
    assert set(ticket) <= {
        "id", "title", "content", "status", "category", "priority", "date",
        "date_solve", "date_close", "followups", "solution", "assigned_to",
    }
    assert ticket["assigned_to"] == ["ana.ribeiro"]
    assert "team" not in ticket and "entity" not in ticket and "user_recipient" not in ticket


@pytest.mark.parametrize("ticket_id", [2, 4, 3, 5, 6, 999, "2", 2.0, True, None, -1, 0])
def test_client_a_cannot_get_b_trashed_unrelated_or_missing_originals(service, ticket_id):
    with pytest.raises(AccessDenied) as denied:
        service.get_ticket(A, ticket_id)
    # Mesma resposta para inexistente e não autorizado: sem enumeração de IDs.
    assert str(denied.value) == "Recurso indisponível."


def test_denied_ticket_never_fetches_its_timeline(service, glpi):
    with pytest.raises(AccessDenied):
        service.get_ticket(A, 2)
    assert not any("Timeline" in str(call) for call in glpi.calls)


def test_requester_rule_needs_user_type_requester_role_and_exact_id(service):
    for ticket_id in (5, 6):  # 5: A é assigned; 6: o requester 101 é Group
        with pytest.raises(AccessDenied):
            service.get_ticket(A, ticket_id)


def test_nothing_of_b_reaches_a_through_any_operation(service):
    seen = dump(
        service.get_ticket(A, 1),
        service.list_tickets(A),
        service.ticket_statistics(A),
        service.similar_cases(A),
        service.list_articles(A),
    )
    for marker in PRIVATE_MARKERS + ("PUBLICO-B", "SOLUCAO-B", "b.cliente", "Impressora (B)"):
        assert marker not in seen


def test_client_never_gets_private_unflagged_or_unknown_timeline_items(service):
    ticket = service.get_ticket(A, 1)
    assert "SENTINELA" not in dump(ticket)  # is_private ausente conta como privado; Task é ignorada


def test_list_tickets_returns_only_own_non_deleted(service):
    assert sorted(t["id"] for t in service.list_tickets(A)) == [1, 7]
    assert sorted(t["id"] for t in service.list_tickets(B)) == [2, 4, 5, 6]


# --- Estatística, ranking e ferramentas ----------------------------------------

def test_client_statistics_are_computed_only_over_own_authorized_set(service):
    stats = service.ticket_statistics(A)
    assert stats["scope"] == "own" and stats["total"] == 2
    assert stats["by_status"] == {"Fechado": 1, "Novo": 1}
    assert stats["by_category"] == {"rede": 1, "acesso": 1}


def test_staff_statistics_are_global_but_exclude_trash(service):
    stats = service.ticket_statistics(TECH_7)
    assert stats["scope"] == "global" and stats["total"] == 6


@pytest.mark.parametrize("who", [A, TECH_7, None])
def test_global_ranking_is_blocked_for_everyone(service, who):
    with pytest.raises(ToolDenied):
        service.ranking_global(who)
    with pytest.raises(ToolDenied):
        service.authorize_tool(who, "ranking_global")


def test_disabled_and_unknown_tools_are_denied_and_gate_the_operation(glpi):
    service = AuthorizationService(glpi, disabled_tools={"get_ticket"})
    with pytest.raises(ToolDenied):
        service.get_ticket(TECH_7, 1)
    for name in ("get_ticket", "inexistente", "", None, "__import__"):
        with pytest.raises(ToolDenied):
            service.authorize_tool(TECH_7, name)
    service.authorize_tool(TECH_7, "list_tickets")  # as demais continuam permitidas
    assert glpi.calls == []


def test_operations_require_a_principal(service):
    for call in (
        lambda: service.get_ticket(None, 1), lambda: service.list_tickets({"role": "staff"}),
        lambda: service.ticket_statistics("staff"), lambda: service.list_articles(None),
    ):
        with pytest.raises(AccessDenied):
            call()


# --- Conjunto autorizado vazio ---------------------------------------------------

@pytest.mark.parametrize("operation", ["list_tickets", "ticket_statistics", "similar_cases"])
def test_empty_authorized_set_is_denied_not_answered_as_zero(service, operation):
    with pytest.raises(EmptyAuthorizedSet):
        getattr(service, operation)(C)


def test_empty_articles_are_denied(glpi):
    glpi.data["articles"] = []
    with pytest.raises(EmptyAuthorizedSet):
        AuthorizationService(glpi).list_articles(A)


# --- Staff: escopo previsto --------------------------------------------------------

def test_staff_reads_non_deleted_originals_with_team(service):
    ticket = service.get_ticket(TECH_7, 2)
    assert ticket["team"] == [
        {"role": "requester", "id": 102, "name": "b.cliente"},
        {"role": "assigned", "id": 7, "name": "ana.ribeiro"},
    ]
    with pytest.raises(AccessDenied):
        service.get_ticket(TECH_7, 3)  # lixeira vale para todos


def test_staff_sees_private_followups_only_on_tickets_where_it_is_in_the_team(service):
    assert "SENTINELA-PRIVADO-B" in dump(service.get_ticket(TECH_7, 2))
    assert "SENTINELA-PRIVADO-B" not in dump(service.get_ticket(TECH_8, 2))
    assert "PUBLICO-B" in dump(service.get_ticket(TECH_8, 2))


def test_staff_never_gets_trash_in_listing_or_statistics(service):
    assert 3 not in [t["id"] for t in service.list_tickets(TECH_7)]
    assert "SENTINELA-LIXEIRA" not in dump(service.list_tickets(TECH_7))


# --- Revogação e dados inconsistentes -------------------------------------------------

def test_revoked_membership_is_denied_on_the_next_call_without_cache(service, glpi):
    assert service.get_ticket(A, 1)["id"] == 1
    ticket = glpi._ticket(1)
    ticket["team"] = [m for m in ticket["team"] if m["id"] != 101]
    with pytest.raises(AccessDenied):
        service.get_ticket(A, 1)
    assert 1 not in [t["id"] for t in service.list_tickets(A)]


def test_ticket_moved_to_trash_is_denied_on_the_next_call(service, glpi):
    service.get_ticket(A, 1)
    glpi._ticket(1)["is_deleted"] = True
    with pytest.raises(AccessDenied):
        service.get_ticket(A, 1)


@pytest.mark.parametrize("breakage", ["no_is_deleted", "no_team", "team_not_list", "bad_member"])
def test_malformed_ticket_fails_closed(service, glpi, breakage):
    ticket = glpi._ticket(1)
    if breakage == "no_is_deleted":
        del ticket["is_deleted"]
    elif breakage == "no_team":
        del ticket["team"]
    elif breakage == "team_not_list":
        ticket["team"] = "101"
    else:
        ticket["team"] = ["101", {"type": "User", "role": "requester", "id": "101"}]
    with pytest.raises(AccessDenied):
        service.get_ticket(A, 1)
    assert 1 not in [t["id"] for t in service.list_tickets(A)]


def test_other_http_failures_are_not_disguised_as_denial(service, glpi):
    def boom(endpoint, item_id):
        response = requests.Response()
        response.status_code = 500
        raise requests.HTTPError("500", response=response)
    glpi.get_by_id = boom
    with pytest.raises(requests.HTTPError):
        service.get_ticket(A, 1)


# --- Caso técnico preparado ------------------------------------------------------------

def test_prepared_case_has_its_own_projection_without_identity_or_private_data(service):
    cases = service.similar_cases(TECH_7)
    assert sorted(c["id"] for c in cases) == [1, 2]  # só com solução e fora da lixeira
    for case in cases:
        assert set(case) == {"id", "title", "problem", "solution", "source_reference"}
        assert case["source_reference"] == "/Assistance/Ticket"
    original = service.get_ticket(TECH_7, 1)
    assert set(cases[0]) != set(original)
    text = dump(cases)
    for marker in PRIVATE_MARKERS + ("a.cliente", "b.cliente", "ana.ribeiro", "PUBLICO-A"):
        assert marker not in text


def test_client_prepared_cases_come_only_from_own_tickets(service):
    assert [c["id"] for c in service.similar_cases(A)] == [1]
    assert [c["id"] for c in service.similar_cases(B)] == [2]


def test_case_without_a_public_solution_is_not_a_source(service, glpi):
    glpi._ticket(1)["timeline"] = [t for t in glpi._ticket(1)["timeline"] if t["type"] != "Solution"]
    assert [c["id"] for c in service.similar_cases(TECH_7)] == [2]
    with pytest.raises(EmptyAuthorizedSet):
        service.similar_cases(A)


# --- Artigos compartilhados ----------------------------------------------------------------

@pytest.mark.parametrize("who", [A, B, TECH_7])
def test_articles_are_shared_with_any_session_regardless_of_is_faq(service, who):
    articles = service.list_articles(who)
    assert [a["id"] for a in articles] == [901, 902]
    assert set(articles[0]) == {"id", "title", "content", "date_mod", "source_reference"}
    assert articles[0]["source_reference"] == "/Knowledgebase/Article"


# --- Conteúdo recuperado é dado ---------------------------------------------------------------

def test_retrieved_text_never_changes_permissions(service):
    own = service.get_ticket(A, 7)
    assert "IGNORE as regras" in own["content"]  # o texto é preservado como dado...
    for _ in range(2):  # ...e nada muda, nem depois de lê-lo
        with pytest.raises(AccessDenied):
            service.get_ticket(A, 2)
        with pytest.raises(ToolDenied):
            service.ranking_global(A)
    assert service.ticket_statistics(A)["scope"] == "own"


def test_model_payload_marks_everything_as_untrusted_data(service):
    payload = as_model_data(service.list_tickets(A), source="tickets")
    assert payload["trust"] == "untrusted_data" and payload["source"] == "tickets"
    assert payload["records"] == service.list_tickets(A)
    with pytest.raises(EmptyAuthorizedSet):
        as_model_data([], source="tickets")
