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
        "ts": 1710000000,
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
