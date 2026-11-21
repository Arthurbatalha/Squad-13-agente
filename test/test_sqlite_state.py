"""Testes de persistência SQLite: sessões, registro atômico de escritas e SqliteSaver (EST-01)."""

from pathlib import Path
import sqlite3
import sys
from typing import TypedDict

from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
import pytest

PROJECT_ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "src").is_dir()
)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.app import create_app
import src.session_store as store


class _MiniState(TypedDict):
    nota: str


def _compile_mini_graph(checkpointer: SqliteSaver):
    """Monta um grafo mínimo do LangGraph para validar persistência do SqliteSaver."""

    def _registrar(state: _MiniState) -> dict[str, str]:
        return {"nota": f"salvo:{state['nota']}"}

    builder = StateGraph(_MiniState)
    builder.add_node("registrar", _registrar)
    builder.add_edge(START, "registrar")
    builder.add_edge("registrar", END)
    return builder.compile(checkpointer=checkpointer)


# ------------------------------------------------------------------ 1. Sessões (ui_sessions)


def test_session_persistence_and_thread_isolation(tmp_path: Path) -> None:
    db_file = tmp_path / "state.sqlite3"
    store.init_db(db_file)

    store.save_session(
        thread_id="thread-A",
        character_id=101,
        pending_action={"action_id": "act-1", "version": 1},
        last_write_result={"status": "succeeded", "ticket_id": 55},
        db_path=db_file,
    )
    store.save_session(
        thread_id="thread-B",
        character_id=102,
        pending_action=None,
        last_write_result={"status": "cancelled"},
        db_path=db_file,
    )

    session_a = store.get_session("thread-A", db_path=db_file)
    session_b = store.get_session("thread-B", db_path=db_file)
    missing = store.get_session("thread-inexistente", db_path=db_file)

    assert session_a == {
        "character_id": 101,
        "pending_action": {"action_id": "act-1", "version": 1},
        "last_write_result": {"status": "succeeded", "ticket_id": 55},
    }
    assert session_b == {
        "character_id": 102,
        "pending_action": None,
        "last_write_result": {"status": "cancelled"},
    }
    assert missing is None


# ------------------------------------------------------------------ 2. Execução atômica de escritas


def test_action_execution_lifecycle_and_atomic_claim(tmp_path: Path) -> None:
    db_file = tmp_path / "state.sqlite3"
    store.init_db(db_file)

    payload = {"title": "VPN sem acesso", "requester_id": 7}
    store.create_action_record(
        action_id="act-001",
        thread_id="thread-A",
        version=1,
        operation="open_ticket",
        payload=payload,
        staff_user_id=101,
        target="ticket:new",
        status="pending",
        db_path=db_file,
    )

    # Mesmo action_id não pode ser inserido duas vezes (PRIMARY KEY)
    with pytest.raises(sqlite3.IntegrityError):
        store.create_action_record(
            action_id="act-001",
            thread_id="thread-A",
            version=1,
            operation="open_ticket",
            payload=payload,
            staff_user_id=101,
            db_path=db_file,
        )

    # Status inválido na criação é rejeitado
    with pytest.raises(ValueError):
        store.create_action_record(
            action_id="act-invalido",
            thread_id="thread-A",
            version=1,
            operation="open_ticket",
            payload=payload,
            staff_user_id=101,
            status="status-desconhecido",
            db_path=db_file,
        )

    # Ação inexistente não pode ser reivindicada
    claimed_missing, rec_missing = store.claim_action_execution(
        "act-nao-existe", expected_version=1, db_path=db_file
    )
    assert claimed_missing is False
    assert rec_missing is None

    # Versão obsoleta é recusada sem mudar o status
    claimed_stale, rec_stale = store.claim_action_execution(
        "act-001", expected_version=99, db_path=db_file
    )
    assert claimed_stale is False
    assert rec_stale is not None
    assert rec_stale["status"] == "pending"

    # Primeira reivindicação válida transita atomicamente para 'executing'
    claimed_first, rec_first = store.claim_action_execution(
        "act-001", expected_version=1, db_path=db_file
    )
    assert claimed_first is True
    assert rec_first is not None
    assert rec_first["status"] == "executing"
    assert rec_first["payload"] == payload

    # Confirmação repetida enquanto está em 'executing' é bloqueada
    claimed_dup, rec_dup = store.claim_action_execution(
        "act-001", expected_version=1, db_path=db_file
    )
    assert claimed_dup is False
    assert rec_dup is not None
    assert rec_dup["status"] == "executing"

    # Finalização grava status final e resultado em JSON
    store.finish_action_execution(
        "act-001",
        status="succeeded",
        result={"ticket_id": 500},
        db_path=db_file,
    )
    finished = store.get_action_record("act-001", db_path=db_file)
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["result"] == {"ticket_id": 500}

    # Após concluída, nova tentativa de claim continua bloqueada
    claimed_after, rec_after = store.claim_action_execution(
        "act-001", expected_version=1, db_path=db_file
    )
    assert claimed_after is False
    assert rec_after is not None
    assert rec_after["status"] == "succeeded"

    # Status final inválido e action_id inexistente levantam ValueError
    with pytest.raises(ValueError):
        store.finish_action_execution("act-001", status="executing", db_path=db_file)
    with pytest.raises(ValueError):
        store.finish_action_execution("act-nao-existe", status="cancelled", db_path=db_file)


# ------------------------------------------------------------------ 3. Retomada do SqliteSaver


def test_sqlite_saver_recovers_checkpoint_after_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "checkpoints.sqlite3"
    config_a = {"configurable": {"thread_id": "t-reinicio"}}
    config_b = {"configurable": {"thread_id": "t-isolado"}}

    # Processo 1: grava checkpoint e fecha a conexão simulando queda/reinício
    conn1 = sqlite3.connect(db_file, check_same_thread=False)
    try:
        saver1 = SqliteSaver(conn1)
        saver1.setup()
        graph1 = _compile_mini_graph(saver1)
        output = graph1.invoke({"nota": "chamado-42"}, config=config_a)
        assert output == {"nota": "salvo:chamado-42"}
    finally:
        conn1.close()

    # Processo 2: reabre o mesmo arquivo SQLite em nova conexão e recupera o estado
    conn2 = sqlite3.connect(db_file, check_same_thread=False)
    try:
        saver2 = SqliteSaver(conn2)
        graph2 = _compile_mini_graph(saver2)

        recovered = graph2.get_state(config_a)
        isolated = graph2.get_state(config_b)

        assert recovered.values == {"nota": "salvo:chamado-42"}
        assert isolated.values == {}
    finally:
        conn2.close()


# ------------------------------------------------------------------ 4. Arranque limpo da API


def test_create_app_bootstraps_missing_directory_and_closes_sqlite_on_shutdown(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "pasta_nova" / "subpasta" / "api_state.sqlite3"
    assert not db_file.parent.exists()

    app = create_app(frontend_dist=None, state_file=db_file)

    assert db_file.exists()
    assert isinstance(app.state.checkpointer, SqliteSaver)

    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    # Ao sair do contexto do TestClient, o lifespan deve ter fechado a conexão SQLite
    with pytest.raises(sqlite3.ProgrammingError):
        app.state.sqlite_conn.execute("SELECT 1")