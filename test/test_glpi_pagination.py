import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.glpi_integration.GLPI_Client import GLPIClient, GLPICollection
from src.glpi_integration.auth import GLPIProtocolError
from scripts.coletar_dados import collect_data, extract_participants


def make_client():
    return GLPIClient(
        "http://glpi.test/api.php/v2",
        "access-token",
        "refresh-token",
        "client-id",
        "client-secret",
    )


def response(status_code, body, content_range=None):
    headers = {}
    if content_range is not None:
        headers["Content-Range"] = content_range
    return SimpleNamespace(
        status_code=status_code,
        headers=headers,
        json=lambda: body,
    )


def test_search_all_reads_exact_multiple_of_limit_without_extra_empty_page():
    client = make_client()
    requests = []
    pages = [
        response(206, [{"id": 1}, {"id": 2}], "0-1/4"),
        response(206, [{"id": 3}, {"id": 4}], "2-3/4"),
    ]

    def request(method, url, **kwargs):
        requests.append(kwargs["params"])
        return pages.pop(0)

    client._secure_request = request
    collection = client.search_all("/Assistance/Ticket", limit=2)

    assert isinstance(collection, GLPICollection)
    assert collection == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]
    assert collection.complete is True
    assert collection.total == 4
    assert collection.pages == 2
    assert requests == [{"start": 0, "limit": 2}, {"start": 2, "limit": 2}]
    assert pages == []


def test_search_all_accepts_final_200_page_after_partial_206():
    client = make_client()
    requests = []
    pages = [
        response(206, [{"id": 1}, {"id": 2}], "0-1/3"),
        response(200, [{"id": 3}]),
    ]

    def request(method, url, **kwargs):
        requests.append(kwargs["params"]["start"])
        return pages.pop(0)

    client._secure_request = request
    result = client.search_all("/Assistance/Ticket", limit=2)

    assert [item["id"] for item in result] == [1, 2, 3]
    assert result.complete
    assert result.total == 3
    assert requests == [0, 2]


def test_search_all_accepts_empty_complete_collection():
    client = make_client()
    client._secure_request = lambda *args, **kwargs: response(200, [])

    result = client.search_all("/Administration/User")

    assert result == []
    assert result.complete
    assert result.total == 0


@pytest.mark.parametrize(
    "status,body,content_range",
    [
        (206, [], "0-0/1"),
        (206, [{"id": 1}], None),
        (206, [{"id": 1}], "1-1/2"),
        (206, [{"id": 1}, {"id": 2}, {"id": 3}], "0-2/3"),
        (200, {"data": []}, None),
        (200, [{"id": 1}, "unexpected"], None),
    ],
)
def test_search_all_rejects_invalid_or_unverifiable_pages(
    status, body, content_range
):
    client = make_client()
    client._secure_request = lambda *args, **kwargs: response(
        status, body, content_range
    )

    with pytest.raises(GLPIProtocolError):
        client.search_all("/Assistance/Ticket", limit=2)


def test_search_all_rejects_duplicate_ids_in_separate_pages():
    client = make_client()
    pages = [
        response(206, [{"id": 1}], "0-0/2"),
        response(206, [{"id": 1}], "1-1/2"),
    ]
    client._secure_request = lambda *args, **kwargs: pages.pop(0)

    with pytest.raises(GLPIProtocolError, match="duplicado"):
        client.search_all("/Assistance/Ticket", limit=1)


def test_search_all_propagates_intermediate_request_failure():
    client = make_client()
    pages = [response(206, [{"id": 1}], "0-0/2")]

    def request(*args, **kwargs):
        if pages:
            return pages.pop(0)
        raise ConnectionError("request failure")

    client._secure_request = request

    with pytest.raises(ConnectionError, match="request failure"):
        client.search_all("/Assistance/Ticket", limit=1)


@pytest.mark.parametrize("body", [{"id": 3}, [], None])
def test_get_by_id_requires_nonempty_object(body):
    client = make_client()
    client._secure_request = lambda *args, **kwargs: response(200, body)

    if isinstance(body, dict):
        assert client.get_by_id("/Assistance/Ticket", 3) == body
    else:
        with pytest.raises(GLPIProtocolError):
            client.get_by_id("/Assistance/Ticket", 3)


def test_collector_uses_shared_client_and_preserves_ticket_participants():
    ticket = {
        "id": 12,
        "is_deleted": True,
        "date": "2025-04-01T09:00:00-03:00",
        "date_solve": None,
        "date_close": None,
        "team": [{"role": "requester", "id": 4, "name": "requester"}],
    }

    class FakeClient:
        def __init__(self):
            self.endpoints = []

        def search_all(self, endpoint):
            self.endpoints.append(endpoint)
            records = [ticket] if endpoint == "/Assistance/Ticket" else []
            return GLPICollection(endpoint, records, len(records), 1)

    client = FakeClient()
    data = collect_data(client)

    assert client.endpoints == [
        "/Assistance/Ticket",
        "/Dropdowns/ITILCategory",
        "/Administration/User",
        "/Knowledgebase/Article",
    ]
    assert data["tickets"][0] == ticket
    assert data["tickets"][0]["is_deleted"] is True
    assert data["tickets"][0]["date"].endswith("-03:00")
    assert data["participants"] == [
        {"ticket_id": 12, "participant": ticket["team"][0]}
    ]
    assert data["participants_complete"] is True
    assert data["participants_source"] == "/Assistance/Ticket (campo team)"


def test_participant_collection_rejects_missing_team_contract():
    with pytest.raises(GLPIProtocolError, match="team"):
        extract_participants([{"id": 12}])
