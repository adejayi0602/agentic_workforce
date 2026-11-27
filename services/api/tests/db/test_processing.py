"""Scan and extract steps against PostgreSQL and emulated S3, as the worker role."""

import io
import uuid
from collections.abc import AsyncIterator
from typing import Any

import boto3
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from workforce_api.modules.documents import processing
from workforce_api.storage import ObjectStore
from workforce_intake.scanning import EICAR, EicarScanner

pytestmark = pytest.mark.integration


@pytest.fixture
async def worker(test_database: Any, s3_endpoint: str) -> AsyncIterator["Worker"]:
    engine = create_async_engine(test_database.worker_url)
    try:
        yield Worker(
            async_sessionmaker(engine, expire_on_commit=False),
            ObjectStore(endpoint_url=s3_endpoint, region="eu-west-1"),
        )
    finally:
        await engine.dispose()


class Worker:
    """Runs the steps exactly as the workflow's activities do."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], store: ObjectStore) -> None:
        self.sessions = sessions
        self.store = store

    async def scan(self, org: str, version: str) -> str:
        outcome = await processing.scan_step(
            self.sessions,
            self.store,
            EicarScanner(),
            organisation_id=uuid.UUID(org),
            version_id=uuid.UUID(version),
            needs_content=True,
        )
        return outcome.value

    async def extract(self, org: str, version: str) -> processing.ExtractOutcome:
        return await processing.extract_step(
            self.sessions,
            self.store,
            organisation_id=uuid.UUID(org),
            version_id=uuid.UUID(version),
            workflow_id=f"process-document-{version}",
            artefacts_bucket="workforce-artefacts",
        )


def docx_bytes() -> bytes:
    import docx

    d = docx.Document()
    d.add_heading("Payments SRS", level=0)
    d.add_heading("3.2 Card payments", level=2)
    d.add_paragraph("REQ-PAY-014: The system shall refund within 5 working days.")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


async def setup(api: Any, content: bytes, filename: str) -> dict[str, Any]:
    admin = await api.sign_in()
    org = await api.create_org(admin)
    headers = api.in_org(admin, org["id"])
    project = (
        await api.client.post(
            "/api/v1/projects",
            json={"key": "P" + uuid.uuid4().hex[:5].upper(), "name": "P", "type": "software"},
            headers=headers,
        )
    ).json()
    up = await api.upload_document(headers, project["id"], content=content, filename=filename)
    base = f"/api/v1/projects/{project['id']}/documents/{up['document']['id']}"
    return {
        "headers": headers,
        "org": org["id"],
        "version": up["version"]["id"],
        "doc_url": base,
        "version_url": f"{base}/versions/{up['version']['id']}",
    }


async def test_completing_an_upload_starts_processing_once(api: Any) -> None:
    s = await setup(api, b"# SRS", "srs.md")
    assert api.workflows.started == [{"organisation_id": s["org"], "version_id": s["version"]}]
    await api.client.post(f"{s['version_url']}/complete", headers=s["headers"])  # repeat
    assert len(api.workflows.started) == 1


async def test_upload_still_succeeds_when_temporal_is_down(api: Any) -> None:
    api.workflows.fail = True
    s = await setup(api, b"# SRS", "srs.md")  # complete returned 200 inside setup
    detail = (await api.client.get(s["doc_url"], headers=s["headers"])).json()
    assert detail["latest_version"]["status"] == "uploaded"


async def test_word_document_end_to_end(api: Any, worker: Worker) -> None:
    s = await setup(api, docx_bytes(), "Payments SRS.docx")
    assert await worker.scan(s["org"], s["version"]) == "clean"
    outcome = await worker.extract(s["org"], s["version"])
    assert outcome.status == "ready"

    detail = (await api.client.get(s["doc_url"], headers=s["headers"])).json()
    latest = detail["latest_version"]
    assert latest["status"] == "ready"
    assert latest["last_run"]["status"] == "succeeded"
    assert latest["last_run"]["parser_name"] == "docx"
    assert latest["last_run"]["stats"]["headings"] == 2

    extraction = (
        await api.client.get(f"{s['version_url']}/extraction", headers=s["headers"])
    ).json()
    req = next(b for b in extraction["document"]["blocks"] if "REQ-PAY-014" in b["text"])
    assert req["location"]["heading_path"] == ["Payments SRS", "3.2 Card payments"]
    assert extraction["document"]["source"]["filename"] == "Payments SRS.docx"

    # Running again changes nothing (activities are retried by Temporal).
    again = await worker.extract(s["org"], s["version"])
    assert again.run_id == outcome.run_id


async def test_infected_file_never_reaches_a_parser(api: Any, worker: Worker) -> None:
    s = await setup(api, b"# Notes\n" + EICAR, "notes.md")
    assert await worker.scan(s["org"], s["version"]) == "quarantined"
    assert (await worker.extract(s["org"], s["version"])).status == "quarantined"

    detail = (await api.client.get(s["doc_url"], headers=s["headers"])).json()
    assert detail["latest_version"]["status"] == "quarantined"
    assert detail["latest_version"]["last_run"] is None  # no processing run was ever opened
    r = await api.client.get(f"{s['version_url']}/extraction", headers=s["headers"])
    assert r.status_code == 404


async def test_disguised_file_fails_with_a_clear_code(api: Any, worker: Worker) -> None:
    s = await setup(api, b"MZ this is really a program", "requirements.docx")
    await worker.scan(s["org"], s["version"])
    outcome = await worker.extract(s["org"], s["version"])
    assert outcome.status == "processing_failed"
    assert outcome.error_code == "content_does_not_match_type"
    detail = (await api.client.get(s["doc_url"], headers=s["headers"])).json()
    assert detail["latest_version"]["last_run"]["error_code"] == "content_does_not_match_type"


async def test_a_file_changed_in_storage_after_upload_is_caught(
    api: Any, worker: Worker, s3_endpoint: str
) -> None:
    s = await setup(api, b"# Approved SRS", "srs.md")
    await worker.scan(s["org"], s["version"])
    s3 = boto3.client("s3", endpoint_url=s3_endpoint, region_name="eu-west-1")
    key = f"org/{s['org']}/project/"
    obj = next(
        o["Key"]
        for o in s3.list_objects_v2(Bucket="workforce-uploads", Prefix=key)["Contents"]
        if f"/{s['doc_url'].rsplit('/', 1)[1]}/" in o["Key"]
    )
    s3.put_object(Bucket="workforce-uploads", Key=obj, Body=b"# Tampered SRS")
    outcome = await worker.extract(s["org"], s["version"])
    assert outcome.error_code == "content_changed"


async def test_failed_processing_can_be_retried_by_a_manager(api: Any, worker: Worker) -> None:
    s = await setup(api, b"MZ not a docx", "x.docx")
    await worker.scan(s["org"], s["version"])
    await worker.extract(s["org"], s["version"])

    member = await api.sign_in()
    await api.add_member(s["org"], await api.user_id(member), "member")
    denied = await api.client.post(
        f"{s['version_url']}/process", headers=api.in_org(member, s["org"])
    )
    assert denied.status_code == 403

    started = await api.client.post(f"{s['version_url']}/process", headers=s["headers"])
    assert started.status_code == 202
    assert started.json()["workflow_id"] == f"process-document-{s['version']}"

    # A retry runs a second attempt with its own run record.
    second = await worker.extract(s["org"], s["version"])
    assert second.status == "processing_failed"
    detail = (await api.client.get(s["doc_url"], headers=s["headers"])).json()
    assert detail["latest_version"]["last_run"]["attempt"] == 2


async def test_ready_versions_cannot_be_reprocessed(api: Any, worker: Worker) -> None:
    s = await setup(api, b"# SRS", "srs.md")
    await worker.scan(s["org"], s["version"])
    await worker.extract(s["org"], s["version"])
    r = await api.client.post(f"{s['version_url']}/process", headers=s["headers"])
    assert r.status_code == 409


async def test_a_crash_mid_extraction_resumes_the_same_run(
    api: Any, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await setup(api, b"# SRS\n\nBody.", "srs.md")
    await worker.scan(s["org"], s["version"])

    real = worker.store.get_bytes
    calls = {"n": 0}

    async def flaky(**kwargs: Any) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("worker lost its connection")
        return await real(**kwargs)

    monkeypatch.setattr(worker.store, "get_bytes", flaky)
    with pytest.raises(ConnectionError):
        await worker.extract(s["org"], s["version"])  # Temporal would retry this activity

    outcome = await worker.extract(s["org"], s["version"])
    assert outcome.status == "ready"
    detail = (await api.client.get(s["doc_url"], headers=s["headers"])).json()
    assert detail["latest_version"]["last_run"]["attempt"] == 1  # resumed, not duplicated


async def test_scan_waits_for_an_uncommitted_upload(api: Any, worker: Worker) -> None:
    admin = await api.sign_in()
    org = await api.create_org(admin)
    headers = api.in_org(admin, org["id"])
    project = (
        await api.client.post(
            "/api/v1/projects",
            json={"key": "W" + uuid.uuid4().hex[:5].upper(), "name": "W", "type": "software"},
            headers=headers,
        )
    ).json()
    started = await api.upload_document(headers, project["id"], complete=False)
    assert await worker.scan(org["id"], started["version"]["id"]) == "not_ready"
