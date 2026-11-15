import sqlite3
import json
from src.config import STATE_FILE

def init_db(): # Garante que os dados existam na database

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(STATE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ui_sessions (
            thread_id TEXT PRIMARY KEY,
            character_id INTEGER,
            pending_action TEXT,
            last_write_result TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

def save_session(
        thread_id: str,
        character_id: int,
        pending_action: dict,
        last_write_result: dict
):
    tuple_data = (
        thread_id if thread_id != None else None,
        character_id if character_id != None else None,
        json.dumps(pending_action) if pending_action != None else None,
        json.dumps(last_write_result) if last_write_result != None else None
    )

    conn = sqlite3.connect(STATE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO ui_sessions
        (thread_id, character_id, pending_action, last_write_result, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, tuple_data)

    conn.commit()
    conn.close()

def get_session(thread_id: str):

    conn = sqlite3.connect(STATE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT character_id, pending_action, last_write_result
        FROM ui_sessions
        WHERE thread_id = ?
    """, (thread_id, ))

    row = cursor.fetchone()
    conn.close()

    if row == None:
        return None

    return {
        "character_id": row[0],
        "pending_action": json.loads(row[1]) if row[1] != None else None,
        "last_write_result": json.loads(row[2]) if row[2] != None else None
    }