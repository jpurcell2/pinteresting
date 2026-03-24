from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class PersistenceStore:
    """SQLite-backed storage for risk snapshots and alert idempotency."""

    def __init__(self, db_path: str, *, processed_alert_ttl_seconds: int = 7 * 24 * 60 * 60) -> None:
        self.db_path = db_path
        self.processed_alert_ttl_seconds = max(60, int(processed_alert_ttl_seconds))
        self._lock = threading.Lock()
        self._conn = self._connect(db_path)
        self._init_schema()

    def _connect(self, db_path: str) -> sqlite3.Connection:
        path = Path(db_path)
        if path.parent and str(path.parent) not in {"", "."}:
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    current_day TEXT NOT NULL,
                    open_positions_json TEXT NOT NULL,
                    realized_pnl_today_usd REAL NOT NULL,
                    peak_equity_usd REAL NOT NULL,
                    current_equity_usd REAL NOT NULL,
                    blocked INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_alerts (
                    idempotency_key TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    alert_ts INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_processed_alerts_created_at
                ON processed_alerts (created_at)
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def prune_old_alerts(self) -> None:
        cutoff = int(time.time()) - self.processed_alert_ttl_seconds
        with self._lock:
            self._conn.execute("DELETE FROM processed_alerts WHERE created_at < ?", (cutoff,))
            self._conn.commit()

    def begin_alert_processing(
        self,
        *,
        alert_key: str,
        signal_id: str,
        ts: int,
        payload: dict[str, Any],
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        Try to reserve an idempotency key.
        - Returns (True, None) if caller should process this alert.
        - Returns (False, record) if duplicate key already exists.
        """
        now = int(time.time())
        self.prune_old_alerts()
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO processed_alerts (
                        idempotency_key, signal_id, alert_ts, payload_json,
                        status, message, response_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (alert_key, signal_id or "", int(ts), payload_json, "processing", "", "{}", now, now),
                )
                self._conn.commit()
                return True, None
            except sqlite3.IntegrityError:
                row = self._conn.execute(
                    "SELECT * FROM processed_alerts WHERE idempotency_key = ?",
                    (alert_key,),
                ).fetchone()
                if row is None:
                    return False, None
                return False, self._row_to_alert_record(row)

    def finalize_alert_processing(
        self,
        *,
        alert_key: str,
        response: dict[str, Any],
        status: str,
        message: str = "",
    ) -> None:
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                """
                UPDATE processed_alerts
                SET status = ?, message = ?, response_json = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (
                    status,
                    message,
                    json.dumps(response, separators=(",", ":"), sort_keys=True),
                    now,
                    alert_key,
                ),
            )
            self._conn.commit()

    def load_risk_state(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM risk_state WHERE id = 1").fetchone()
        if row is None:
            return None
        return {
            "current_day": row["current_day"],
            "open_positions": json.loads(row["open_positions_json"]),
            "realized_pnl_today_usd": float(row["realized_pnl_today_usd"]),
            "peak_equity_usd": float(row["peak_equity_usd"]),
            "current_equity_usd": float(row["current_equity_usd"]),
            "blocked": bool(row["blocked"]),
        }

    def save_risk_state(self, state: dict[str, Any]) -> None:
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO risk_state (
                    id, current_day, open_positions_json, realized_pnl_today_usd,
                    peak_equity_usd, current_equity_usd, blocked, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    current_day = excluded.current_day,
                    open_positions_json = excluded.open_positions_json,
                    realized_pnl_today_usd = excluded.realized_pnl_today_usd,
                    peak_equity_usd = excluded.peak_equity_usd,
                    current_equity_usd = excluded.current_equity_usd,
                    blocked = excluded.blocked,
                    updated_at = excluded.updated_at
                """,
                (
                    state["current_day"],
                    json.dumps(state["open_positions"], separators=(",", ":"), sort_keys=True),
                    float(state["realized_pnl_today_usd"]),
                    float(state["peak_equity_usd"]),
                    float(state["current_equity_usd"]),
                    1 if state["blocked"] else 0,
                    now,
                ),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_alert_record(row: sqlite3.Row) -> dict[str, Any]:
        try:
            response = json.loads(row["response_json"])
        except json.JSONDecodeError:
            response = {}
        return {
            "key": row["idempotency_key"],
            "signal_id": row["signal_id"],
            "status": row["status"],
            "message": row["message"],
            "response": response,
        }
