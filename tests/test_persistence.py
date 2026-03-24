import sqlite3
import time

from app.persistence import PersistenceStore


def test_risk_state_roundtrip(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    store = PersistenceStore(db_path=str(db_path), processed_alert_ttl_seconds=600)

    snapshot = {
        "open_positions": {"BTC-USD": 123.0},
        "realized_pnl_today_usd": -10.0,
        "peak_equity_usd": 1000.0,
        "current_equity_usd": 990.0,
        "drawdown_pct": 1.0,
        "blocked": False,
        "current_day": "2026-03-24",
    }
    store.save_risk_state(snapshot)
    loaded = store.load_risk_state()

    assert loaded is not None
    assert loaded["open_positions"] == {"BTC-USD": 123.0}
    assert loaded["realized_pnl_today_usd"] == -10.0
    assert loaded["current_day"] == "2026-03-24"


def test_idempotency_completion_roundtrip(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    store = PersistenceStore(db_path=str(db_path), processed_alert_ttl_seconds=600)

    key = "abc"
    can_process, existing = store.begin_alert_processing(
        alert_key=key,
        signal_id="sig-1",
        ts=1710000000,
        payload={"signal_id": "sig-1"},
    )
    assert can_process is True
    assert existing is None

    response = {"accepted": True, "message": "accepted", "order": {"status": "DRY_RUN"}}
    store.finalize_alert_processing(alert_key=key, response=response, status="accepted", message="accepted")

    can_process_2, existing_2 = store.begin_alert_processing(
        alert_key=key,
        signal_id="sig-1",
        ts=1710000000,
        payload={"signal_id": "sig-1"},
    )
    assert can_process_2 is False
    assert existing_2 is not None
    assert existing_2["response"] == response
    assert existing_2["status"] == "accepted"


def test_cleanup_expired_records(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    store = PersistenceStore(db_path=str(db_path), processed_alert_ttl_seconds=10)

    key = "old"
    store.begin_alert_processing(
        alert_key=key,
        signal_id="old",
        ts=100,
        payload={"signal_id": "old"},
    )
    store.finalize_alert_processing(alert_key=key, response={"ok": True}, status="accepted")

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE processed_alerts SET created_at = ?, updated_at = ? WHERE idempotency_key = ?",
            (int(time.time()) - 1000, int(time.time()) - 1000, key),
        )
        conn.commit()

    store.prune_old_alerts()

    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute("SELECT count(*) FROM processed_alerts WHERE idempotency_key = ?", (key,)).fetchone()
    assert row is not None
    assert row[0] == 0
