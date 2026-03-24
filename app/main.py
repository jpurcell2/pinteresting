import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from .config import get_settings
from .coinbase_client import CoinbaseClient
from .models import HealthResponse, RiskSnapshot, TVAlert
from .persistence import PersistenceStore
from .risk import RiskManager
from .service import TradingService


logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.info("starting crypto bot API")
    persistence = PersistenceStore(
        db_path=settings.sqlite_db_path,
        processed_alert_ttl_seconds=settings.idempotency_ttl_seconds,
    )
    risk = RiskManager(
        max_notional_per_trade_usd=settings.max_notional_per_trade_usd,
        max_position_notional_usd=settings.max_position_notional_usd,
        max_daily_loss_usd=settings.max_daily_loss_usd,
        max_open_positions=settings.max_open_positions,
        max_drawdown_pct=settings.max_drawdown_pct,
        initial_equity_usd=settings.initial_equity_usd,
        store=persistence,
    )
    coinbase = CoinbaseClient(
        api_base_url=settings.coinbase_api_base_url,
        api_key_name=settings.coinbase_api_key_name,
        private_key_pem=settings.coinbase_private_key_pem,
        timeout_seconds=settings.coinbase_timeout_seconds,
    )
    service = TradingService(
        webhook_secret=settings.webhook_secret,
        coinbase=coinbase,
        risk=risk,
        store=persistence,
        trading_enabled=settings.trading_enabled,
        dry_run=settings.dry_run,
        replay_window_seconds=settings.replay_window_seconds,
    )
    app.state.trading_service = service
    yield
    persistence.close()
    logger.info("stopped crypto bot API")


app = FastAPI(title="TradingView -> Coinbase Bot API", version="0.1.0", lifespan=lifespan)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", trading_enabled=settings.trading_enabled, dry_run=settings.dry_run)


@app.get("/risk", response_model=RiskSnapshot)
async def risk() -> RiskSnapshot:
    service: TradingService = app.state.trading_service
    return service.risk.snapshot()


@app.post("/webhook/tradingview")
async def webhook(alert: TVAlert):
    service: TradingService = app.state.trading_service
    accepted, message, order = await service.handle_signal(alert)
    if not accepted:
        code = status.HTTP_401_UNAUTHORIZED if "secret" in message.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=message)
    return {"accepted": True, "message": message, "order": order}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
