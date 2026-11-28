"""CON-01: contratos, filtros, resolução, estatísticas e envelopes."""
import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.authorization.policies import Principal, ToolDenied
from src.authorization.service import AuthorizationService
from src.glpi_integration.GLPI_Client import GLPICollection
from src.query.contracts import QueryContractError, QueryAmbiguousError
from src.query.service import QueryService

TICKETS = [
 {"id": 1, "name": "Erro A", "status": {"name": "Novo"}, "category": {"id": 10, "name": "Rede"}, "date": "2026-02-01", "is_deleted": "0", "team": [{"role":"requester","type":"User","id":101,"name":"Cliente A"},{"role":"assigned","type":"User","id":7,"name":"Ana"}]},
 {"id": 2, "name": "Erro B", "status": {"name": "Fechado"}, "category": {"id": 20, "name": "Hardware"}, "date": "2026-03-15", "date_close": "2026-03-16", "is_deleted": "0", "team": [{"role":"requester","type":"User","id":101,"name":"Cliente A"},{"role":"assigned","type":"User","id":8,"name":"Bruno"}]},
 {"id": 3, "name": "Outro", "status": {"name": "Novo"}, "category": {"id": 10, "name": "Rede"}, "date": "2026-02-02", "is_deleted": "0", "team": [{"role":"requester","type":"User","id":102,"name":"Cliente B"},{"role":"assigned","type":"User","id":7,"name":"Ana"}]},
]
class FakeGLPI:
 def search_all(self, endpoint, start=0, limit=25):
  if endpoint == "/Assistance/Ticket": return GLPICollection(endpoint, TICKETS, len(TICKETS), 1)
  if endpoint.endswith("/Timeline"): return GLPICollection(endpoint, [], 0, 1)
  raise AssertionError(endpoint)
 def get_by_id(self, endpoint, id): return next(t for t in TICKETS if t["id"] == id)
@pytest.fixture
def queries(): return QueryService(AuthorizationService(FakeGLPI()))
STAFF = Principal.staff(7)
CLIENT = Principal.client(101)

def test_list_filters_combine_and_resolve_name(queries):
 r=queries.list(CLIENT,{"resource":"ticket","filters":{"status":"Novo","category_id":"Rede","assignee_id":"Ana","date_from":"2026-01-01","date_to":"2026-02-28","date_event":"date"},"limit":10})
 assert r["status"] == "success"
 assert r["data"]["total_matching"] == 1
 assert r["data"]["records"][0]["id"] == 1
 assert r["filters_applied"]["category_id"] == 10

def test_empty_is_distinct(queries):
 r=queries.list(CLIENT,{"resource":"ticket","filters":{"status":"Inexistente"}})
 assert r["status"] == "empty" and r["data"] == []

def test_stats_count_and_grouping(queries):
 assert queries.statistics(CLIENT,{"resource":"ticket","metric":"count","filters":{}})["data"]["value"] == 2
 cats=queries.statistics(CLIENT,{"resource":"ticket","metric":"by_category","filters":{}})["data"]["values"]
 assert cats == {"Rede":1,"Hardware":1}
 ass=queries.statistics(CLIENT,{"resource":"ticket","metric":"by_assignee","filters":{}})["data"]["values"]
 assert ass == {"Ana":1,"Bruno":1}

def test_detail_authorized_and_denied(queries):
 assert queries.detail(CLIENT,{"resource":"ticket","id":1})["status"] == "success"
 assert queries.detail(CLIENT,{"resource":"ticket","id":3})["status"] == "access_denied"

def test_invalid_contracts_rejected(queries):
 invalid=[
  {"resource":"ticket","filters":{"arbitrary_rsql":"x"}},
  {"resource":"ticket","filters":{"category_id":0}},
  {"resource":"ticket","filters":{"date_from":"2026-01-01"}},
  {"resource":"ticket","filters":{"date_from":"2026-01-10","date_to":"2026-01-01","date_event":"date"}},
  {"resource":"ticket","filters":{},"limit":101},
  {"resource":"ticket","filters":{},"offset":-1},
  {"resource":"ticket","filters":{},"user_id":123},
 ]
 for args in invalid:
  with pytest.raises(QueryContractError): queries.list(CLIENT,args)
 with pytest.raises(QueryContractError): queries.detail(CLIENT,{"resource":"ticket","id":True})
 with pytest.raises(QueryContractError): queries.statistics(CLIENT,{"resource":"ticket","metric":"avg","filters":{}})

def test_ambiguous_resolver(queries):
 # staff can see all; two authorized entities share the substring "a"
 with pytest.raises(QueryAmbiguousError):
  queries.list(STAFF,{"resource":"ticket","filters":{"assignee_id":"n"}})

def test_disabled_tool_is_access_denied():
 service=QueryService(AuthorizationService(FakeGLPI(),disabled_tools={"query_list"}))
 with pytest.raises(ToolDenied): service.list(STAFF,{"resource":"ticket","filters":{}})
