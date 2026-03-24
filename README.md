# Hedge-Fund Style Crypto Bot (TradingView Strategy + Coinbase API)

This repository contains a full starter implementation of an "Arch Public style" crypto execution stack:

- a **TradingView Pine strategy** with institutional-style risk controls and JSON webhook alerts
- a **FastAPI webhook service** that validates signals, enforces server-side risk rules, and submits market IOC orders to Coinbase Advanced Trade

> Educational software only. Not investment advice.

## What is included

- `tradingview/arch_style_bot.pine`  
  Pine v5 strategy with:
  - EMA trend regime and momentum filter
  - ATR-based stop and take-profit
  - optional shorting
  - dynamic position sizing by risk %
  - JSON `alert()` payloads for webhook execution

- `app/main.py`  
  API endpoints:
  - `GET /health`
  - `GET /risk`
  - `POST /webhook/tradingview`

- `app/service.py`  
  Signal validation + risk checks + idempotency + dry-run/live order routing.

- `app/risk.py`  
  Risk manager:
  - max notional per trade
  - max notional per symbol position
  - max open symbols
  - max daily realized loss
  - max drawdown from equity high-water mark
  - persisted state to survive restarts

- `app/persistence.py`
  SQLite-backed persistence:
  - risk state snapshots
  - webhook idempotency records
  - replay window enforcement support

- `app/coinbase_client.py`  
  Coinbase Advanced Trade REST client using JWT Bearer auth and market IOC order placement.

- `tests/`  
  Risk and webhook tests.

## Quick start

### 1) Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure env

```bash
cp .env.example .env
```

Set at minimum:

- `WEBHOOK_SECRET` (must match TradingView alert payload)
- `TRADING_ENABLED=false` and `DRY_RUN=true` for safe initial testing
- Coinbase credentials for live mode:
  - `COINBASE_API_KEY_NAME`
  - `COINBASE_PRIVATE_KEY_PEM`
- persistence/replay settings:
  - `SQLITE_DB_PATH`
  - `REPLAY_WINDOW_SECONDS`

### 3) Run API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Check:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/risk
```

### 4) Add strategy in TradingView

1. Open Pine Editor.
2. Paste `tradingview/arch_style_bot.pine`.
3. Save and add to chart.
4. Create an alert with condition **Any alert() function call**.
5. Set webhook URL to:
   - `https://<your-host>/webhook/tradingview`

The strategy emits JSON payloads with fields such as:

```json
{
  "secret": "change-me-now",
  "signal_id": "tv-12345",
  "action": "BUY",
  "symbol": "COINBASE:BTCUSD",
  "product_id": "BTC-USD",
  "side": "BUY",
  "qty_usd": 250,
  "strategy": "arch-style-hf-bot",
  "timeframe": "60",
  "ts": 1710000000
}
```

`signal_id` is strongly recommended for deterministic idempotency. If omitted, the API falls back to a stable hash of key alert fields.

## Stateful persistence + replay protection

This implementation now includes:

- **SQLite stateful persistence** (`SQLITE_DB_PATH`, default `data/bot.db`)
  - risk state is saved and reloaded on startup
  - processed alerts are recorded with status/result
- **Idempotency**
  - duplicate `signal_id` (or fallback derived key) returns the original stored result without re-executing
- **Replay protection**
  - alert timestamps older than `REPLAY_WINDOW_SECONDS` are rejected
  - future timestamps beyond a small clock-skew allowance are rejected

## Live trading safety checklist

1. Start with `TRADING_ENABLED=false` and verify alerts are accepted.
2. Keep `TRADING_ENABLED=true` but `DRY_RUN=true` and monitor for a few sessions.
3. Switch to `DRY_RUN=false` only after:
   - secrets are strong
   - TLS is enabled (reverse proxy + HTTPS)
   - risk limits are tuned small
4. Monitor `/risk` continuously.

## TradingView alert setup

1. Paste `tradingview/arch_style_bot.pine` into the Pine editor and add to chart.
2. Open **Alerts** and choose condition **Any alert() function call**.
3. Set webhook URL to `https://<your-host>/webhook/tradingview`.
4. Leave alert message blank because the script emits full JSON via `alert()`.

## Running tests

```bash
pytest -q
```

## Production hardening (recommended next)

- migrate SQLite to managed Postgres/Redis for multi-instance concurrency
- reconcile fills/positions from Coinbase periodically
- add structured logs and metrics (Prometheus + alerting)
- add canary mode for tiny notional before scaling
