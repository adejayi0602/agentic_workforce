"""Cursor pagination (spec §6): stable under inserts, opaque to clients.

The cursor encodes the (created_at, id) of the last item returned. Results are ordered
newest first by (created_at DESC, id DESC), so the next page is everything strictly after it.
"""

import base64
import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from workforce_api.errors import ApiError
from workforce_contracts import ErrorCode

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


class PageParams(BaseModel):
    limit: int
    after: tuple[datetime, uuid.UUID] | None


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(item_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, item_id = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(created), uuid.UUID(item_id)
    except (ValueError, TypeError) as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "The cursor is not valid.",
            status_code=400,
            details={"parameter": "cursor"},
        ) from exc


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
) -> PageParams:
    return PageParams(limit=limit, after=decode_cursor(cursor) if cursor else None)
