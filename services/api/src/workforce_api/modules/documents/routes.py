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
from workforce_api.modules.documents import service
from workforce_api.modules.documents.file_policy import MAX_BYTES, accept
from workforce_api.modules.documents.models import DocumentVersion, ProjectDocument
from workforce_api.modules.idempotency import service as idempotency
from workforce_api.modules.projects import service as projects
from workforce_api.storage import ObjectStore, PresignedUpload

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
Category = Literal["srs", "brief", "architecture", "supporting"]


def get_store(request: Request) -> ObjectStore:
    store: ObjectStore = request.app.state.object_store
    return store


Store = Annotated[ObjectStore, Depends(get_store)]


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


def _version(v: DocumentVersion) -> VersionOut:
    return VersionOut.model_validate(v, from_attributes=True)


def _document(d: ProjectDocument, latest: DocumentVersion | None) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        title=d.title,
        category=d.category,
        created_at=d.created_at,
        latest_version=_version(latest) if latest else None,
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
    return [_document(d, v) for d, v in await service.list_documents(session, project)]


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
    base = _document(document, versions[0] if versions else None)
    return DocumentDetail(**base.model_dump(), versions=[_version(v) for v in versions])


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
    request: Request,
) -> VersionOut:
    """Confirm the upload. The API checks the stored file's size and SHA-256 itself."""
    project = await projects.get_project(session, context, project_id)
    document = await service.get_document(session, project, document_id)
    version = await service.get_version(session, document, version_id)
    database: Database = request.app.state.database
    completed = await service.complete_upload(
        session, context, document, version, store=store, database=database
    )
    return _version(completed)
