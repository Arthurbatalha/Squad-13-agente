"""Serviços de leitura CON-01: detalhe, listagem e estatísticas."""
from collections import Counter
from datetime import datetime, timezone
import requests
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.glpi_integration.GLPI_Client import GLPIProtocolError
from src.authorization.service import TICKETS

from src.authorization import projections, policies
from src.authorization.policies import AccessDenied, EmptyAuthorizedSet
from src.query.contracts import DetailQuery, ListQuery, StatisticsQuery, QueryContractError
from src.query.resolver import resolve_id

TOOL_NAMES = {"detail": "query_detail", "list": "query_list", "statistics": "query_statistics"}

class QueryService:
    def __init__(self, authorization):
        self.authorization = authorization

    def _records(self, principal, operation):
        self.authorization.authorize_tool(principal, TOOL_NAMES[operation])
        return self.authorization._authorized(principal)

    @staticmethod
    def _envelope(operation, data, *, filters=None, scope="authorized", status="success", complete=True):
        return {"status": status, "operation": operation, "scope": scope, "data": data,
                "filters_applied": filters or {}, "completeness": {"complete": complete},
                "generated_at": datetime.now(timezone.utc).isoformat()}

    def detail(self, principal, arguments):
        q = DetailQuery.parse(arguments)
        records = self._records(principal, "detail")
        ticket = next((t for t in records if t.get("id") == q.id), None)
        if ticket is None:
            return self._envelope("query_detail", None, status="access_denied")
        try:
            timeline = self.authorization._timeline(q.id)
            result = projections.project_original(principal, ticket, timeline)
        except (requests.RequestException, GLPIProtocolError, OSError, ValueError, TypeError, KeyError):
            return self._envelope("query_detail", None, status="query_failed", complete=False)
        return self._envelope("query_detail", result)

    def list(self, principal, arguments):
        q = ListQuery.parse(arguments)
        try:
            records = self._records(principal, "list")
        except AccessDenied:
            raise
        except (requests.RequestException, GLPIProtocolError, OSError, ValueError, TypeError, KeyError):
            return self._envelope("query_list", None, status="query_failed", complete=False)
        filters = dict(q.filters)
        for key in ("category_id", "assignee_id"):
            if key in filters and type(filters[key]) is not int:
                filters[key] = resolve_id(records, key, filters[key])
        filtered = [t for t in records if self._matches(t, filters)]
        if not filtered:
            return self._envelope("query_list", [], filters=filters, status="empty")
        summaries = [projections.project_summary(t) for t in filtered]
        page = summaries[q.offset:q.offset + q.limit]
        return self._envelope("query_list", {"records": page, "total_matching": len(summaries), "limit": q.limit, "offset": q.offset}, filters=filters)

    def statistics(self, principal, arguments):
        q = StatisticsQuery.parse(arguments)
        try:
            records = self._records(principal, "statistics")
        except AccessDenied:
            raise
        except (requests.RequestException, GLPIProtocolError, OSError, ValueError, TypeError, KeyError):
            return self._envelope("query_statistics", None, status="query_failed", complete=False)
        filters = dict(q.filters)
        for key in ("category_id", "assignee_id"):
            if key in filters and type(filters[key]) is not int:
                filters[key] = resolve_id(records, key, filters[key])
        records = [t for t in records if self._matches(t, filters)]
        if not records: return self._envelope("query_statistics", {}, filters=filters, status="empty")
        if q.metric == "count": data = {"metric": "count", "value": len(records)}
        elif q.metric == "by_category": data = {"metric": q.metric, "values": dict(Counter(projections.name_of(t.get("category")) or "Sem categoria" for t in records))}
        else:
            names = []
            for t in records:
                assigned = [m.get("name") for m in policies.team_members(t) or [] if m.get("role") == "assigned"]
                names.extend(assigned or ["Sem responsável"])
            data = {"metric": q.metric, "values": dict(Counter(names))}
        return self._envelope("query_statistics", data, filters=filters)

    @staticmethod
    def _matches(ticket, filters):
        if "status" in filters:
            status = projections.name_of(ticket.get("status"))
            if status not in filters["status"]: return False
        if "category_id" in filters:
            cat = ticket.get("category")
            if not isinstance(cat, dict) or cat.get("id") != filters["category_id"]: return False
        if "assignee_id" in filters:
            team = policies.team_members(ticket) or []
            if not any(m.get("role") == "assigned" and m.get("id") == filters["assignee_id"] for m in team): return False
        if "date_from" in filters or "date_to" in filters:
            field = filters["date_event"]
            raw = ticket.get(field)
            try: value = datetime.fromisoformat(raw[:10]).date() if isinstance(raw, str) and raw else None
            except ValueError: value = None
            if value is None: return False
            if "date_from" in filters and value < filters["date_from"]: return False
            if "date_to" in filters and value > filters["date_to"]: return False
        return True
