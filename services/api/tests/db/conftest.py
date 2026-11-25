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
from typing import Any

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


# ---- HTTP helpers shared by API tests ----

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from workforce_api.config import Settings  # noqa: E402
from workforce_api.main import create_app  # noqa: E402


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Api:
    """Drives the API as real clients would, plus owner-level shortcuts for test setup."""

    def __init__(self, client: httpx.AsyncClient, database: DatabaseUrls) -> None:
        self.client = client
        self.database = database

    async def sign_in(self, name: str | None = None) -> dict[str, str]:
        subject = name or unique("user")
        r = await self.client.post(
            "/api/v1/dev-auth/token",
            json={"subject": subject, "email": f"{subject}@example.com", "name": subject},
        )
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await self.client.get("/api/v1/me", headers=headers)  # provision the user
        return headers

    async def user_id(self, headers: dict[str, str]) -> str:
        return str((await self.client.get("/api/v1/me", headers=headers)).json()["id"])

    async def create_org(self, headers: dict[str, str]) -> dict[str, str]:
        slug = unique("org")
        r = await self.client.post(
            "/api/v1/organisations", json={"name": slug, "slug": slug}, headers=headers
        )
        assert r.status_code == 201, r.text
        body: dict[str, str] = r.json()
        return body

    @staticmethod
    def in_org(headers: dict[str, str], org_id: str) -> dict[str, str]:
        return {**headers, "X-Organisation-ID": org_id}

    async def add_member(self, org_id: str, user_id: str, role: str) -> None:
        """Invitations arrive in #11; until then tests add members as the schema owner."""
        owner = create_async_engine(self.database.owner_url)
        try:
            async with owner.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.organisation_id', :o, true)"), {"o": org_id}
                )
                await conn.execute(
                    text(
                        "INSERT INTO organisation_members (organisation_id, user_id, role) "
                        "VALUES (:o, :u, :r)"
                    ),
                    {"o": org_id, "u": user_id, "r": role},
                )
        finally:
            await owner.dispose()

    async def owner_read(self, table: str, where: str, params: dict[str, str]) -> list[Any]:
        """Read raw rows as the schema owner, with RLS lifted inside a rolled-back transaction.

        For asserting on tables the API role cannot read (such as the outbox).
        """
        owner = create_async_engine(self.database.owner_url)
        try:
            async with owner.connect() as conn:
                transaction = await conn.begin()
                await conn.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
                rows = await conn.execute(text(f"SELECT * FROM {table} WHERE {where}"), params)  # noqa: S608
                result = [r._mapping for r in rows]
                await transaction.rollback()
                return result
        finally:
            await owner.dispose()


@pytest.fixture
async def api(test_database: DatabaseUrls) -> AsyncIterator[Api]:
    settings = Settings(
        env="test",
        organisation_creation="open",
        database_url=test_database.app_url.render_as_string(hide_password=False),
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield Api(c, test_database)
