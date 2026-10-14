from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    auth_mode: Literal["dev", "clerk"] = "dev"
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    database_url: str = "postgresql+asyncpg://sportreg:sportreg@localhost:5433/sportreg"
    test_database_url: str = (
        "postgresql+asyncpg://sportreg:sportreg@localhost:5433/sportreg_test"
    )
    qr_secret: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_startup(settings: Settings) -> None:
    """Refuse to boot in unsafe configurations."""
    if settings.env == "prod" and settings.auth_mode == "dev":
        raise RuntimeError("AUTH_MODE=dev is not allowed when ENV=prod")
