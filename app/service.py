from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .coinbase_client import CoinbaseClient
from .models import TVAlert
from .persistence import PersistenceStore
from .risk import RiskManager


@dataclass
class TradingService:
    webhook_secret: str
    coinbase: CoinbaseClient
    risk: RiskManager
    store: PersistenceStore
    trading_enabled: bool = False
    dry_run: bool = True
    replay_window_seconds: int = 300
    logger: logging.Logger = logging.getLogger("trading.service")

    async def handle_signal(self, alert: TVAlert) -> tuple[bool, str, dict[str, Any]]:
        if alert.secret != self.webhook_secret:
            return False, "invalid secret", {}

        alert_key = self._alert_key(alert)
        inserted, prior_response = self.store.begin_alert_processing(
            alert_key=alert_key,
            signal_id=alert.signal_id,
            ts=alert.ts,
            payload=alert.model_dump(),
        )
        if not inserted:
            if prior_response is None:
                return False, "alert already processing", {}
            if prior_response.get("status") == "processing":
                return False, "alert already processing", {}
            if prior_response.get("status") == "accepted":
                return True, "duplicate", prior_response.get("response", {})
            return False, prior_response.get("message") or "duplicate rejected", prior_response.get("response", {})

        if self._is_stale(alert.ts):
            result = {"status": "REJECTED", "reason": "stale alert timestamp"}
            self.store.finalize_alert_processing(
                alert_key=alert_key,
                response=result,
                status="rejected",
                message="stale alert timestamp",
            )
            return False, "stale alert timestamp", result

        side = alert.side.lower()
        allowed, reason = self.risk.can_trade(product_id=alert.product_id, side=side, notional_usd=alert.qty_usd)
        if not allowed:
            result = {"status": "REJECTED", "reason": reason, "risk": self.risk.snapshot().model_dump()}
            self.store.finalize_alert_processing(
                alert_key=alert_key,
                response=result,
                status="rejected",
                message=reason,
            )
            return False, reason, result

        if not self.trading_enabled:
            order_id = f"sim-disabled-{uuid4().hex[:12]}"
            result = self._build_sim_result(
                alert=alert,
                order_id=order_id,
                reason="trading_disabled",
            )
            self.store.finalize_alert_processing(
                alert_key=alert_key,
                response=result,
                status="accepted",
                message="accepted",
            )
            return True, "accepted", result

        if self.dry_run:
            order_id = f"sim-dry-run-{uuid4().hex[:12]}"
            result = self._build_sim_result(
                alert=alert,
                order_id=order_id,
                reason="dry_run",
            )
            self.store.finalize_alert_processing(
                alert_key=alert_key,
                response=result,
                status="accepted",
                message="accepted",
            )
            return True, "accepted", result

        client_order_id = f"tv-{alert.strategy}-{uuid4().hex[:12]}"
        response = await self.coinbase.create_market_order(
            side=alert.side,
            product_id=alert.product_id,
            quote_size=alert.qty_usd,
            client_order_id=client_order_id,
        )
        if not response["success"]:
            result = {"status": "REJECTED", "reason": response["reason"], "coinbase": response["raw"]}
            self.store.finalize_alert_processing(
                alert_key=alert_key,
                response=result,
                status="rejected",
                message=response["reason"] or "Coinbase order rejected",
            )
            return False, response["reason"] or "Coinbase order rejected", result

        self.risk.on_fill(product_id=alert.product_id, side=side, notional_usd=alert.qty_usd)
        result = {
            "status": "LIVE",
            "mode": "live",
            "success": True,
            "order_id": response["order_id"],
            "client_order_id": client_order_id,
            "coinbase": response["raw"],
            "risk": self.risk.snapshot().model_dump(),
        }
        self.store.finalize_alert_processing(
            alert_key=alert_key,
            response=result,
            status="accepted",
            message="accepted",
        )
        return True, "accepted", result

    def _build_sim_result(self, alert: TVAlert, order_id: str, reason: str) -> dict[str, Any]:
        self.risk.on_fill(product_id=alert.product_id, side=alert.side.lower(), notional_usd=alert.qty_usd)
        return {
            "status": "DRY_RUN",
            "mode": "paper",
            "success": True,
            "order_id": order_id,
            "reason": reason,
            "ts": int(time.time()),
            "signal": alert.model_dump(),
            "risk": self.risk.snapshot().model_dump(),
        }

    def _is_stale(self, ts: int) -> bool:
        now = int(time.time())
        return abs(now - ts) > self.replay_window_seconds

    def _alert_key(self, alert: TVAlert) -> str:
        if alert.signal_id:
            return f"signal:{alert.signal_id}"
        canonical = json.dumps(
            {
                "strategy": alert.strategy,
                "action": alert.action,
                "symbol": alert.symbol,
                "product_id": alert.product_id,
                "side": alert.side,
                "qty_usd": alert.qty_usd,
                "timeframe": alert.timeframe,
                "ts": alert.ts,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"hash:{digest}"
