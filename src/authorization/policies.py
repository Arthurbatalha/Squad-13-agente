"""Políticas de acesso: identidade confiável, ferramentas e regras por recurso.

Toda decisão usa somente o `Principal` (criado pelo backend) e os campos
estruturais do GLPI (`is_deleted`, `team`, `is_private`). O texto de chamados
e artigos nunca é lido por estas funções, então conteúdo recuperado não
consegue alterar permissões. Dado ausente ou inesperado nega o acesso.
"""

from dataclasses import dataclass

DENIED_MESSAGE = "Recurso indisponível."

ROLES = frozenset({"client", "staff"})

# Ferramenta -> papéis que podem usá-la. O que não está aqui é negado.
TOOL_ROLES = {
    "get_ticket": ROLES,
    "list_tickets": ROLES,
    "ticket_statistics": ROLES,
    "similar_cases": ROLES,
    "search_articles": ROLES,
}
# Nunca liberada, nem por configuração: ranking e estatística entre usuários.
BLOCKED_TOOLS = frozenset({"ranking_global"})


class AccessDenied(PermissionError):
    """Acesso negado. A mensagem é a mesma para inexistente e não autorizado."""

    def __init__(self, message: str = DENIED_MESSAGE):
        super().__init__(message)


class ToolDenied(AccessDenied):
    """Ferramenta desconhecida, desabilitada, bloqueada ou sem principal válido."""


class EmptyAuthorizedSet(AccessDenied):
    """Nenhum registro autorizado: nada é calculado nem enviado ao modelo."""


@dataclass(frozen=True)
class Principal:
    """Quem pede. Nunca é montado a partir de corpo de requisição ou texto."""

    role: str
    user_id: int

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError("Papel inválido.")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id deve ser um inteiro positivo.")

    @classmethod
    def client(cls, user_id: int) -> "Principal":
        return cls("client", user_id)

    @classmethod
    def staff(cls, user_id: int) -> "Principal":
        return cls("staff", user_id)

    @classmethod
    def from_session(cls, sessions, session_id: str, thread_id: str) -> "Principal":
        """Confere o vínculo sessão/conversa (SES-01) e devolve o técnico."""
        context = sessions.model_context(session_id, thread_id)
        if context.get("role") != "staff":
            raise AccessDenied()
        return cls.staff(context.get("staff_user_id"))


def tool_allowed(principal, tool, disabled=frozenset()) -> bool:
    if not isinstance(principal, Principal) or not isinstance(tool, str):
        return False
    if tool in BLOCKED_TOOLS or tool in disabled:
        return False
    return principal.role in TOOL_ROLES.get(tool, ())


def flag(value):
    """True/False para valores booleanos do GLPI; None se ausente ou estranho."""
    if isinstance(value, str):
        return {"1": True, "0": False}.get(value)
    if isinstance(value, (bool, int)) and value in (0, 1):
        return bool(value)
    return None


def team_members(ticket):
    """Membros `User` do chamado ou None se `team` estiver malformado."""
    team = ticket.get("team")
    if not isinstance(team, list):
        return None
    users = []
    for member in team:
        if not isinstance(member, dict) or not isinstance(member.get("role"), str):
            return None
        if member.get("type") == "User":
            if type(member.get("id")) is not int:
                return None
            users.append(member)
    return users


def in_trash_or_unknown(ticket) -> bool:
    return flag(ticket.get("is_deleted")) is not False


def is_requester(ticket, user_id) -> bool:
    members = team_members(ticket)
    return members is not None and any(
        m["role"] == "requester" and m["id"] == user_id for m in members
    )


def is_team_member(ticket, user_id) -> bool:
    members = team_members(ticket)
    return members is not None and any(m["id"] == user_id for m in members)


def can_read_original(principal, ticket) -> bool:
    """Cliente: requester User do chamado. Staff: qualquer chamado fora da lixeira."""
    if not isinstance(principal, Principal) or not isinstance(ticket, dict):
        return False
    if in_trash_or_unknown(ticket) or team_members(ticket) is None:
        return False
    if principal.role == "staff":
        return True
    return is_requester(ticket, principal.user_id)


def can_see_private_followups(principal, ticket) -> bool:
    """Acompanhamentos privados: só técnico que integra a equipe do chamado."""
    return (
        isinstance(principal, Principal)
        and principal.role == "staff"
        and is_team_member(ticket, principal.user_id)
    )
