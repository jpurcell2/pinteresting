import time

from fastapi.testclient import TestClient

from app.main import app


def _payload(**overrides):
    base = {
        "secret": "change-me-now",
        "action": "BUY",
        "symbol": "COINBASE:BTCUSD",
        "product_id": "BTC-USD",
        "side": "BUY",
        "qty_usd": 100.0,
        "strategy": "arch-style",
        "timeframe": "15",
        "ts": int(time.time()),
    }
    base.update(overrides)
    return base


def test_webhook_rejects_bad_secret():
    with TestClient(app) as client:
        payload = _payload(secret="wrong-secret")
        response = client.post("/webhook/tradingview", json=payload)
        assert response.status_code == 401
        assert "invalid secret" in response.text.lower()


def test_webhook_accepts_in_dry_run_mode():
    with TestClient(app) as client:
        payload = _payload()
        response = client.post("/webhook/tradingview", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"] is True
        assert body["order"]["status"] == "DRY_RUN"


def test_webhook_is_idempotent_for_duplicate_signal():
    with TestClient(app) as client:
        payload = _payload(signal_id="dup-1")
        first = client.post("/webhook/tradingview", json=payload)
        second = client.post("/webhook/tradingview", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        first_body = first.json()
        second_body = second.json()
        assert first_body["accepted"] is True
        assert second_body["accepted"] is True
        assert second_body["message"] == "duplicate"
        assert first_body["order"]["order_id"] == second_body["order"]["order_id"]


def test_webhook_rejects_replayed_stale_timestamp():
    with TestClient(app) as client:
        payload = _payload(signal_id="old-sig", ts=1)
        response = client.post("/webhook/tradingview", json=payload)
        assert response.status_code == 400
        assert "stale alert timestamp" in response.text.lower()
