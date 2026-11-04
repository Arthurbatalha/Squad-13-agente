import pytest

from scripts.coletar_dados import build_diagnostic
from src.glpi_integration.GLPI_Client import (
    GLPICollection,
    GLPIProtocolError,
)


COLLECTION_NAMES = ("tickets", "categories", "users", "articles")


def make_data(tickets=None, articles=None):
    """Monta coleções fictícias, sem acessar o laboratório."""
    records = {
        "tickets": tickets if tickets is not None else [],
        "categories": [],
        "users": [],
        "articles": articles if articles is not None else [],
    }

    return {
        name: GLPICollection(
            endpoint=f"/fake/{name}",
            items=items,
            total=len(items),
            pages=1,
        )
        for name, items in records.items()
    }


def test_diagnostic_calculates_totals_and_distributions():
    data = make_data(
        tickets=[
            {
                "id": 1,
                "status": {"name": "Novo"},
                "category": {"name": "Rede"},
            },
            {
                "id": 2,
                "status": {"name": "Novo"},
                "category": {"name": "Software"},
            },
            {
                "id": 3,
                "status": {"name": "Fechado"},
                "category": {"name": "Rede"},
            },
        ],
        articles=[{"id": 10}, {"id": 20}],
    )

    result = build_diagnostic(data)

    assert result["totals"] == {
        "tickets": 3,
        "categories": 0,
        "users": 0,
        "articles": 2,
    }
    assert result["status_counts"] == {"Novo": 2, "Fechado": 1}
    assert result["category_counts"] == {"Rede": 2, "Software": 1}


def test_diagnostic_accepts_empty_complete_collections():
    result = build_diagnostic(make_data())

    assert result["totals"] == {
        "tickets": 0,
        "categories": 0,
        "users": 0,
        "articles": 0,
    }
    assert result["status_counts"] == {}
    assert result["category_counts"] == {}


@pytest.mark.parametrize("collection_name", COLLECTION_NAMES)
def test_diagnostic_rejects_incomplete_collection(collection_name):
    data = make_data()
    data[collection_name].complete = False

    with pytest.raises(GLPIProtocolError, match="incompleta"):
        build_diagnostic(data)


@pytest.mark.parametrize("collection_name", COLLECTION_NAMES)
def test_diagnostic_rejects_inconsistent_total(collection_name):
    data = make_data()
    data[collection_name].total = 1

    with pytest.raises(GLPIProtocolError, match="não corresponde"):
        build_diagnostic(data)