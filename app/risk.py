from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import RiskSnapshot


@dataclass
class RiskState:
    """Simple in-memory risk state for webhook execution."""

    open_positions: dict[str, float] = field(default_factory=dict)
    realized_pnl_today_usd: float = 0.0
    peak_equity_usd: float = 0.0
    current_equity_usd: float = 0.0
    blocked: bool = False
    current_day: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())

    def reset_if_new_day(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self.current_day:
            self.current_day = today
            self.realized_pnl_today_usd = 0.0
            self.blocked = False

    def update_equity(self, equity_usd: float) -> None:
        self.current_equity_usd = equity_usd
        if equity_usd > self.peak_equity_usd:
            self.peak_equity_usd = equity_usd

    def drawdown_pct(self) -> float:
        if self.peak_equity_usd <= 0:
            return 0.0
        drawdown = (self.peak_equity_usd - self.current_equity_usd) / self.peak_equity_usd
        return max(0.0, drawdown * 100.0)


class RiskManager:
    def __init__(
        self,
        *,
        max_notional_per_trade_usd: float,
        max_position_notional_usd: float,
        max_daily_loss_usd: float,
        max_open_positions: int,
        max_drawdown_pct: float,
        initial_equity_usd: float,
    ) -> None:
        self.max_notional_per_trade_usd = max_notional_per_trade_usd
        self.max_position_notional_usd = max_position_notional_usd
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_open_positions = max_open_positions
        self.max_drawdown_pct = max_drawdown_pct
        self.state = RiskState(
            peak_equity_usd=initial_equity_usd,
            current_equity_usd=initial_equity_usd,
        )

    def can_trade(self, product_id: str, side: str, notional_usd: float) -> tuple[bool, str]:
        self.state.reset_if_new_day()

        if self.state.blocked:
            return False, "Risk engine is blocked"

        if notional_usd <= 0:
            return False, "Notional must be > 0"

        if notional_usd > self.max_notional_per_trade_usd:
            return False, "Trade exceeds max_notional_per_trade_usd"

        if self.state.realized_pnl_today_usd <= -abs(self.max_daily_loss_usd):
            self.state.blocked = True
            return False, "Daily loss limit breached"

        if self.state.drawdown_pct() >= self.max_drawdown_pct:
            self.state.blocked = True
            return False, "Max drawdown breached"

        nonzero_positions = [v for v in self.state.open_positions.values() if abs(v) > 0]
        is_new_position = abs(self.state.open_positions.get(product_id, 0.0)) == 0.0
        if is_new_position and len(nonzero_positions) >= self.max_open_positions:
            return False, "Max open positions reached"

        projected_abs = abs(self.state.open_positions.get(product_id, 0.0))
        if side.lower() in {"buy", "sell"}:
            projected_abs += notional_usd
        if projected_abs > self.max_position_notional_usd:
            return False, "Position notional limit breached"

        return True, "ok"

    def on_fill(self, product_id: str, side: str, notional_usd: float, realized_pnl_usd: float = 0.0) -> None:
        position = self.state.open_positions.get(product_id, 0.0)
        if side.lower() == "buy":
            position += notional_usd
        elif side.lower() == "sell":
            position -= notional_usd
        elif side.lower() == "close":
            position = 0.0
        self.state.open_positions[product_id] = position
        self.state.realized_pnl_today_usd += realized_pnl_usd

    def snapshot(self) -> RiskSnapshot:
        self.state.reset_if_new_day()
        return RiskSnapshot(
            open_positions=self.state.open_positions,
            realized_pnl_today_usd=self.state.realized_pnl_today_usd,
            peak_equity_usd=self.state.peak_equity_usd,
            current_equity_usd=self.state.current_equity_usd,
            drawdown_pct=self.state.drawdown_pct(),
            blocked=self.state.blocked,
        )
