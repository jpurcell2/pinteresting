from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8080
    log_level: str = "INFO"

    webhook_secret: str = Field(default="change-me-now", min_length=8)
    trading_enabled: bool = False
    dry_run: bool = True

    coinbase_api_key_name: str = ""
    coinbase_private_key_pem: str = ""
    coinbase_api_base_url: str = "https://api.coinbase.com"
    coinbase_timeout_seconds: float = 10.0
    default_product_id: str = "BTC-USD"

    sqlite_db_path: str = "data/bot.db"
    replay_window_seconds: int = 600
    idempotency_ttl_seconds: int = 72 * 60 * 60

    max_notional_per_trade_usd: float = 500.0
    max_position_notional_usd: float = 2500.0
    max_daily_loss_usd: float = 750.0
    max_open_positions: int = 2
    max_drawdown_pct: float = 8.0
    initial_equity_usd: float = 100000.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
