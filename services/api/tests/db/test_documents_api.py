"""Document upload sessions (FR-001, FR-002, ADR-0012) against PostgreSQL and emulated S3."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration


async def setup(api: Any, *roles: str) -> tuple[str, list[dict[str, str]]]:
    """An organisation and project; returns the project id and headers per role (admin first)."""
    admin = await api.sign_in()
    org = await api.create_org(admin)
    people = [api.in_org(admin, org["id"])]
    for role in roles:
        person = await api.sign_in()
        await api.add_member(org["id"], await api.user_id(person), role)
        people.append(api.in_org(person, org["id"]))
    project = await api.client.post(
        "/api/v1/projects",
        json={"key": "D" + uuid.uuid4().hex[:5].upper(), "name": "Docs", "type": "software"},
        headers=people[0],
    )
    return project.json()["id"], people


def declaration(content: bytes, filename: str = "srs.docx", **extra: Any) -> dict[str, Any]:
    return {
        "filename": filename,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        **extra,
    }


async def test_full_upload_flow(api: Any) -> None:
    project_id, [admin] = await setup(api)
    result = await api.upload_document(
        admin, project_id, content=b"hello SRS", filename="Payments SRS.md"
    )

    assert result["version"]["status"] == "awaiting_upload"
    assert result["upload"]["method"] == "PUT"
    assert result["upload"]["headers"]["Content-Type"] == "text/markdown"
    assert result["document"]["title"] == "Payments SRS"
    assert result["completed"]["status"] == "uploaded"
    assert result["completed"]["uploaded_at"] is not None

    listed = (
        await api.client.get(f"/api/v1/projects/{project_id}/documents", headers=admin)
    ).json()
    assert [d["latest_version"]["status"] for d in listed] == ["uploaded"]


async def test_presigned_url_is_scoped_to_the_tenant_prefix(api: Any) -> None:
    project_id, [admin] = await setup(api)
    org_id = admin["X-Organisation-ID"]
    started = await api.client.post(
        f"/api/v1/projects/{project_id}/documents", json=declaration(b"x"), headers=admin
    )
    url = started.json()["upload"]["url"]
    assert f"/org/{org_id}/project/{project_id}/documents/" in url
    assert "/v1/original?" in url
    for signed in ("content-length", "content-type", "x-amz-checksum-sha256"):
        assert signed in url  # part of X-Amz-SignedHeaders


async def test_legacy_word_file_is_refused_with_advice(api: Any) -> None:
    project_id, [admin] = await setup(api)
    r = await api.client.post(
        f"/api/v1/projects/{project_id}/documents",
        json=declaration(b"x", filename="old.doc"),
        headers=admin,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert ".docx" in r.json()["error"]["message"]


async def test_over_15_mb_is_refused(api: Any) -> None:
    project_id, [admin] = await setup(api)
    r = await api.client.post(
        f"/api/v1/projects/{project_id}/documents",
        json={"filename": "big.pdf", "size_bytes": 15 * 1024 * 1024 + 1, "sha256": "a" * 64},
        headers=admin,
    )
    assert r.status_code == 422


async def test_completing_before_uploading_is_refused(api: Any) -> None:
    project_id, [admin] = await setup(api)
    result = await api.upload_document(admin, project_id, complete=False)
    # Upload happened in the helper; make a fresh session that never uploads.
    started = (
        await api.client.post(
            f"/api/v1/projects/{project_id}/documents/{result['document']['id']}/versions",
            json=declaration(b"never sent", filename="v2.md"),
            headers=admin,
        )
    ).json()
    r = await api.client.post(
        f"/api/v1/projects/{project_id}/documents/{result['document']['id']}"
        f"/versions/{started['version']['id']}/complete",
        headers=admin,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "UPLOAD_INCOMPLETE"


async def test_a_swapped_file_is_caught_on_completion(api: Any) -> None:
    """Even if storage accepted different bytes, the API's own check refuses them."""
    project_id, [admin] = await setup(api)
    declared = b"the approved SRS"
    started = (
        await api.client.post(
            f"/api/v1/projects/{project_id}/documents",
            json=declaration(declared, filename="srs.md"),
            headers=admin,
        )
    ).json()
    async with httpx.AsyncClient() as s3:
        await s3.put(
            started["upload"]["url"],
            content=b"a tampered SRS!!",  # same length, different content
            headers=started["upload"]["headers"],
        )
    complete_url = (
        f"/api/v1/projects/{project_id}/documents/{started['document']['id']}"
        f"/versions/{started['version']['id']}/complete"
    )
    r = await api.client.post(complete_url, headers=admin)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CHECKSUM_MISMATCH"

    detail = (
        await api.client.get(
            f"/api/v1/projects/{project_id}/documents/{started['document']['id']}", headers=admin
        )
    ).json()
    assert detail["versions"][0]["status"] == "awaiting_upload"

    events = (await api.client.get("/api/v1/audit-events", headers=admin)).json()["items"]
    denial = next(e for e in events if e["decision"] == "denied")
    assert denial["details"]["reason"] == "checksum_mismatch"


async def test_expired_upload_link_cannot_be_completed(api: Any) -> None:
    project_id, [admin] = await setup(api)
    result = await api.upload_document(admin, project_id, complete=False)
    owner = create_async_engine(api.database.owner_url)
    try:
        async with owner.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.organisation_id', :o, true)"),
                {"o": admin["X-Organisation-ID"]},
            )
            await conn.execute(
                text("UPDATE document_versions SET upload_expires_at = :t WHERE id = :v"),
                {"t": datetime.now(UTC) - timedelta(minutes=1), "v": result["version"]["id"]},
            )
    finally:
        await owner.dispose()
    r = await api.client.post(
        f"/api/v1/projects/{project_id}/documents/{result['document']['id']}"
        f"/versions/{result['version']['id']}/complete",
        headers=admin,
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "UPLOAD_EXPIRED"


async def test_completing_twice_is_harmless(api: Any) -> None:
    project_id, [admin] = await setup(api)
    result = await api.upload_document(admin, project_id)
    again = await api.client.post(
        f"/api/v1/projects/{project_id}/documents/{result['document']['id']}"
        f"/versions/{result['version']['id']}/complete",
        headers=admin,
    )
    assert again.status_code == 200
    assert again.json()["uploaded_at"] == result["completed"]["uploaded_at"]


async def test_new_versions_keep_old_ones_unchanged(api: Any) -> None:
    project_id, [admin] = await setup(api)
    first = await api.upload_document(admin, project_id, content=b"version one")
    doc_id = first["document"]["id"]
    started = (
        await api.client.post(
            f"/api/v1/projects/{project_id}/documents/{doc_id}/versions",
            json=declaration(b"version two", filename="srs.md"),
            headers=admin,
        )
    ).json()
    assert started["version"]["version"] == 2

    detail = (
        await api.client.get(f"/api/v1/projects/{project_id}/documents/{doc_id}", headers=admin)
    ).json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    v1 = detail["versions"][1]
    assert v1["sha256"] == hashlib.sha256(b"version one").hexdigest()
    assert v1["status"] == "uploaded"
    assert detail["latest_version"]["version"] == 2


async def test_who_may_upload(api: Any) -> None:
    project_id, [_, member, auditor] = await setup(api, "member", "auditor")
    ok = await api.client.post(
        f"/api/v1/projects/{project_id}/documents", json=declaration(b"m"), headers=member
    )
    assert ok.status_code == 201
    refused = await api.client.post(
        f"/api/v1/projects/{project_id}/documents", json=declaration(b"a"), headers=auditor
    )
    assert refused.status_code == 403
    readable = await api.client.get(f"/api/v1/projects/{project_id}/documents", headers=auditor)
    assert readable.status_code == 200


async def test_archived_projects_take_no_documents(api: Any) -> None:
    project_id, [admin] = await setup(api)
    await api.client.patch(
        f"/api/v1/projects/{project_id}", json={"status": "archived"}, headers=admin
    )
    r = await api.client.post(
        f"/api/v1/projects/{project_id}/documents", json=declaration(b"x"), headers=admin
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_STATE"


async def test_document_steps_are_audited_and_emitted(api: Any) -> None:
    project_id, [admin] = await setup(api)
    result = await api.upload_document(admin, project_id)
    events = (
        await api.client.get(f"/api/v1/projects/{project_id}/audit-events", headers=admin)
    ).json()["items"]
    actions = {e["action"] for e in events}
    assert {"document.create", "document.upload_complete"} <= actions
    outbox = await api.owner_read(
        "outbox_events", "aggregate_id = :v", {"v": result["version"]["id"]}
    )
    assert [e["event_type"] for e in outbox] == ["document.version_uploaded"]


async def test_create_is_idempotent(api: Any) -> None:
    project_id, [admin] = await setup(api)
    headers = {**admin, "Idempotency-Key": f"doc-{uuid.uuid4()}"}
    body = declaration(b"same", filename="same.md")
    a = await api.client.post(
        f"/api/v1/projects/{project_id}/documents", json=body, headers=headers
    )
    b = await api.client.post(
        f"/api/v1/projects/{project_id}/documents", json=body, headers=headers
    )
    assert a.json()["document"]["id"] == b.json()["document"]["id"]
    assert b.headers.get("Idempotent-Replayed") == "true"
