"""Database engine, sessions and the readiness probe.

The API connects as a login role that is a member of `workforce_app`. That role owns no
tables and cannot bypass row-level security (ADR-0003). Migrations run separately, as the
schema owner, through WORKFORCE_MIGRATION_DATABASE_URL.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from workforce_api.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory()() as session:
        yield session


async def check_database() -> bool:
    """Return True if a trivial query succeeds."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
