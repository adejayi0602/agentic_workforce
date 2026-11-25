from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from workforce_api import __version__
from workforce_api.db import Database
from workforce_api.errors import ApiError
from workforce_contracts import ErrorCode

router = APIRouter(prefix="/health", tags=["health"])

DatabaseCheck = Callable[[], Awaitable[bool]]


def get_database_check(request: Request) -> DatabaseCheck:
    database: Database = request.app.state.database
    return database.ping


class Liveness(BaseModel):
    status: Literal["ok"]
    version: str


class Readiness(BaseModel):
    status: Literal["ready"]
    checks: dict[str, bool]


@router.get("", response_model=Liveness)
async def liveness() -> Liveness:
    """The process is up. Has no dependencies, so the load balancer never kills a healthy task."""
    return Liveness(status="ok", version=__version__)


@router.get("/ready", response_model=Readiness)
async def readiness(
    database_check: Annotated[DatabaseCheck, Depends(get_database_check)],
) -> Readiness:
    """Dependencies are reachable. Returns 503 with the failing checks otherwise."""
    checks = {"database": await database_check()}
    if not all(checks.values()):
        raise ApiError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "One or more dependencies are unavailable.",
            status_code=503,
            details={"checks": checks},
        )
    return Readiness(status="ready", checks=checks)
