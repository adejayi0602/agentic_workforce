from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKFORCE_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "development", "staging", "production"] = "local"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "workforce-main"

    # The worker's own login role: a member of `workforce_worker`, subject to RLS.
    worker_database_url: str = (
        "postgresql+asyncpg://workforce_worker_login:workforce_worker@localhost:5432/workforce"
    )
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "eu-west-1"
    s3_bucket_artefacts: str = "workforce-artefacts"

    # "guardduty" in AWS. "eicar" detects only the antivirus test file: local and test only.
    scanner: Literal["eicar", "guardduty"] = "eicar"

    @model_validator(mode="after")
    def _real_scanning_outside_local(self) -> Self:
        if self.scanner == "eicar" and self.env not in {"local", "test"}:
            raise ValueError(
                f"scanner 'eicar' is a test scanner and is not allowed when env is '{self.env}'."
            )
        return self
