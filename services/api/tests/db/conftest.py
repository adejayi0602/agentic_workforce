"""Fixtures for tests that need a real PostgreSQL.

Set WORKFORCE_TEST_ADMIN_DATABASE_URL to a superuser URL (CI uses a Postgres service
container). Each test session gets a fresh database, migrated as a non-superuser owner, and
the tests connect as a login role in `workforce_app`, exactly like the running API.
Without the variable these tests are skipped.
"""

import asyncio
import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

API_DIR = Path(__file__).resolve().parents[2]
OWNER_ROLE = "wf_test_owner"
APP_LOGIN_ROLE = "wf_test_api"
# Test-only credentials for throwaway roles in a throwaway database.
OWNER_PASSWORD = "wf_test_owner"  # noqa: S105
APP_PASSWORD = "wf_test_api"  # noqa: S105


@dataclass(frozen=True)
class DatabaseUrls:
    owner_url: URL
    app_url: URL


def _asyncpg_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _admin(admin_url: URL, *statements: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(admin_url))
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


async def _ensure_role(admin_url: URL, name: str, password: str, extra: str = "") -> None:
    await _admin(
        admin_url,
        f"""DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{name}') THEN
                CREATE ROLE {name} LOGIN PASSWORD '{password}' {extra};
              END IF;
            END $$;""",
    )


@pytest.fixture(scope="session")
def test_database() -> Iterator[DatabaseUrls]:
    raw = os.environ.get("WORKFORCE_TEST_ADMIN_DATABASE_URL")
    if not raw:
        pytest.skip("WORKFORCE_TEST_ADMIN_DATABASE_URL is not set")
    admin_url = make_url(raw)
    db_name = f"workforce_test_{uuid.uuid4().hex[:8]}"

    async def setup() -> None:
        await _ensure_role(admin_url, OWNER_ROLE, OWNER_PASSWORD, "CREATEROLE")
        await _ensure_role(admin_url, APP_LOGIN_ROLE, APP_PASSWORD)
        await _admin(
            admin_url,
            """DO $$ BEGIN
                 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'workforce_app') THEN
                   CREATE ROLE workforce_app NOLOGIN;
                 END IF;
               END $$;""",
            f"GRANT workforce_app TO {APP_LOGIN_ROLE}",
            f"CREATE DATABASE {db_name} OWNER {OWNER_ROLE}",
        )

    asyncio.run(setup())
    owner_url = admin_url.set(username=OWNER_ROLE, password=OWNER_PASSWORD, database=db_name)
    app_url = admin_url.set(username=APP_LOGIN_ROLE, password=APP_PASSWORD, database=db_name)

    migrate_env = {
        **os.environ,
        "WORKFORCE_MIGRATION_DATABASE_URL": owner_url.render_as_string(hide_password=False),
    }
    subprocess.run(
        ["alembic", "upgrade", "head"],  # noqa: S607
        cwd=API_DIR,
        env=migrate_env,
        check=True,
        capture_output=True,
    )
    try:
        yield DatabaseUrls(owner_url=owner_url, app_url=app_url)
    finally:
        asyncio.run(_admin(admin_url, f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)"))


@pytest.fixture
async def app_engine(test_database: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """An engine connected as the API's role. One pooled connection, to expose leaks."""
    engine = create_async_engine(test_database.app_url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        await engine.dispose()
