"""Durable SQLite journal connecting DexOS runtime processes.

The journal is shared by the API and ambient processes through DEXOS_STATE_DIR.
Events are append-only; each consumer acknowledges independently. SQLite WAL
mode allows concurrent readers and writers without an external service.
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    from paths import _STATE_BASE
    _BASE = Path(_STATE_BASE)
except Exception:
    _BASE = Path(os.environ.get("DEXOS_STATE_DIR") or Path(__file__).parent)
    _BASE.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("DEX_EVENT_BRIDGE_PATH") or (_BASE / "dex_event_bridge.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _connect():
    connection = sqlite3.connect(str(DB_PATH), timeout=15.0)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cognitive_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            origin TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS cognitive_event_acks (
            consumer TEXT NOT NULL,
            event_id TEXT NOT NULL,
            acknowledged_at REAL NOT NULL,
            PRIMARY KEY (consumer, event_id),
            FOREIGN KEY (event_id) REFERENCES cognitive_events(event_id)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_cognitive_events_created "
        "ON cognitive_events(created_at)"
    )
    return connection


def append_event(event_id: str, event_type: str, origin: str, payload: Dict[str, Any]) -> None:
    # Correlation IDs may intentionally span multiple event types in one
    # cognitive cycle. Journal identity is therefore (event_id, event_type).
    journal_id = f"{event_type}:{event_id}"
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    with _connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO cognitive_events "
            "(event_id, event_type, origin, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (journal_id, str(event_type), str(origin), encoded, time.time()),
        )


def pending_events(consumer: str, limit: int = 64) -> List[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT e.event_id, e.event_type, e.origin, e.payload_json, e.created_at
            FROM cognitive_events AS e
            LEFT JOIN cognitive_event_acks AS a
              ON a.event_id = e.event_id AND a.consumer = ?
            WHERE e.origin != ? AND a.event_id IS NULL
            ORDER BY e.created_at ASC
            LIMIT ?
            """,
            (str(consumer), str(consumer), max(1, min(int(limit), 256))),
        ).fetchall()
    events = []
    for event_id, event_type, origin, payload_json, created_at in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            payload = {}
        events.append({
            "event_id": event_id,
            "event_type": event_type,
            "origin": origin,
            "payload": payload,
            "created_at": created_at,
        })
    return events


def acknowledge_event(consumer: str, event_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO cognitive_event_acks "
            "(consumer, event_id, acknowledged_at) VALUES (?, ?, ?)",
            (str(consumer), str(event_id), time.time()),
        )


def bridge_status(consumer: str = "") -> dict:
    with _connect() as connection:
        total = connection.execute("SELECT COUNT(*) FROM cognitive_events").fetchone()[0]
        if consumer:
            pending = connection.execute(
                """
                SELECT COUNT(*) FROM cognitive_events e
                LEFT JOIN cognitive_event_acks a
                  ON a.event_id=e.event_id AND a.consumer=?
                WHERE e.origin != ? AND a.event_id IS NULL
                """,
                (consumer, consumer),
            ).fetchone()[0]
        else:
            pending = None
    return {
        "database": str(DB_PATH),
        "total_events": total,
        "pending_for_consumer": pending,
    }
