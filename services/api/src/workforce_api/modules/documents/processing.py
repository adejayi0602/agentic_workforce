"""The two processing steps the worker runs for each version: scan, then extract.

Both are safe to run more than once (Temporal retries activities). Each opens its own
transactions as the worker role and sets the tenant context from its input.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from anyio import to_thread
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Registers every table, so foreign keys resolve when this runs outside the API (the worker).
import workforce_api.models  # noqa: F401
from workforce_api.modules.audit import service as audit
from workforce_api.modules.documents import scan_gate
from workforce_api.modules.documents.file_policy import MAX_BYTES
from workforce_api.modules.documents.lifecycle import VersionStatus, transition
from workforce_api.modules.documents.models import DocumentProcessingRun
from workforce_api.storage import ObjectStore
from workforce_intake.extraction import ExtractionError, extract
from workforce_intake.scanning import Scanner, Verdict

PROCESSOR_ACTOR = "document-processor"


class ScanOutcome(StrEnum):
    CLEAN = "clean"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    PENDING = "pending"  # no verdict yet: ask again later
    NOT_READY = "not_ready"  # the upload isn't committed yet: ask again shortly


@dataclass(frozen=True)
class ExtractOutcome:
    status: str  # ready | needs_ocr | processing_failed | quarantined | not_parseable
    run_id: str | None = None
    error_code: str | None = None


Sessions = async_sessionmaker[AsyncSession]


async def scan_step(
    sessions: Sessions,
    store: ObjectStore,
    scanner: Scanner,
    *,
    organisation_id: uuid.UUID,
    version_id: uuid.UUID,
    needs_content: bool,
) -> ScanOutcome:
    async with sessions() as session, session.begin():
        version, document = await scan_gate.load_version(
            session, organisation_id=organisation_id, version_id=version_id
        )
        status = VersionStatus(version.status)
        already = {
            VersionStatus.QUARANTINED: ScanOutcome.QUARANTINED,
            VersionStatus.CLEAN: ScanOutcome.CLEAN,
            VersionStatus.PROCESSING: ScanOutcome.CLEAN,
            VersionStatus.PROCESSING_FAILED: ScanOutcome.CLEAN,
            VersionStatus.READY: ScanOutcome.CLEAN,
            VersionStatus.NEEDS_OCR: ScanOutcome.CLEAN,
        }
        if status in already:
            return already[status]  # an earlier attempt already got a verdict
        if status in {VersionStatus.AWAITING_UPLOAD, VersionStatus.EXPIRED}:
            return ScanOutcome.NOT_READY
        await scan_gate.start_scan(session, version)
        bucket, key = version.s3_bucket, version.s3_key

    content = (
        await store.get_bytes(bucket=bucket, key=key, max_bytes=MAX_BYTES) if needs_content else b""
    )
    result = await to_thread.run_sync(lambda: scanner.scan(bucket=bucket, key=key, content=content))

    async with sessions() as session, session.begin():
        version, document = await scan_gate.load_version(
            session, organisation_id=organisation_id, version_id=version_id
        )
        if VersionStatus(version.status) != VersionStatus.SCANNING:
            return ScanOutcome.CLEAN if version.status != "quarantined" else ScanOutcome.QUARANTINED
        await scan_gate.record_verdict(session, version, document, result)
    return {
        Verdict.CLEAN: ScanOutcome.CLEAN,
        Verdict.INFECTED: ScanOutcome.QUARANTINED,
        Verdict.FAILED: ScanOutcome.FAILED,
        Verdict.PENDING: ScanOutcome.PENDING,
    }[result.verdict]


async def extract_step(
    sessions: Sessions,
    store: ObjectStore,
    *,
    organisation_id: uuid.UUID,
    version_id: uuid.UUID,
    workflow_id: str,
    artefacts_bucket: str,
) -> ExtractOutcome:
    # 1. Claim: pass the gate, move to processing, open (or resume) a run.
    async with sessions() as session, session.begin():
        version, _ = await scan_gate.load_version(
            session, organisation_id=organisation_id, version_id=version_id
        )
        status = VersionStatus(version.status)
        if status in {VersionStatus.READY, VersionStatus.NEEDS_OCR}:
            run = await _latest_run(session, version_id)
            return ExtractOutcome(status.value, str(run.id) if run else None)
        if status == VersionStatus.QUARANTINED:
            return ExtractOutcome("quarantined")
        try:
            scan_gate.ensure_parseable(version)
        except scan_gate.NotParseableError:
            return ExtractOutcome("not_parseable")
        run = await _latest_run(session, version_id)
        if status == VersionStatus.PROCESSING and run is not None and run.status == "running":
            pass  # a crashed attempt: resume its run
        else:
            version.status = transition(status, VersionStatus.PROCESSING)
            attempt = (run.attempt if run else 0) + 1
            run = DocumentProcessingRun(
                id=uuid.uuid4(),
                organisation_id=organisation_id,
                document_version_id=version_id,
                attempt=attempt,
                status="running",
                workflow_id=workflow_id,
            )
            session.add(run)
            await session.flush()
        run_id = run.id
        source = (version.s3_bucket, version.s3_key, version.filename, version.media_type)
        expected_sha = version.sha256
        artefact_key = version.s3_key.rsplit("/", 1)[0] + f"/extraction/{run_id}.json"

    bucket, key, filename, media_type = source

    # 2. Work, outside any transaction: read, re-verify, parse, store the result.
    error_code: str | None = None
    result_json: bytes | None = None
    try:
        content = await store.get_bytes(bucket=bucket, key=key, max_bytes=MAX_BYTES)
        if hashlib.sha256(content).hexdigest() != expected_sha:
            raise ExtractionError(
                "content_changed", "The stored file no longer matches its checksum."
            )
        document = await to_thread.run_sync(
            lambda: extract(content, filename=filename, media_type=media_type, sha256=expected_sha)
        )
        result_json = json.dumps(document.model_dump(mode="json"), sort_keys=True).encode()
        await store.put_bytes(
            bucket=artefacts_bucket,
            key=artefact_key,
            data=result_json,
            content_type="application/json",
        )
    except ExtractionError as exc:
        error_code = exc.code

    # 3. Record the outcome.
    async with sessions() as session, session.begin():
        version, doc = await scan_gate.load_version(
            session, organisation_id=organisation_id, version_id=version_id
        )
        run = await session.get(DocumentProcessingRun, run_id, with_for_update=True)
        assert run is not None  # noqa: S101 - created above in this organisation
        now = datetime.now(UTC)
        if error_code is None and result_json is not None:
            parsed = json.loads(result_json)
            target = VersionStatus.NEEDS_OCR if parsed["needs_ocr"] else VersionStatus.READY
            run.status = "needs_ocr" if parsed["needs_ocr"] else "succeeded"
            run.parser_name = parsed["parser"]["name"]
            run.parser_version = f"{parsed['parser']['version']} ({parsed['parser']['library']})"
            run.result_s3_key = artefact_key
            run.result_sha256 = hashlib.sha256(result_json).hexdigest()
            run.stats = {**parsed["stats"], "warnings": parsed["warnings"]}
        else:
            target = VersionStatus.PROCESSING_FAILED
            run.status = "failed"
            run.error_code = error_code
        run.finished_at = now
        version.status = transition(VersionStatus(version.status), target)
        version.processed_at = now
        await session.flush()
        await audit.record(
            session,
            organisation_id=organisation_id,
            project_id=doc.project_id,
            actor_type="system",
            actor_id=PROCESSOR_ACTOR,
            action="document.process",
            resource_type="document_version",
            resource_id=str(version_id),
            decision="allowed",
            details={
                "document_id": str(doc.id),
                "version": version.version,
                "outcome": target.value,
                "run_id": str(run_id),
                **({"error_code": error_code} if error_code else {}),
            },
        )
        await audit.emit(
            session,
            organisation_id=organisation_id,
            aggregate_type="document_version",
            aggregate_id=version_id,
            event_type=f"document.version_{target.value}",
            payload={
                "document_id": str(doc.id),
                "version_id": str(version_id),
                "run_id": str(run_id),
            },
        )
    return ExtractOutcome(target.value, str(run_id), error_code)


async def _latest_run(session: AsyncSession, version_id: uuid.UUID) -> DocumentProcessingRun | None:
    latest = await session.scalar(
        select(func.max(DocumentProcessingRun.attempt)).where(
            DocumentProcessingRun.document_version_id == version_id
        )
    )
    if latest is None:
        return None
    return await session.scalar(
        select(DocumentProcessingRun).where(
            DocumentProcessingRun.document_version_id == version_id,
            DocumentProcessingRun.attempt == latest,
        )
    )
