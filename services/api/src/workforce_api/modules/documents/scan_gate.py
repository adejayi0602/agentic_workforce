"""The malware scan gate (ADR-0012, threat T10). Runs in the worker, as `workforce_worker`.

Every version is scanned before anything reads it. `ensure_parseable` is the one check every
parser must pass first: only a version that passed the scan gets through.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.db import set_tenant_context
from workforce_api.modules.audit import service as audit
from workforce_api.modules.documents.lifecycle import PARSEABLE, VersionStatus, transition
from workforce_api.modules.documents.models import DocumentVersion, ProjectDocument
from workforce_intake.scanning import ScanResult, Verdict

SCANNER_ACTOR = "document-scanner"


class NotParseableError(Exception):
    """Raised when something tries to parse a version that hasn't passed the scan."""

    def __init__(self, version_id: uuid.UUID, status: str) -> None:
        super().__init__(f"Version {version_id} is {status}; only scanned, clean files are parsed.")
        self.version_id = version_id
        self.status = status


async def load_version(
    session: AsyncSession, *, organisation_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[DocumentVersion, ProjectDocument]:
    """Set the tenant context from the workflow input, then load the version (locked)."""
    await set_tenant_context(session, organisation_id=organisation_id, user_id=None)
    version = await session.scalar(
        select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise LookupError(f"Document version {version_id} not found in this organisation.")
    document = await session.scalar(
        select(ProjectDocument).where(ProjectDocument.id == version.document_id)
    )
    assert document is not None  # noqa: S101 - composite FK guarantees it
    return version, document


async def start_scan(session: AsyncSession, version: DocumentVersion) -> DocumentVersion:
    """uploaded or scan_failed -> scanning. Already scanning: nothing to do (idempotent)."""
    status = VersionStatus(version.status)
    if status != VersionStatus.SCANNING:
        version.status = transition(status, VersionStatus.SCANNING)
        await session.flush()
    return version


async def record_verdict(
    session: AsyncSession,
    version: DocumentVersion,
    document: ProjectDocument,
    result: ScanResult,
) -> DocumentVersion:
    """Apply a scanner verdict. PENDING changes nothing: the workflow asks again later."""
    if result.verdict == Verdict.PENDING:
        return version

    target = {
        Verdict.CLEAN: VersionStatus.CLEAN,
        Verdict.INFECTED: VersionStatus.QUARANTINED,
        Verdict.FAILED: VersionStatus.SCAN_FAILED,
    }[result.verdict]
    version.status = transition(VersionStatus(version.status), target)
    version.scanned_at = datetime.now(UTC)
    version.scan_result = {
        "engine": result.engine,
        "verdict": result.verdict.value,
        **result.details,
    }
    await session.flush()

    infected = result.verdict == Verdict.INFECTED
    await audit.record(
        session,
        organisation_id=version.organisation_id,
        project_id=document.project_id,
        actor_type="system",
        actor_id=SCANNER_ACTOR,
        action="document.quarantine" if infected else "document.scan",
        resource_type="document_version",
        resource_id=str(version.id),
        decision="denied" if infected else "allowed",
        details={
            "document_id": str(document.id),
            "version": version.version,
            "verdict": result.verdict.value,
            "engine": result.engine,
            **result.details,
        },
    )
    await audit.emit(
        session,
        organisation_id=version.organisation_id,
        aggregate_type="document_version",
        aggregate_id=version.id,
        event_type=f"document.version_{target.value}",
        payload={"document_id": str(document.id), "version_id": str(version.id)},
    )
    return version


def ensure_parseable(version: DocumentVersion) -> None:
    """The gate. Call before reading a version's content for parsing."""
    if VersionStatus(version.status) not in PARSEABLE:
        raise NotParseableError(version.id, version.status)
