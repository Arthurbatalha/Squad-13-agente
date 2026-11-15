import sqlite3
import pytest
import sys
import os

from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0 ,str(PROJECT_ROOT))

import src.session_store as store


def test_persistence_and_recovery(tmp_path):

    store.STATE_FILE = tmp_path / "test_state.sqlite3"
    store.init_db()

    mock_data = [
        {"thread_id": "A", "character_id": 101, "pending_action": {"acao": "dormir"}, "last_write_result": {"acao": "abrir_chamado"}},
        {"thread_id": "B", "character_id": 102, "pending_action": {"acao": "dormir"}, "last_write_result": {"acao": "fechar_chamado"}}
    ]

    store.save_session(**mock_data[0])
    store.save_session(**mock_data[1])

    query_test_a = store.get_session("A")
    query_test_b = store.get_session("B")

    assert query_test_a != None
    assert query_test_a["character_id"] == 101
    assert isinstance(query_test_a["pending_action"], dict)