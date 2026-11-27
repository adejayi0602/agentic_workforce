"""Document processing activities. Thin: the logic lives in workforce_api's processing module."""

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from workforce_api.modules.documents import processing
from workforce_api.storage import ObjectStore
from workforce_intake.scanning import Scanner


class VersionRef(BaseModel):
    organisation_id: uuid.UUID
    version_id: uuid.UUID


class ExtractResult(BaseModel):
    status: str
    run_id: str | None = None
    error_code: str | None = None


class DocumentActivities:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        store: ObjectStore,
        scanner: Scanner,
        artefacts_bucket: str,
    ) -> None:
        self._sessions = sessions
        self._store = store
        self._scanner = scanner
        self._artefacts_bucket = artefacts_bucket

    @activity.defn(name="scan_document_version")
    async def scan(self, ref: VersionRef) -> str:
        outcome = await processing.scan_step(
            self._sessions,
            self._store,
            self._scanner,
            organisation_id=ref.organisation_id,
            version_id=ref.version_id,
            needs_content=self._scanner.engine != "aws-guardduty",
        )
        if outcome in {processing.ScanOutcome.PENDING, processing.ScanOutcome.NOT_READY}:
            # Retryable by design: Temporal asks again after its backoff.
            raise ApplicationError(f"Scan {outcome.value}; will retry.", type="ScanNotReady")
        return outcome.value

    @activity.defn(name="extract_document_version")
    async def extract(self, ref: VersionRef) -> ExtractResult:
        outcome = await processing.extract_step(
            self._sessions,
            self._store,
            organisation_id=ref.organisation_id,
            version_id=ref.version_id,
            workflow_id=activity.info().workflow_id or "",
            artefacts_bucket=self._artefacts_bucket,
        )
        return ExtractResult(
            status=outcome.status, run_id=outcome.run_id, error_code=outcome.error_code
        )
