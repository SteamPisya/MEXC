# MEXC Futures Scanner Configuration
# Stackable Consolidations Pattern Bot

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExchangeConfig(BaseSettings):
    """MEXC Exchange configuration"""
    api_key: str = Field(default="", description="MEXC API Key")
    api_secret: str = Field(default="", description="MEXC API Secret")
    rate_limit_ms: int = Field(default=250, description="Rate limit in milliseconds")
    enable_rate_limit: bool = Field(default=True, description="Enable CCXT rate limiting")
    max_concurrent_requests: int = Field(default=5, description="Maximum concurrent requests")
    fetch_retries: int = Field(default=3, description="Number of retries on failure")
    default_timeframe: str = Field(default="15m", description="Default timeframe for scanning")
    candles_limit: int = Field(default=500, description="Number of candles to fetch")


class PatternConfig(BaseSettings):
    """Pattern detection parameters"""
    min_amplitude_pct: float = Field(default=0.5, description="Minimum amplitude percentage")
    max_amplitude_pct: float = Field(default=3.0, description="Maximum amplitude percentage")
    min_consolidation_length: int = Field(default=5, description="Minimum consolidation candles")
    y_gap_pct: float = Field(default=0.3, description="Vertical gap between consolidations (%)")
    x_gap_candles: int = Field(default=3, description="Horizontal gap between consolidations")
    max_candles_after: int = Field(default=10, description="Max candles after pattern for entry")


class TradingConfig(BaseSettings):
    """Trading parameters"""
    tp_percent: float = Field(default=2.0, description="Take profit percentage")
    sl_percent: float = Field(default=1.0, description="Stop loss percentage")
    risk_reward_ratio: float = Field(default=2.0, description="Risk/Reward ratio")


class TelegramConfig(BaseSettings):
    """Telegram Bot configuration"""
    bot_token: str = Field(default="", description="Telegram Bot Token")
    chat_id: int = Field(default=0, description="Telegram Chat ID for notifications")
    timeout_seconds: int = Field(default=30, description="Request timeout")
    retry_count: int = Field(default=3, description="Number of retries on send failure")


class DatabaseConfig(BaseSettings):
    """SQLite Database configuration"""
    db_path: str = Field(default="signals.db", description="Database file path")
    wal_mode: bool = Field(default=True, description="Enable WAL mode")
    synchronous_normal: bool = Field(default=True, description="Use NORMAL synchronous mode")


class BotConfig(BaseSettings):
    """Main bot configuration"""
    scan_interval_minutes: int = Field(default=1, description="Scan interval in minutes")
    quote_currency: str = Field(default="USDT", description="Quote currency filter")
    log_level: str = Field(default="INFO", description="Logging level")
    log_file: str = Field(default="bot.log", description="Log file path")
    chart_timeout_seconds: int = Field(default=15, description="Chart generation timeout")
    chart_workers: int = Field(default=2, description="Chart generator workers")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class Config(BaseSettings):
    """Main configuration container"""
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    pattern: PatternConfig = Field(default_factory=PatternConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    bot: BotConfig = Field(default_factory=BotConfig)

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment and files"""
        return cls()


# Default instance
config = Config.load()
