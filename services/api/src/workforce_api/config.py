from functools import lru_cache
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "development", "staging", "production"]
DEV_AUTH_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test"})


class Settings(BaseSettings):
    """Runtime configuration, read from WORKFORCE_* environment variables.

    Secrets are never given defaults here. In AWS they come from Secrets Manager
    through the task definition, not from files in the image.
    """

    model_config = SettingsConfigDict(env_prefix="WORKFORCE_", env_file=".env", extra="ignore")

    env: Environment = "local"
    log_level: str = "INFO"
    # The API's login role: a member of `workforce_app`, subject to row-level security.
    database_url: str = "postgresql+asyncpg://workforce_api:workforce_api@localhost:5432/workforce"
    # The schema owner, used only by Alembic. Never used by the running API.
    migration_database_url: str = (
        "postgresql+asyncpg://workforce:workforce@localhost:5432/workforce"
    )
    cors_origins: list[str] = ["http://localhost:3000"]

    # Authentication (ADR-0008).
    # "oidc": validate tokens from an external issuer (Cognito in AWS) against its JWKS.
    # "dev": the API issues its own tokens. Allowed only in local and test environments.
    auth_mode: Literal["oidc", "dev"] = "dev"
    auth_issuer: str = "workforce-dev"
    auth_audience: str = "workforce-api"
    # Defaults to {auth_issuer}/.well-known/jwks.json, which is where Cognito publishes keys.
    auth_jwks_url: str | None = None
    auth_clock_skew_seconds: int = 30

    # Who may create organisations through the API. "closed" (the safe default) means only
    # operators can, out of band; "open" lets any signed-in user create one and become its
    # org admin. Local development and tests use "open".
    organisation_creation: Literal["open", "closed"] = "closed"

    @model_validator(mode="after")
    def _dev_auth_only_where_safe(self) -> Self:
        if self.auth_mode == "dev" and self.env not in DEV_AUTH_ENVIRONMENTS:
            raise ValueError(
                f"auth_mode 'dev' is not allowed when env is '{self.env}'. Use 'oidc'."
            )
        return self

    @property
    def jwks_url(self) -> str:
        return self.auth_jwks_url or f"{self.auth_issuer.rstrip('/')}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
