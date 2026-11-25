"""Database engine, request sessions and the readiness probe.

The API connects as a login role that is a member of `workforce_app`. That role owns no
tables and cannot bypass row-level security (ADR-0003). Migrations run separately, as the
schema owner, through WORKFORCE_MIGRATION_DATABASE_URL.

Each request gets one session inside one transaction: the tenant context set at the start
applies to every query, is committed or rolled back together, and disappears at the end.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(self, url: str) -> None:
        # Connections open lazily, so the app starts even when the database is down.
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request. Commits if the handler succeeds, rolls back otherwise."""
    database: Database = request.app.state.database
    async with database.sessions() as session, session.begin():
        yield session
