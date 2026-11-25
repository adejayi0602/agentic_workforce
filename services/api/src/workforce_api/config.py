from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from WORKFORCE_* environment variables.

    Secrets are never given defaults here. In AWS they come from Secrets Manager
    through the task definition, not from files in the image.
    """

    model_config = SettingsConfigDict(env_prefix="WORKFORCE_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "development", "staging", "production"] = "local"
    log_level: str = "INFO"
    # The API's login role: a member of `workforce_app`, subject to row-level security.
    database_url: str = "postgresql+asyncpg://workforce_api:workforce_api@localhost:5432/workforce"
    # The schema owner, used only by Alembic. Never used by the running API.
    migration_database_url: str = (
        "postgresql+asyncpg://workforce:workforce@localhost:5432/workforce"
    )
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
