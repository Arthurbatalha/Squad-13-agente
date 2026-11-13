"""Projeções por lista de campos permitidos: o que não está aqui não sai."""

from html.parser import HTMLParser

from src.authorization.policies import (
    Principal, can_see_private_followups, flag, team_members,
)

TICKET_SOURCE = "/Assistance/Ticket"
ARTICLE_SOURCE = "/Knowledgebase/Article"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style") and self._skip > 0

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def text_of(html) -> str:
    """HTML do GLPI para texto simples (sem marcação executável no front)."""
    if not isinstance(html, str):
        return ""
    parser = _Text()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())


def name_of(value):
    if isinstance(value, dict):
        return value.get("name") if isinstance(value.get("name"), str) else None
    return value if isinstance(value, str) else None


def _items(timeline, kind):
    return [
        entry["item"] for entry in timeline
        if isinstance(entry, dict) and entry.get("type") == kind and isinstance(entry.get("item"), dict)
    ]


def _solution(timeline):
    solutions = _items(timeline, "Solution")
    if not solutions:
        return None
    last = solutions[-1]
    return {"content": text_of(last.get("content")), "date": last.get("date_creation")}


def project_summary(ticket) -> dict:
    return {
        "id": ticket["id"],
        "title": ticket.get("name"),
        "status": name_of(ticket.get("status")),
        "category": name_of(ticket.get("category")),
        "priority": ticket.get("priority"),
        "date": ticket.get("date"),
    }


def project_original(principal: Principal, ticket, timeline) -> dict:
    """Registro original. Followup sem `is_private` booleano é tratado como privado."""
    show_private = can_see_private_followups(principal, ticket)
    followups = []
    for item in _items(timeline, "Followup"):
        private = flag(item.get("is_private"))
        if private is False or (private is True and show_private):
            followups.append({
                "id": item.get("id"),
                "content": text_of(item.get("content")),
                "date": item.get("date"),
                "author": name_of(item.get("user")),
            })
    members = team_members(ticket)
    view = {
        **project_summary(ticket),
        "content": text_of(ticket.get("content")),
        "date_solve": ticket.get("date_solve"),
        "date_close": ticket.get("date_close"),
        "followups": followups,
        "solution": _solution(timeline),
        "assigned_to": [m.get("name") for m in members if m["role"] == "assigned"],
    }
    if principal.role == "staff":
        view["team"] = [
            {"role": m["role"], "id": m["id"], "name": m.get("name")} for m in members
        ]
    return view


def project_case(ticket, timeline):
    """Caso técnico preparado: problema e solução, sem pessoas nem acompanhamentos.

    Devolve None quando não há solução registrada (não serve como fonte).
    """
    solution = _solution(timeline)
    if solution is None or not solution["content"]:
        return None
    return {
        "id": ticket["id"],
        "title": ticket.get("name"),
        "problem": text_of(ticket.get("content")),
        "solution": solution["content"],
        "source_reference": TICKET_SOURCE,
    }


def project_article(article):
    """Contrato de source_treatment(); None se o registro for inválido."""
    if not isinstance(article, dict) or type(article.get("id")) is not int or not article.get("content"):
        return None
    return {
        "id": article["id"],
        "title": article.get("name"),
        "content": article["content"],
        "date_mod": article.get("date_mod"),
        "source_reference": ARTICLE_SOURCE,
    }
