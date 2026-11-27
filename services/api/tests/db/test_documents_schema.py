"""Document tables: tenant isolation, composite keys and grants, as the API's role."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

pytestmark = pytest.mark.integration

SHA = "a" * 64


async def _tenant(engine: AsyncEngine) -> dict[str, uuid.UUID]:
    """User, organisation, project and one document, created through RLS."""
    ids = {k: uuid.uuid4() for k in ("user", "org", "project", "document")}
    s = ids["org"].hex[:8]
    async with engine.begin() as c:
        await c.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(ids["user"])})
        await c.execute(
            text("INSERT INTO users (id, identity_issuer, identity_subject) VALUES (:u, 't', :s)"),
            {"u": ids["user"], "s": s},
        )
    async with engine.begin() as c:
        await c.execute(
            text(
                "SELECT set_config('app.organisation_id', :o, true), "
                "set_config('app.user_id', :u, true)"
            ),
            {"o": str(ids["org"]), "u": str(ids["user"])},
        )
        await c.execute(
            text("INSERT INTO organisations (id, name, slug) VALUES (:o, :s, :s)"),
            {"o": ids["org"], "s": f"o-{s}"},
        )
        await c.execute(
            text(
                "INSERT INTO organisation_members (organisation_id, user_id, role) "
                "VALUES (:o, :u, 'org_admin')"
            ),
            {"o": ids["org"], "u": ids["user"]},
        )
        await c.execute(
            text(
                "INSERT INTO projects (id, organisation_id, key, name, type, owner_id) "
                "VALUES (:p, :o, 'DOC', 'Docs', 'software', :u)"
            ),
            {"p": ids["project"], "o": ids["org"], "u": ids["user"]},
        )
        await c.execute(
            text(
                "INSERT INTO project_documents (id, organisation_id, project_id, title, "
                "category, created_by) VALUES (:d, :o, :p, 'SRS', 'srs', :u)"
            ),
            {"d": ids["document"], "o": ids["org"], "p": ids["project"], "u": ids["user"]},
        )
    return ids


def _version_params(t: dict[str, uuid.UUID], **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid.uuid4(),
        "o": t["org"],
        "d": t["document"],
        "v": 1,
        "size": 1000,
        "sha": SHA,
        "key": f"org/{t['org']}/v/{uuid.uuid4()}",
        "u": t["user"],
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "status": "awaiting_upload",
    }
    params.update(overrides)
    return params


INSERT_VERSION = text(
    "INSERT INTO document_versions (id, organisation_id, document_id, version, filename, "
    "media_type, size_bytes, sha256, s3_bucket, s3_key, status, uploaded_by, upload_expires_at) "
    "VALUES (:id, :o, :d, :v, 'srs.docx', 'application/x', :size, :sha, 'b', :key, :status, "
    ":u, :exp)"
)


async def _as(engine: AsyncEngine, t: dict[str, uuid.UUID], statement: Any, params: Any) -> None:
    async with engine.begin() as c:
        await c.execute(
            text(
                "SELECT set_config('app.organisation_id', :o, true), "
                "set_config('app.user_id', :u, true)"
            ),
            {"o": str(t["org"]), "u": str(t["user"])},
        )
        await c.execute(statement, params)


async def test_version_insert_within_own_organisation(app_engine: AsyncEngine) -> None:
    t = await _tenant(app_engine)
    await _as(app_engine, t, INSERT_VERSION, _version_params(t))


async def test_version_cannot_point_at_another_organisations_document(
    app_engine: AsyncEngine,
) -> None:
    a, b = await _tenant(app_engine), await _tenant(app_engine)
    # Acting in A, claiming A's organisation, but referencing B's document.
    with pytest.raises(DBAPIError, match="foreign key"):
        await _as(app_engine, a, INSERT_VERSION, _version_params(a, d=b["document"]))


async def test_composite_key_holds_even_with_rls_lifted(
    app_engine: AsyncEngine, test_database: Any
) -> None:
    """Defence in depth: the owner, with RLS off, still can't mismatch tenants."""
    a, b = await _tenant(app_engine), await _tenant(app_engine)
    owner = create_async_engine(test_database.owner_url)
    try:
        async with owner.connect() as conn:
            tx = await conn.begin()
            await conn.execute(text("ALTER TABLE document_versions NO FORCE ROW LEVEL SECURITY"))
            with pytest.raises(DBAPIError, match="foreign key"):
                await conn.execute(INSERT_VERSION, _version_params(a, d=b["document"]))
            await tx.rollback()
    finally:
        await owner.dispose()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"size": 15 * 1024 * 1024 + 1}, "size_limit"),
        ({"size": 0}, "size_limit"),
        ({"sha": "NOT-A-HASH"}, "sha256_format"),
        ({"status": "approved"}, "status"),
        ({"v": 0}, "version_positive"),
    ],
)
async def test_database_rejects_invalid_versions(
    app_engine: AsyncEngine, overrides: dict[str, Any], constraint: str
) -> None:
    t = await _tenant(app_engine)
    with pytest.raises(DBAPIError, match=constraint):
        await _as(app_engine, t, INSERT_VERSION, _version_params(t, **overrides))


async def test_version_numbers_are_unique_per_document(app_engine: AsyncEngine) -> None:
    t = await _tenant(app_engine)
    await _as(app_engine, t, INSERT_VERSION, _version_params(t, v=1))
    with pytest.raises(DBAPIError, match="duplicate key"):
        await _as(app_engine, t, INSERT_VERSION, _version_params(t, v=1))


async def test_api_role_cannot_delete_or_write_runs(app_engine: AsyncEngine) -> None:
    t = await _tenant(app_engine)
    with pytest.raises(DBAPIError, match="permission denied"):
        await _as(app_engine, t, text("DELETE FROM project_documents"), {})
    with pytest.raises(DBAPIError, match="permission denied"):
        await _as(app_engine, t, text("DELETE FROM document_versions"), {})
    with pytest.raises(DBAPIError, match="permission denied"):
        await _as(
            app_engine,
            t,
            text(
                "INSERT INTO document_processing_runs (organisation_id, document_version_id, "
                "attempt, status) VALUES (:o, :v, 1, 'running')"
            ),
            {"o": t["org"], "v": uuid.uuid4()},
        )


async def test_documents_are_invisible_to_other_organisations(app_engine: AsyncEngine) -> None:
    a, b = await _tenant(app_engine), await _tenant(app_engine)
    async with app_engine.begin() as c:
        await c.execute(
            text(
                "SELECT set_config('app.organisation_id', :o, true), "
                "set_config('app.user_id', :u, true)"
            ),
            {"o": str(a["org"]), "u": str(a["user"])},
        )
        ids = {r[0] for r in await c.execute(text("SELECT id FROM project_documents"))}
    assert a["document"] in ids
    assert b["document"] not in ids
