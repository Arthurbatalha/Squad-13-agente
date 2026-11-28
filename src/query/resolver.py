"""Resolução segura de nomes de categoria e responsável para IDs do GLPI."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.query.contracts import QueryAmbiguousError, QueryContractError


def _entity_name(value):
    if isinstance(value, dict): return value.get("name")
    return value if isinstance(value, str) else None


def resolve_id(tickets, field: str, value):
    """Resolve nomes usando somente registros já autorizados. ID numérico é validado."""
    if field not in {"category_id", "assignee_id"}: raise QueryContractError("campo de resolução inválido")
    if type(value) is int and value > 0: return value
    if not isinstance(value, str) or not value.strip(): raise QueryContractError("informe nome ou ID")
    needle = value.strip().casefold()
    found = {}
    for ticket in tickets:
        if field == "category_id":
            entity = ticket.get("category")
            if isinstance(entity, dict) and type(entity.get("id")) is int:
                name = _entity_name(entity)
                if name: found[entity["id"]] = name
        else:
            team = ticket.get("team")
            if isinstance(team, list):
                for member in team:
                    if isinstance(member, dict) and member.get("role") == "assigned" and member.get("type") == "User" and type(member.get("id")) is int:
                        name = _entity_name(member)
                        if name: found[member["id"]] = name
    matches = {i: name for i, name in found.items() if name.casefold() == needle}
    if not matches:
        matches = {i: name for i, name in found.items() if needle in name.casefold()}
    if len(matches) > 1: raise QueryAmbiguousError("nome corresponde a mais de uma entidade; especifique melhor")
    if not matches: raise QueryContractError("entidade não encontrada no escopo autorizado")
    return next(iter(matches))
