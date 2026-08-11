from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "InventoryOS"
    api_v1_prefix: str = "/api/v1"

    database_url: str = (
        "postgresql+asyncpg://inventory:inventory_dev_password@localhost:5432/inventory_os"
    )
    test_database_url: str = (
        "postgresql+asyncpg://inventory:inventory_dev_password@localhost:5432/inventory_os_test"
    )

    jwt_secret: str = "change-me-to-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    demo_org_name: str = "华东精密制造有限公司"
    demo_org_slug: str = "huadong-precision"
    demo_admin_email: str = "admin@inventoryos.local"
    demo_admin_password: str = "Demo@12345"

    ai_provider: str = "demo"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""

    market_provider: str = "mock"

    frontend_origin: str = "http://localhost:5173"

    # Integration event replay guard: max events processed in one batch.
    sse_poll_interval_seconds: float = 2.0
    sse_heartbeat_seconds: float = 15.0

    # Inventory health engine thresholds
    health_horizon_days: int = 7
    health_overstock_days_threshold: int = 180
    health_dormant_days: int = 30
    health_expiry_days: int = 30
    health_score_weights: dict[str, int] = {
        "CRITICAL": 25,
        "HIGH": 15,
        "MEDIUM": 8,
        "LOW": 3,
        "INFO": 1,
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
