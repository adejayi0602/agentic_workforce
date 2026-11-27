"""The malware scan gate, run as the worker's own database role (ADR-0012, threat T10)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from workforce_api.modules.documents import scan_gate
from workforce_intake.scanning import EICAR, EicarScanner, ScanResult, Verdict

pytestmark = pytest.mark.integration


@pytest.fixture
async def worker_sessions(test_database: Any) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(test_database.worker_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def run_as(engine: Any, org_id: str | None, sql: str, params: dict[str, Any]) -> None:
    """One statement in its own transaction, with the tenant context set."""
    async with engine.begin() as conn:
        if org_id:
            await conn.execute(
                text("SELECT set_config('app.organisation_id', :o, true)"), {"o": org_id}
            )
        await conn.execute(text(sql), params)


async def uploaded_version(api: Any, content: bytes) -> tuple[dict[str, str], dict[str, Any]]:
    admin = await api.sign_in()
    org = await api.create_org(admin)
    headers = api.in_org(admin, org["id"])
    project = await api.client.post(
        "/api/v1/projects",
        json={"key": "S" + uuid.uuid4().hex[:5].upper(), "name": "Scan", "type": "software"},
        headers=headers,
    )
    result = await api.upload_document(headers, project.json()["id"], content=content)
    return headers, result


async def scan(
    sessions: async_sessionmaker[AsyncSession], org_id: str, version_id: str, content: bytes
) -> str:
    """What the workflow's scan activity will do: start, scan, record."""
    async with sessions() as session, session.begin():
        version, document = await scan_gate.load_version(
            session, organisation_id=uuid.UUID(org_id), version_id=uuid.UUID(version_id)
        )
        await scan_gate.start_scan(session, version)
        result = EicarScanner().scan(bucket="b", key="k", content=content)
        await scan_gate.record_verdict(session, version, document, result)
        return version.status


async def test_clean_file_passes_the_gate(api: Any, worker_sessions: Any) -> None:
    headers, up = await uploaded_version(api, b"# An ordinary SRS")
    status = await scan(worker_sessions, headers["X-Organisation-ID"], up["version"]["id"], b"ok")
    assert status == "clean"

    async with worker_sessions() as session, session.begin():
        version, _ = await scan_gate.load_version(
            session,
            organisation_id=uuid.UUID(headers["X-Organisation-ID"]),
            version_id=uuid.UUID(up["version"]["id"]),
        )
        scan_gate.ensure_parseable(version)  # does not raise
        assert version.scan_result == {"engine": "eicar-test", "verdict": "clean"}


async def test_eicar_file_is_quarantined_audited_and_never_parseable(
    api: Any, worker_sessions: Any
) -> None:
    content = b"Requirements\n" + EICAR
    headers, up = await uploaded_version(api, content)
    org_id, version_id = headers["X-Organisation-ID"], up["version"]["id"]

    assert await scan(worker_sessions, org_id, version_id, content) == "quarantined"

    async with worker_sessions() as session, session.begin():
        version, _ = await scan_gate.load_version(
            session, organisation_id=uuid.UUID(org_id), version_id=uuid.UUID(version_id)
        )
        with pytest.raises(scan_gate.NotParseableError):
            scan_gate.ensure_parseable(version)

    # Quarantine is final: a rescan can't release it.
    with pytest.raises(Exception, match="quarantined"):
        await scan(worker_sessions, org_id, version_id, b"clean now, honest")

    events = (await api.client.get("/api/v1/audit-events", headers=headers)).json()["items"]
    quarantine = next(e for e in events if e["action"] == "document.quarantine")
    assert quarantine["decision"] == "denied"
    assert quarantine["actor_type"] == "system"
    assert quarantine["details"]["signature"] == "EICAR-Test-File"


async def test_unscanned_versions_are_not_parseable(api: Any, worker_sessions: Any) -> None:
    headers, up = await uploaded_version(api, b"not yet scanned")
    async with worker_sessions() as session, session.begin():
        version, _ = await scan_gate.load_version(
            session,
            organisation_id=uuid.UUID(headers["X-Organisation-ID"]),
            version_id=uuid.UUID(up["version"]["id"]),
        )
        assert version.status == "uploaded"
        with pytest.raises(scan_gate.NotParseableError):
            scan_gate.ensure_parseable(version)


async def test_failed_scan_can_be_retried_and_pending_changes_nothing(
    api: Any, worker_sessions: Any
) -> None:
    headers, up = await uploaded_version(api, b"x")
    org = uuid.UUID(headers["X-Organisation-ID"])
    vid = uuid.UUID(up["version"]["id"])
    for verdict, expected in [
        (Verdict.FAILED, "scan_failed"),
        (Verdict.PENDING, "scanning"),
        (Verdict.CLEAN, "clean"),
    ]:
        async with worker_sessions() as session, session.begin():
            version, document = await scan_gate.load_version(
                session, organisation_id=org, version_id=vid
            )
            await scan_gate.start_scan(session, version)
            await scan_gate.record_verdict(
                session, version, document, ScanResult(verdict, "test-engine")
            )
            assert version.status == expected


async def test_worker_cannot_change_what_a_version_is(api: Any, test_database: Any) -> None:
    headers, up = await uploaded_version(api, b"immutable")
    org, vid = headers["X-Organisation-ID"], {"v": up["version"]["id"]}
    engine = create_async_engine(test_database.worker_url)
    try:
        for column, value in [("sha256", "'" + "0" * 64 + "'"), ("s3_key", "'elsewhere'")]:
            sql = f"UPDATE document_versions SET {column} = {value} WHERE id = :v"  # noqa: S608
            with pytest.raises(DBAPIError, match="permission denied"):
                await run_as(engine, org, sql, vid)
        for sql in ("DELETE FROM document_versions", "SELECT id FROM projects"):
            with pytest.raises(DBAPIError, match="permission denied"):
                await run_as(engine, org, sql, {})
    finally:
        await engine.dispose()


async def test_worker_cannot_reach_another_organisations_version(
    api: Any, worker_sessions: Any
) -> None:
    _, a_up = await uploaded_version(api, b"a")
    b_headers, _ = await uploaded_version(api, b"b")
    async with worker_sessions() as session, session.begin():
        with pytest.raises(LookupError):
            await scan_gate.load_version(
                session,
                organisation_id=uuid.UUID(b_headers["X-Organisation-ID"]),
                version_id=uuid.UUID(a_up["version"]["id"]),
            )


async def test_api_role_cannot_rewrite_a_version_either(api: Any, test_database: Any) -> None:
    headers, up = await uploaded_version(api, b"x")
    engine = create_async_engine(test_database.app_url)
    try:
        with pytest.raises(DBAPIError, match="permission denied"):
            await run_as(
                engine,
                headers["X-Organisation-ID"],
                "UPDATE document_versions SET size_bytes = 1 WHERE id = :v",
                {"v": up["version"]["id"]},
            )
    finally:
        await engine.dispose()
