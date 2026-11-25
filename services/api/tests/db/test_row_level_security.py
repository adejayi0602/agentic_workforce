"""Row-level security and grants, tested as the API's own database role (ADR-0003)."""

import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from workforce_api.models import Base

pytestmark = pytest.mark.integration

API_DIR = Path(__file__).resolve().parents[2]


@asynccontextmanager
async def as_tenant(
    engine: AsyncEngine, *, org: uuid.UUID | None = None, user: uuid.UUID | None = None
) -> AsyncIterator[AsyncConnection]:
    """One transaction with the tenant context set, as the API does per request."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT set_config('app.organisation_id', :o, true), "
                "set_config('app.user_id', :u, true)"
            ),
            {"o": str(org) if org else "", "u": str(user) if user else ""},
        )
        yield conn


@dataclass(frozen=True)
class Tenant:
    org: uuid.UUID
    user: uuid.UUID
    project: uuid.UUID


async def make_tenant(engine: AsyncEngine) -> Tenant:
    """Create a user, an organisation they administer, and one project - through RLS."""
    org, user, project = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    suffix = org.hex[:8]
    async with as_tenant(engine, user=user) as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, identity_issuer, identity_subject) VALUES (:id, 'test', :s)"
            ),
            {"id": user, "s": f"sub-{suffix}"},
        )
    async with as_tenant(engine, org=org, user=user) as conn:
        await conn.execute(
            text("INSERT INTO organisations (id, name, slug) VALUES (:id, :n, :s)"),
            {"id": org, "n": f"Org {suffix}", "s": f"org-{suffix}"},
        )
        await conn.execute(
            text(
                "INSERT INTO organisation_members (organisation_id, user_id, role) "
                "VALUES (:o, :u, 'org_admin')"
            ),
            {"o": org, "u": user},
        )
        await conn.execute(
            text(
                "INSERT INTO projects (id, organisation_id, key, name, type, owner_id) "
                "VALUES (:id, :o, 'PAY', 'Payments', 'software', :u)"
            ),
            {"id": project, "o": org, "u": user},
        )
    return Tenant(org=org, user=user, project=project)


@pytest.fixture
async def tenants(app_engine: AsyncEngine) -> tuple[Tenant, Tenant]:
    return await make_tenant(app_engine), await make_tenant(app_engine)


async def ids(conn: AsyncConnection, sql: str) -> set[uuid.UUID]:
    return {row[0] for row in await conn.execute(text(sql))}


async def test_no_context_sees_nothing(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    async with as_tenant(app_engine) as conn:
        for table in ("organisations", "users", "organisation_members", "projects", "audit_events"):
            count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608
            assert count == 0, f"{table} visible without tenant context"


async def test_projects_are_scoped_to_current_organisation(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
        visible = await ids(conn, "SELECT id FROM projects")
    assert a.project in visible
    assert b.project not in visible


async def test_cannot_insert_into_another_organisation(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    with pytest.raises(DBAPIError, match="row-level security"):
        async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
            await conn.execute(
                text(
                    "INSERT INTO projects (organisation_id, key, name, type, owner_id) "
                    "VALUES (:o, 'EVIL', 'x', 'software', :u)"
                ),
                {"o": b.org, "u": a.user},
            )


async def test_cannot_update_another_organisations_project(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
        result = await conn.execute(
            text("UPDATE projects SET name = 'hijacked' WHERE id = :id"), {"id": b.project}
        )
    assert result.rowcount == 0


async def test_cannot_move_a_project_to_another_organisation(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    with pytest.raises(DBAPIError, match="row-level security"):
        async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
            await conn.execute(
                text("UPDATE projects SET organisation_id = :b WHERE id = :id"),
                {"b": b.org, "id": a.project},
            )


async def test_user_sees_own_memberships_before_choosing_an_organisation(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    async with as_tenant(app_engine, user=a.user) as conn:
        orgs = await ids(conn, "SELECT id FROM organisations")
        member_orgs = await ids(conn, "SELECT organisation_id FROM organisation_members")
        projects = await ids(conn, "SELECT id FROM projects")
    assert a.org in orgs
    assert b.org not in orgs
    assert member_orgs == {a.org}
    assert projects == set(), "projects need an organisation context, not just a user"


async def test_users_of_other_organisations_are_invisible(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
        users = await ids(conn, "SELECT id FROM users")
    assert a.user in users
    assert b.user not in users


async def test_tenant_context_does_not_leak_between_transactions(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
        assert await ids(conn, "SELECT id FROM projects")
    # The pool has one connection, so this reuses it.
    async with app_engine.begin() as conn:
        assert await ids(conn, "SELECT id FROM projects") == set()


async def test_audit_events_are_append_only(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    event_id = uuid.uuid4()
    async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_events (id, organisation_id, actor_type, actor_id, action, "
                "resource_type, decision, correlation_id) "
                "VALUES (:id, :o, 'user', :u, 'project.create', 'project', 'allowed', :c)"
            ),
            {"id": event_id, "o": a.org, "u": str(a.user), "c": uuid.uuid4()},
        )
    for statement in (
        "UPDATE audit_events SET action = 'tampered' WHERE id = :id",
        "DELETE FROM audit_events WHERE id = :id",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
                await conn.execute(text(statement), {"id": event_id})


async def test_audit_trigger_blocks_changes_even_for_the_owner(
    test_database: Any, tenants: tuple[Tenant, Tenant]
) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    a, _ = tenants
    owner = create_async_engine(test_database.owner_url)
    try:
        async with owner.connect() as conn:
            transaction = await conn.begin()
            # Even with RLS lifted, the owner cannot rewrite history.
            await conn.execute(text("ALTER TABLE audit_events NO FORCE ROW LEVEL SECURITY"))
            await conn.execute(
                text(
                    "INSERT INTO audit_events (organisation_id, actor_type, actor_id, action, "
                    "resource_type, decision, correlation_id) "
                    "VALUES (:o, 'system', 'test', 'x', 'x', 'allowed', :c)"
                ),
                {"o": a.org, "c": uuid.uuid4()},
            )
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(text("DELETE FROM audit_events"))
            await transaction.rollback()
    finally:
        await owner.dispose()


async def test_projects_cannot_be_deleted_by_the_api_role(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    with pytest.raises(DBAPIError, match="permission denied"):
        async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
            await conn.execute(text("DELETE FROM projects WHERE id = :id"), {"id": a.project})


async def test_outbox_is_write_only_for_the_api_role(
    app_engine: AsyncEngine, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
        await conn.execute(
            text(
                "INSERT INTO outbox_events (organisation_id, aggregate_type, aggregate_id, "
                "event_type, payload, correlation_id) "
                "VALUES (:o, 'project', :p, 'project.created', '{}', :c)"
            ),
            {"o": a.org, "p": a.project, "c": uuid.uuid4()},
        )
    with pytest.raises(DBAPIError, match="permission denied"):
        async with as_tenant(app_engine, org=a.org, user=a.user) as conn:
            await conn.execute(text("SELECT * FROM outbox_events"))


async def test_every_table_has_forced_row_level_security(
    app_engine: AsyncEngine, test_database: Any
) -> None:
    async with app_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' "
                "AND relname <> 'alembic_version'"
            )
        )
        state = {name: (enabled, forced) for name, enabled, forced in rows}
    assert set(state) == set(Base.metadata.tables), "a table is missing from this check"
    assert all(enabled and forced for enabled, forced in state.values()), state


def test_models_match_migrations(test_database: Any) -> None:
    env = {
        **os.environ,
        "WORKFORCE_MIGRATION_DATABASE_URL": test_database.owner_url.render_as_string(
            hide_password=False
        ),
    }
    result = subprocess.run(
        ["alembic", "check"],  # noqa: S607
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
