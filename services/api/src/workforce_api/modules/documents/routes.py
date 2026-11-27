import json
import logging
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.permissions import Permission
from workforce_api.auth.tenancy import OrgContext, require
from workforce_api.config import Settings
from workforce_api.db import Database, get_db_session
from workforce_api.errors import ApiError
from workforce_api.modules.documents import service
from workforce_api.modules.documents.file_policy import MAX_BYTES, accept
from workforce_api.modules.documents.models import (
    DocumentProcessingRun,
    DocumentVersion,
    ProjectDocument,
)
from workforce_api.modules.idempotency import service as idempotency
from workforce_api.modules.projects import service as projects
from workforce_api.storage import ObjectStore, PresignedUpload
from workforce_api.workflows import WorkflowStarter
from workforce_contracts import ErrorCode
from workforce_intake.extraction.model import NormalisedDocument

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
Category = Literal["srs", "brief", "architecture", "supporting"]


def get_store(request: Request) -> ObjectStore:
    store: ObjectStore = request.app.state.object_store
    return store


Store = Annotated[ObjectStore, Depends(get_store)]


def get_workflows(request: Request) -> WorkflowStarter:
    starter: WorkflowStarter = request.app.state.workflows
    return starter


Workflows = Annotated[WorkflowStarter, Depends(get_workflows)]


class FileDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255, examples=["payments-srs.docx"])
    size_bytes: int = Field(gt=0, le=MAX_BYTES, description="Exact size in bytes (max 15 MB)")
    sha256: str = Field(description="SHA-256 of the file, 64 hex characters")


class DocumentCreate(FileDeclaration):
    title: str | None = Field(default=None, max_length=200, description="Defaults to the filename")
    category: Category = "supporting"


class UploadOut(BaseModel):
    url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    expires_at: datetime


class RunOut(BaseModel):
    id: uuid.UUID
    attempt: int
    status: str
    parser_name: str | None
    parser_version: str | None
    error_code: str | None
    stats: dict[str, object]
    started_at: datetime
    finished_at: datetime | None


class VersionOut(BaseModel):
    id: uuid.UUID
    version: int
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime
    uploaded_at: datetime | None
    scanned_at: datetime | None
    processed_at: datetime | None
    last_run: RunOut | None = None


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    created_at: datetime
    latest_version: VersionOut | None


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class UploadStarted(BaseModel):
    document: DocumentOut
    version: VersionOut
    upload: UploadOut


def _version(v: DocumentVersion, run: DocumentProcessingRun | None = None) -> VersionOut:
    out = VersionOut.model_validate(v, from_attributes=True)
    if run is not None:
        out.last_run = RunOut.model_validate(run, from_attributes=True)
    return out


def _document(
    d: ProjectDocument,
    latest: DocumentVersion | None,
    run: DocumentProcessingRun | None = None,
) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        title=d.title,
        category=d.category,
        created_at=d.created_at,
        latest_version=_version(latest, run) if latest else None,
    )


def _upload(u: PresignedUpload) -> UploadOut:
    return UploadOut(url=u.url, method="PUT", headers=u.headers, expires_at=u.expires_at)


@router.post("", response_model=UploadStarted, status_code=201)
async def create_document(
    project_id: uuid.UUID,
    body: DocumentCreate,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_UPLOAD))],
    session: Session,
    store: Store,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias=idempotency.IDEMPOTENCY_HEADER)] = None,
) -> UploadStarted | JSONResponse:
    """Start uploading a new document. PUT the file to `upload.url` with `upload.headers`,
    then call `.../versions/{version_id}/complete`."""
    reservation = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            organisation_id=context.organisation_id,
            user_id=context.user.id,
            key=idempotency_key,
            operation=f"POST /api/v1/projects/{project_id}/documents",
            body=body,
        )
        if isinstance(outcome, idempotency.StoredResponse):
            return JSONResponse(
                status_code=outcome.status_code,
                content=outcome.body,
                headers={idempotency.REPLAYED_HEADER: "true"},
            )
        reservation = outcome

    file = accept(body.filename, body.size_bytes, body.sha256)
    project = await projects.get_project(session, context, project_id)
    settings: Settings = request.app.state.settings
    started = await service.create_document(
        session,
        context,
        project,
        title=body.title,
        category=body.category,
        file=file,
        store=store,
        settings=settings,
    )
    result = UploadStarted(
        document=_document(started.document, started.version),
        version=_version(started.version),
        upload=_upload(started.upload),
    )
    if reservation:
        await idempotency.complete(session, reservation, status_code=201, body=result)
    return result


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    project_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_READ))],
    session: Session,
) -> list[DocumentOut]:
    project = await projects.get_project(session, context, project_id)
    listed = await service.list_documents(session, project)
    runs = await service.latest_runs(session, [v.id for _, v in listed if v is not None])
    return [_document(d, v, runs.get(v.id) if v else None) for d, v in listed]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_READ))],
    session: Session,
) -> DocumentDetail:
    project = await projects.get_project(session, context, project_id)
    document = await service.get_document(session, project, document_id)
    versions = await service.list_versions(session, document)
    runs = await service.latest_runs(session, [v.id for v in versions])
    latest = versions[0] if versions else None
    base = _document(document, latest, runs.get(latest.id) if latest else None)
    return DocumentDetail(
        **base.model_dump(), versions=[_version(v, runs.get(v.id)) for v in versions]
    )


@router.post("/{document_id}/versions", response_model=UploadStarted, status_code=201)
async def add_version(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: FileDeclaration,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_UPLOAD))],
    session: Session,
    store: Store,
    request: Request,
) -> UploadStarted:
    """Upload a new version of an existing document. Earlier versions are kept unchanged."""
    file = accept(body.filename, body.size_bytes, body.sha256)
    project = await projects.get_project(session, context, project_id)
    document = await service.get_document(session, project, document_id)
    settings: Settings = request.app.state.settings
    started = await service.add_version(
        session, context, project, document, file=file, store=store, settings=settings
    )
    return UploadStarted(
        document=_document(document, started.version),
        version=_version(started.version),
        upload=_upload(started.upload),
    )


@router.post("/{document_id}/versions/{version_id}/complete", response_model=VersionOut)
async def complete_upload(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_UPLOAD))],
    session: Session,
    store: Store,
    workflows: Workflows,
    request: Request,
) -> VersionOut:
    """Confirm the upload. The API checks the stored file's size and SHA-256 itself, then
    starts scanning and processing."""
    project = await projects.get_project(session, context, project_id)
    document = await service.get_document(session, project, document_id)
    version = await service.get_version(session, document, version_id)
    database: Database = request.app.state.database
    was_waiting = version.status == "awaiting_upload"
    completed = await service.complete_upload(
        session, context, document, version, store=store, database=database
    )
    result = _version(completed)
    if was_waiting:
        # Commit first, so the worker never sees an upload that might still roll back.
        await session.commit()
        await _start(workflows, context.organisation_id, completed.id)
    return result


class ProcessingStarted(BaseModel):
    workflow_id: str | None
    started: bool


@router.post(
    "/{document_id}/versions/{version_id}/process",
    response_model=ProcessingStarted,
    status_code=202,
)
async def process_version(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_PROCESS))],
    session: Session,
    workflows: Workflows,
) -> ProcessingStarted:
    """Start or retry scanning and processing (for example after a failure)."""
    project = await projects.get_project(session, context, project_id)
    document = await service.get_document(session, project, document_id)
    version = await service.get_version(session, document, version_id)
    await service.request_processing(session, context, document, version)
    await session.commit()
    workflow_id = await _start(workflows, context.organisation_id, version.id)
    return ProcessingStarted(workflow_id=workflow_id, started=workflow_id is not None)


class Extraction(BaseModel):
    run: RunOut
    document: NormalisedDocument


@router.get("/{document_id}/versions/{version_id}/extraction", response_model=Extraction)
async def get_extraction(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.DOCUMENT_READ))],
    session: Session,
    store: Store,
    request: Request,
) -> Extraction:
    """The structured content extracted from a processed version, with source locations."""
    project = await projects.get_project(session, context, project_id)
    document = await service.get_document(session, project, document_id)
    version = await service.get_version(session, document, version_id)
    run = (await service.latest_runs(session, [version.id])).get(version.id)
    if run is None or run.result_s3_key is None or version.status not in {"ready", "needs_ocr"}:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "This version hasn't been processed yet.",
            status_code=404,
            details={"status": version.status},
        )
    settings: Settings = request.app.state.settings
    raw = await store.get_bytes(
        bucket=settings.s3_bucket_artefacts, key=run.result_s3_key, max_bytes=50 * 1024 * 1024
    )
    return Extraction(
        run=RunOut.model_validate(run, from_attributes=True),
        document=NormalisedDocument.model_validate(json.loads(raw)),
    )


async def _start(
    workflows: WorkflowStarter, organisation_id: uuid.UUID, version_id: uuid.UUID
) -> str | None:
    """Start processing. If Temporal is unreachable the upload still stands; processing can
    be started later with POST .../process."""
    try:
        return await workflows.start_document_processing(
            organisation_id=organisation_id, version_id=version_id
        )
    except Exception:
        logger.exception("Could not start processing for version %s", version_id)
        return None
