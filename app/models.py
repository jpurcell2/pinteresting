from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TVAlert(BaseModel):
    """TradingView webhook payload consumed by the API."""

    secret: str = Field(min_length=8)
    signal_id: str = Field(default="", description="Idempotency key from TradingView.")
    strategy: str = Field(default="arch-style-hf")
    action: Literal["BUY", "SELL", "EXIT_LONG", "EXIT_SHORT"] = "BUY"
    symbol: str = Field(default="COINBASE:BTCUSD")
    product_id: str = Field(default="BTC-USD")
    side: Literal["BUY", "SELL"] = "BUY"
    qty_usd: float = Field(gt=0.0, description="Order notional in USD")
    price: float = Field(default=0.0, ge=0.0)
    timeframe: str = Field(default="")
    ts: int = Field(default_factory=lambda: int(datetime.now(tz=timezone.utc).timestamp()))
    regime: str = Field(default="trend")
    reason: str = Field(default="")
    client_order_id: str = Field(default="")

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, value: str) -> str:
        return str(value).upper()

    @field_validator("side", mode="before")
    @classmethod
    def normalize_side(cls, value: str) -> str:
        return str(value).upper()

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, value: str) -> str:
        product = value.upper().strip()
        if "-" not in product:
            raise ValueError("product_id must look like BTC-USD")
        return product


class HealthResponse(BaseModel):
    status: Literal["ok"]
    trading_enabled: bool
    dry_run: bool


class RiskSnapshot(BaseModel):
    open_positions: dict[str, float]
    realized_pnl_today_usd: float
    peak_equity_usd: float
    current_equity_usd: float
    drawdown_pct: float
    blocked: bool


class PersistedAlertRecord(BaseModel):
    key: str
    signal_id: str
    status: Literal["processing", "accepted", "rejected"]
    message: str
    response: dict

