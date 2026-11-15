"""Application settings, loaded from environment variables / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "STELLAR Backend"
    environment: str = "dev"

    # SQLite by default so the API runs offline with no Docker (Plan B).
    # docker-compose overrides this with the PostgreSQL URL.
    database_url: str = "sqlite:///./stellar.db"

    # JWT
    jwt_secret: str = "change-me-in-.env"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 12 * 60

    # Account lockout (brute-force protection)
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # CORS: comma-separated list, "*" for the hackathon
    cors_origins: str = "*"

    # AI integration: "auto" = use real team modules in ai_modules/ if present, else stubs
    ai_mode: str = "auto"

    # Simulated space-to-ground link (seconds of one-way delay)
    comm_delay_seconds: float = 2.0
    comm_link_enabled: bool = True

    # Seed demo data on startup
    seed_on_startup: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
