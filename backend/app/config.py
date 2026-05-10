"""
全局配置读取 — 所有敏感信息通过 .env 注入，严禁硬编码。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Exchange
    EXCHANGE: str = "okx"
    OKX_API_KEY: str = ""
    OKX_SECRET_KEY: str = ""
    OKX_PASSPHRASE: str = ""
    BINANCE_API_KEY: str = ""
    BINANCE_SECRET_KEY: str = ""

    # Account
    INITIAL_CAPITAL: float = 10000.0

    # 模拟交易成本（贴近真实盘口）
    # 手续费率：默认 0.1%（类似币安/OKX 现货 maker/taker 的中位数）
    FEE_RATE: float = 0.001
    # 市价单滑点：成交价在当前价基础上 ±SLIPPAGE_PCT（买高卖低）
    # 默认 0.05%；限价单不应用滑点（用户已经指定价格）
    SLIPPAGE_PCT: float = 0.0005

    # DB
    DB_PATH: str = "./data.db"

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Server
    BACKEND_PORT: int = 8000

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
