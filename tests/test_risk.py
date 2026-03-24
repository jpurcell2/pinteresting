from app.risk import RiskManager


def _engine() -> RiskManager:
    return RiskManager(
        max_notional_per_trade_usd=100.0,
        max_position_notional_usd=500.0,
        max_daily_loss_usd=100.0,
        max_open_positions=2,
        max_drawdown_pct=10.0,
        initial_equity_usd=1000.0,
    )


def test_rejects_when_notional_exceeds_limit() -> None:
    engine = _engine()
    allowed, reason = engine.can_trade("BTC-USD", "buy", 150.0)
    assert not allowed
    assert "per-trade" in reason


def test_rejects_when_daily_loss_limit_breached() -> None:
    engine = _engine()
    engine.on_fill("BTC-USD", "buy", 100.0, realized_pnl_usd=-150.0)
    allowed, reason = engine.can_trade("BTC-USD", "buy", 50.0)
    assert not allowed
    assert "Daily loss" in reason

