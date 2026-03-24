from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .coinbase_client import CoinbaseClient
from .models import TVAlert
from .risk import RiskManager


@dataclass
class TradingService:
    webhook_secret: str
    coinbase: CoinbaseClient
    risk: RiskManager
    trading_enabled: bool = False
    dry_run: bool = True
    logger: logging.Logger = logging.getLogger("trading.service")

    @classmethod
    def from_settings(
        cls,
        *,
        webhook_secret: str,
        trading_enabled: bool,
        dry_run: bool,
        coinbase_base_url: str,
        coinbase_api_key_name: str,
        coinbase_private_key_pem: str,
        coinbase_timeout_seconds: float,
        max_notional_per_trade_usd: float,
        max_position_notional_usd: float,
        max_daily_loss_usd: float,
        max_open_positions: int,
        max_drawdown_pct: float,
        initial_equity_usd: float,
    ) -> "TradingService":
        coinbase = CoinbaseClient(
            api_base_url=coinbase_base_url,
            api_key_name=coinbase_api_key_name,
            private_key_pem=coinbase_private_key_pem,
            timeout_seconds=coinbase_timeout_seconds,
        )
        risk = RiskManager(
            max_notional_per_trade_usd=max_notional_per_trade_usd,
            max_position_notional_usd=max_position_notional_usd,
            max_daily_loss_usd=max_daily_loss_usd,
            max_open_positions=max_open_positions,
            max_drawdown_pct=max_drawdown_pct,
            initial_equity_usd=initial_equity_usd,
        )
        return cls(
            webhook_secret=webhook_secret,
            coinbase=coinbase,
            risk=risk,
            trading_enabled=trading_enabled,
            dry_run=dry_run,
        )

    async def handle_signal(self, alert: TVAlert) -> tuple[bool, str, dict[str, Any]]:
        if alert.secret != self.webhook_secret:
            return False, "invalid secret", {}

        side = alert.side.lower()
        allowed, reason = self.risk.can_trade(product_id=alert.product_id, side=side, notional_usd=alert.qty_usd)
        if not allowed:
            return False, reason, {"risk": self.risk.snapshot().model_dump()}

        if not self.trading_enabled:
            order_id = f"sim-disabled-{uuid4().hex[:12]}"
            result = self._build_sim_result(
                alert=alert,
                order_id=order_id,
                reason="trading_disabled",
            )
            return True, "accepted", result

        if self.dry_run:
            order_id = f"sim-dry-run-{uuid4().hex[:12]}"
            result = self._build_sim_result(
                alert=alert,
                order_id=order_id,
                reason="dry_run",
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
            return False, response["reason"] or "Coinbase order rejected", {"coinbase": response["raw"]}

        self.risk.on_fill(product_id=alert.product_id, side=side, notional_usd=alert.qty_usd)
        return True, "accepted", {
            "status": "LIVE",
            "mode": "live",
            "order_id": response["order_id"],
            "client_order_id": client_order_id,
            "coinbase": response["raw"],
            "risk": self.risk.snapshot().model_dump(),
        }

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
