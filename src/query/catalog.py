"""Catálogo de tools: nomes, descrições e esquemas fechados para o agente."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.query.contracts import LIST_FILTERS, STAT_METRICS

TOOL_CATALOG = (
    {"name": "query_detail", "description": "Consultar detalhes de um chamado autorizado por ID.",
     "parameters": {"resource": {"enum": ["ticket"]}, "id": {"type": "integer", "minimum": 1}}},
    {"name": "query_list", "description": "Listar chamados autorizados com filtros combináveis e paginação.",
     "parameters": {"resource": {"enum": ["ticket"]}, "filters": {"allowed": sorted(LIST_FILTERS)}, "limit": {"minimum": 1, "maximum": 100}, "offset": {"minimum": 0}}},
    {"name": "query_statistics", "description": "Estatísticas dos chamados autorizados: count, by_category ou by_assignee.",
     "parameters": {"resource": {"enum": ["ticket"]}, "metric": {"enum": sorted(STAT_METRICS)}, "filters": {"allowed": sorted(LIST_FILTERS)}}},
)
