"""Correlation IDs (spec §4 Observability, §6).

Every request gets a correlation ID. It is taken from the X-Correlation-ID header when that
holds a valid UUID, generated otherwise, returned on the response, attached to log records,
and included in error bodies. Async work started by the request carries the same ID.
"""

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "X-Correlation-ID"

_correlation_id: ContextVar[UUID | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> UUID:
    """Return the current correlation ID, creating one if none is set."""
    current = _correlation_id.get()
    if current is None:
        current = uuid4()
        _correlation_id.set(current)
    return current


def _parse(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = _parse(request.headers.get(CORRELATION_HEADER)) or uuid4()
        token = _correlation_id.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            _correlation_id.reset(token)
        response.headers[CORRELATION_HEADER] = str(correlation_id)
        return response


class CorrelationIdLogFilter(logging.Filter):
    """Adds `correlation_id` to every log record so formatters can include it."""

    def filter(self, record: logging.LogRecord) -> bool:
        current = _correlation_id.get()
        record.correlation_id = str(current) if current else "-"
        return True
