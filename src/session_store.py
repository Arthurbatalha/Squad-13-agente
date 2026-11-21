import sqlite3
import json
from src.config import STATE_FILE
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

VALID_STATES = frozenset([
    "pending",
    "confirmed", 
    "executing",
    "succeeded",
    "partial",
    "uncertain",
    "cancelled"
    ])

@contextmanager
def _connect(db_path: Optional[Path]=None):
    target = Path(db_path) if db_path is not None else STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(target)
    try:
        with conn:
            yield conn
    finally:
        conn.close() 

def init_db(db_path: Optional[Path]= None): # Garante que os dados existam na database

    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS ui_sessions (
                thread_id TEXT PRIMARY KEY,
                character_id INTEGER,
                pending_action TEXT,
                last_write_result TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS action_executions (
                action_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                operation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                staff_user_id INTEGER NOT NULL,
                target TEXT,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

def save_session(
        thread_id: str,
        character_id: int,
        pending_action: dict,
        last_write_result: dict,
        db_path: Optional[Path]= None
):
    tuple_data = (
        thread_id,
        character_id,
        json.dumps(pending_action) if pending_action is not None else None,
        json.dumps(last_write_result) if last_write_result is not None else None
    )

    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO ui_sessions
            (thread_id, character_id, pending_action, last_write_result, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, tuple_data)

def get_session(thread_id: str, db_path: Optional[Path]= None):

    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT character_id, pending_action, last_write_result
            FROM ui_sessions
            WHERE thread_id = ?
        """, (thread_id, ))

        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "character_id": row[0],
        "pending_action": json.loads(row[1]) if row[1] is not None else None,
        "last_write_result": json.loads(row[2]) if row[2] is not None else None
    }

def create_action_record(
        action_id,
        thread_id,
        version,
        operation,
        payload: dict,
        staff_user_id: int,
        target: Optional[str]=None,
        status: str="pending",
        result: Optional[dict]=None,
        db_path: Optional[Path]=None
):

    if status not in VALID_STATES:
        raise ValueError(f"Status inválido {status}")

    payload_json = json.dumps(payload)
    result_json = json.dumps(result) if result is not None else None

    data_tuple = (
        action_id,
        thread_id,
        version,
        operation,
        payload_json,
        staff_user_id,
        target,
        status,
        result_json
    )

    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO action_executions
            (action_id, thread_id, version, operation, payload_json, staff_user_id, target, status, result_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) 
    """, data_tuple)

def get_action_record(action_id: str, db_path: Optional[Path]=None):
    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT thread_id, version, operation, payload_json, staff_user_id, target, status, result_json
            FROM action_executions
            WHERE action_id = ?
        """, (action_id, ))

        row = cursor.fetchone()

    if row is None:
        return None

    return {
        "action_id": action_id,
        "thread_id": row[0],
        "version": row[1],
        "operation": row[2],
        "payload": json.loads(row[3]) if row[3] is not None else None,
        "staff_user_id": row[4],
        "target": row[5],
        "status": row[6],
        "result": json.loads(row[7]) if row[7] is not None else None
    }

def finish_action_execution(
        action_id: str,
        status: str,
        result: Optional[dict]=None,
        db_path: Optional[Path]=None
):

    result_json = json.dumps(result) if result is not None else None

    final_states = [
        "succeeded",
        "partial",
        "uncertain",
        "cancelled"
    ]

    if status not in final_states:
        raise ValueError("Status Invalido")

    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE action_executions
            SET status = ?, result_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE action_id = ?
        """, (status, result_json, action_id))

        if cursor.rowcount == 0:
            raise ValueError(f"Registro da ação não encontrado: {action_id}")

def claim_action_execution(
        action_id: str,
        expected_version: int,
        db_path: Optional[Path]=None
):

    with _connect(db_path) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE action_executions
            SET status = 'executing', updated_at = CURRENT_TIMESTAMP
            WHERE action_id = ? AND version = ? AND status IN ('pending', 'confirmed')
    """, (action_id, expected_version))

        claimed = cursor.rowcount == 1

    record = get_action_record(action_id, db_path)
    return claimed, record

