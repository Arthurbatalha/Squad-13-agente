"""Contratos fechados para as ferramentas gerais de leitura CON-01."""
from dataclasses import dataclass
from datetime import date
from typing import Any

RESOURCES = frozenset({"ticket"})
LIST_FILTERS = frozenset({"status", "category_id", "assignee_id", "date_from", "date_to", "date_event"})
STAT_METRICS = frozenset({"count", "by_category", "by_assignee"})
DATE_EVENTS = frozenset({"date", "date_solve", "date_close"})
MAX_LIMIT = 100
MAX_PERIOD_DAYS = 366

class QueryContractError(ValueError):
    """Argumento fora do contrato da ferramenta."""

class QueryAmbiguousError(ValueError):
    """Nome informado corresponde a mais de uma entidade."""

@dataclass(frozen=True)
class DetailQuery:
    resource: str
    id: int

    @classmethod
    def parse(cls, value: Any):
        _exact_keys(value, {"resource", "id"})
        if value["resource"] not in RESOURCES: raise QueryContractError("resource inválido")
        if type(value["id"]) is not int or value["id"] <= 0: raise QueryContractError("id deve ser inteiro positivo")
        return cls(value["resource"], value["id"])

@dataclass(frozen=True)
class ListQuery:
    resource: str
    filters: dict
    limit: int = 50
    offset: int = 0

    @classmethod
    def parse(cls, value: Any):
        _exact_keys(value, {"resource", "filters", "limit", "offset"}, {"resource", "filters"})
        if value["resource"] not in RESOURCES: raise QueryContractError("resource inválido")
        filters = value["filters"]
        if not isinstance(filters, dict) or set(filters) - LIST_FILTERS: raise QueryContractError("filtros inválidos")
        filters = dict(filters)
        if "status" in filters:
            status = filters["status"]
            if isinstance(status, str): status = [status]
            if not isinstance(status, list) or not status or any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in status):
                raise QueryContractError("status inválido")
            filters["status"] = list(dict.fromkeys(status))
        for key in ("category_id", "assignee_id"):
            if key in filters:
                item = filters[key]
                if not ((type(item) is int and item > 0) or (isinstance(item, str) and item.strip() and len(item) <= 120)):
                    raise QueryContractError(f"{key} deve ser ID positivo ou nome válido")
        for key in ("date_from", "date_to"):
            if key in filters:
                try: filters[key] = date.fromisoformat(filters[key]) if isinstance(filters[key], str) else filters[key]
                except (TypeError, ValueError): raise QueryContractError(f"{key} deve ser ISO YYYY-MM-DD") from None
                if not isinstance(filters[key], date): raise QueryContractError(f"{key} inválido")
        if "date_event" in filters and filters["date_event"] not in DATE_EVENTS: raise QueryContractError("date_event inválido")
        if ("date_from" in filters or "date_to" in filters) and "date_event" not in filters: raise QueryContractError("date_event é obrigatório para período")
        if "date_from" in filters and "date_to" in filters:
            if filters["date_from"] > filters["date_to"]: raise QueryContractError("período invertido")
            if (filters["date_to"] - filters["date_from"]).days > MAX_PERIOD_DAYS: raise QueryContractError("período excede 366 dias")
        limit, offset = value.get("limit", 50), value.get("offset", 0)
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT: raise QueryContractError("limit deve estar entre 1 e 100")
        if type(offset) is not int or offset < 0: raise QueryContractError("offset deve ser inteiro não negativo")
        return cls(value["resource"], filters, limit, offset)

@dataclass(frozen=True)
class StatisticsQuery:
    resource: str
    metric: str
    filters: dict

    @classmethod
    def parse(cls, value: Any):
        _exact_keys(value, {"resource", "metric", "filters"}, {"resource", "metric", "filters"})
        if value["resource"] not in RESOURCES: raise QueryContractError("resource inválido")
        if value["metric"] not in STAT_METRICS: raise QueryContractError("metric inválida")
        # Reuse validation of list filters.
        ListQuery.parse({"resource": value["resource"], "filters": value["filters"], "limit": 1, "offset": 0})
        return cls(value["resource"], value["metric"], dict(value["filters"]))

def _exact_keys(value, allowed, required=None):
    if not isinstance(value, dict): raise QueryContractError("argumentos devem ser objeto")
    required = allowed if required is None else required
    if set(value) - allowed or required - set(value): raise QueryContractError("campos ausentes ou não permitidos")
