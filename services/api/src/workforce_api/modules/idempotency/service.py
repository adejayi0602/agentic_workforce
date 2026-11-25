"""Idempotent mutations.

Flow, all inside the request's transaction:

1. `reserve` inserts the key as in_progress. If another request holds the same key and is
   still running, PostgreSQL makes this insert wait on the unique index until that
   transaction ends, so concurrent retries never both do the work.
2. If the key already exists: a different request body is refused
   (IDEMPOTENCY_KEY_REUSED); a completed one returns the stored response.
3. The handler does the work, then `complete` stores the response.

If the work fails, the transaction rolls back and takes the reservation with it, so the client
can retry with the same key.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.errors import ApiError
from workforce_api.modules.idempotency.models import IdempotencyKey
from workforce_contracts import ErrorCode

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"


@dataclass(frozen=True)
class Reservation:
    organisation_id: uuid.UUID
    user_id: uuid.UUID
    key: str


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def request_hash(body: BaseModel) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def reserve(
    session: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    operation: str,
    body: BaseModel,
) -> Reservation | StoredResponse:
    """Reserve the key, or return the response already stored for it."""
    if not 8 <= len(key) <= 200:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"{IDEMPOTENCY_HEADER} must be 8 to 200 characters.",
            status_code=400,
            details={"header": IDEMPOTENCY_HEADER},
        )
    digest = request_hash(body)
    inserted = await session.scalar(
        insert(IdempotencyKey)
        .values(
            organisation_id=organisation_id,
            user_id=user_id,
            key=key,
            operation=operation,
            request_hash=digest,
            status="in_progress",
        )
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    )
    if inserted is not None:
        return Reservation(organisation_id=organisation_id, user_id=user_id, key=key)

    existing = await session.get(
        IdempotencyKey, (organisation_id, user_id, key), populate_existing=True
    )
    if existing is None:  # pragma: no cover - only if the row vanished between statements
        raise ApiError(ErrorCode.CONFLICT, "Please retry the request.", status_code=409)
    if existing.operation != operation or existing.request_hash != digest:
        raise ApiError(
            ErrorCode.IDEMPOTENCY_KEY_REUSED,
            "This idempotency key was already used for a different request.",
            status_code=422,
            details={"header": IDEMPOTENCY_HEADER},
        )
    if existing.status != "completed" or existing.response_body is None:  # pragma: no cover
        raise ApiError(ErrorCode.CONFLICT, "The original request is still running.", 409)
    return StoredResponse(status_code=existing.response_status or 200, body=existing.response_body)


async def complete(
    session: AsyncSession, reservation: Reservation, *, status_code: int, body: BaseModel
) -> None:
    row = await session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.organisation_id == reservation.organisation_id,
            IdempotencyKey.user_id == reservation.user_id,
            IdempotencyKey.key == reservation.key,
        )
    )
    assert row is not None  # noqa: S101 - reserved in this same transaction
    row.status = "completed"
    row.response_status = status_code
    row.response_body = body.model_dump(mode="json")
    await session.flush()
