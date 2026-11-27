"""Document intake: upload sessions and completion (FR-001, FR-002, ADR-0012)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.tenancy import OrgContext
from workforce_api.config import Settings
from workforce_api.db import Database
from workforce_api.errors import ApiError
from workforce_api.modules.audit import service as audit
from workforce_api.modules.documents.file_policy import MAX_BYTES, AcceptedFile
from workforce_api.modules.documents.lifecycle import VersionStatus, transition
from workforce_api.modules.documents.models import DocumentVersion, ProjectDocument
from workforce_api.modules.projects.models import Project
from workforce_api.storage import ObjectStore, PresignedUpload
from workforce_contracts import ErrorCode


@dataclass(frozen=True)
class NewUpload:
    document: ProjectDocument
    version: DocumentVersion
    upload: PresignedUpload


def object_key(org: uuid.UUID, project: uuid.UUID, document: uuid.UUID, version: int) -> str:
    return f"org/{org}/project/{project}/documents/{document}/v{version}/original"


async def create_document(
    session: AsyncSession,
    context: OrgContext,
    project: Project,
    *,
    title: str | None,
    category: str,
    file: AcceptedFile,
    store: ObjectStore,
    settings: Settings,
) -> NewUpload:
    _ensure_active(project)
    document = ProjectDocument(
        id=uuid.uuid4(),
        organisation_id=context.organisation_id,
        project_id=project.id,
        title=(title or file.filename.rsplit(".", 1)[0])[:200],
        category=category,
        created_by=context.user.id,
    )
    session.add(document)
    await session.flush()
    await session.refresh(document)
    version, upload = await _new_version(session, context, document, 1, file, store, settings)
    await _audit(session, context, document, version, "document.create", {"category": category})
    return NewUpload(document=document, version=version, upload=upload)


async def add_version(
    session: AsyncSession,
    context: OrgContext,
    project: Project,
    document: ProjectDocument,
    *,
    file: AcceptedFile,
    store: ObjectStore,
    settings: Settings,
) -> NewUpload:
    _ensure_active(project)
    # Lock the document so two uploads can't both claim the same version number.
    await session.execute(
        select(ProjectDocument.id).where(ProjectDocument.id == document.id).with_for_update()
    )
    latest = await session.scalar(
        select(func.max(DocumentVersion.version)).where(DocumentVersion.document_id == document.id)
    )
    number = (latest or 0) + 1
    version, upload = await _new_version(session, context, document, number, file, store, settings)
    await _audit(session, context, document, version, "document.version_create", {})
    return NewUpload(document=document, version=version, upload=upload)


async def complete_upload(
    session: AsyncSession,
    context: OrgContext,
    document: ProjectDocument,
    version: DocumentVersion,
    *,
    store: ObjectStore,
    database: Database,
) -> DocumentVersion:
    """Verify the stored object against what was declared, then mark the version uploaded.

    The API reads the object and computes its size and SHA-256 itself. S3's own checks are a
    first layer; this is the one we rely on. Completing twice is harmless.
    """
    status = VersionStatus(version.status)
    if status != VersionStatus.AWAITING_UPLOAD:
        if status == VersionStatus.EXPIRED:
            raise _expired()
        return version  # already completed: idempotent
    if datetime.now(UTC) > version.upload_expires_at:
        raise _expired()

    stored = await store.measure(bucket=version.s3_bucket, key=version.s3_key, max_bytes=MAX_BYTES)
    if stored is None:
        raise ApiError(
            ErrorCode.UPLOAD_INCOMPLETE,
            "The file hasn't been uploaded yet. Upload it to the link provided, then try again.",
            status_code=409,
        )
    if stored.size != version.size_bytes or stored.sha256_hex != version.sha256:
        # The request rolls back, so record the refusal in its own transaction.
        await audit.record_denial(
            database,
            organisation_id=context.organisation_id,
            user_id=context.user.id,
            action="document.upload_complete",
            resource_type="document_version",
            details={"reason": "checksum_mismatch", "version_id": str(version.id)},
        )
        raise ApiError(
            ErrorCode.CHECKSUM_MISMATCH,
            "The uploaded file doesn't match the one declared. Please upload it again.",
            status_code=422,
            details={
                "expected_size": version.size_bytes,
                "actual_size": stored.size if stored.size <= MAX_BYTES else f">{MAX_BYTES}",
            },
        )

    version.status = transition(status, VersionStatus.UPLOADED)
    version.uploaded_at = datetime.now(UTC)
    await session.flush()
    await _audit(session, context, document, version, "document.upload_complete", {})
    await audit.emit(
        session,
        organisation_id=context.organisation_id,
        aggregate_type="document_version",
        aggregate_id=version.id,
        event_type="document.version_uploaded",
        payload={
            "document_id": str(document.id),
            "version_id": str(version.id),
            "version": version.version,
            "project_id": str(document.project_id),
        },
    )
    return version


async def list_documents(
    session: AsyncSession, project: Project
) -> list[tuple[ProjectDocument, DocumentVersion | None]]:
    documents = list(
        await session.scalars(
            select(ProjectDocument)
            .where(ProjectDocument.project_id == project.id)
            .order_by(ProjectDocument.created_at.desc(), ProjectDocument.id.desc())
        )
    )
    latest = await _latest_versions(session, [d.id for d in documents])
    return [(d, latest.get(d.id)) for d in documents]


async def get_document(
    session: AsyncSession, project: Project, document_id: uuid.UUID
) -> ProjectDocument:
    document = await session.scalar(
        select(ProjectDocument).where(
            ProjectDocument.id == document_id, ProjectDocument.project_id == project.id
        )
    )
    if document is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Document not found.", status_code=404)
    return document


async def list_versions(session: AsyncSession, document: ProjectDocument) -> list[DocumentVersion]:
    return list(
        await session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version.desc())
        )
    )


async def get_version(
    session: AsyncSession, document: ProjectDocument, version_id: uuid.UUID
) -> DocumentVersion:
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id, DocumentVersion.document_id == document.id
        )
    )
    if version is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Document version not found.", status_code=404)
    return version


# ---- helpers ----


async def _new_version(
    session: AsyncSession,
    context: OrgContext,
    document: ProjectDocument,
    number: int,
    file: AcceptedFile,
    store: ObjectStore,
    settings: Settings,
) -> tuple[DocumentVersion, PresignedUpload]:
    key = object_key(context.organisation_id, document.project_id, document.id, number)
    upload = store.presign_put(
        bucket=settings.s3_bucket_uploads,
        key=key,
        content_type=file.media_type,
        size=file.size_bytes,
        sha256_b64=file.sha256_b64,
        ttl_seconds=settings.upload_url_ttl_seconds,
    )
    version = DocumentVersion(
        id=uuid.uuid4(),
        organisation_id=context.organisation_id,
        document_id=document.id,
        version=number,
        filename=file.filename,
        media_type=file.media_type,
        size_bytes=file.size_bytes,
        sha256=file.sha256_hex,
        s3_bucket=settings.s3_bucket_uploads,
        s3_key=key,
        status=VersionStatus.AWAITING_UPLOAD.value,
        uploaded_by=context.user.id,
        upload_expires_at=upload.expires_at + timedelta(seconds=60),  # small grace for clocks
    )
    session.add(version)
    await session.flush()
    await session.refresh(version)
    return version, upload


async def _latest_versions(
    session: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, DocumentVersion]:
    if not document_ids:
        return {}
    rows = await session.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id.in_(document_ids))
        .distinct(DocumentVersion.document_id)
        .order_by(DocumentVersion.document_id, DocumentVersion.version.desc())
    )
    return {v.document_id: v for v in rows}


def _ensure_active(project: Project) -> None:
    if project.status != "active":
        raise ApiError(
            ErrorCode.INVALID_STATE,
            "Documents can't be added to an archived project.",
            status_code=409,
        )


def _expired() -> ApiError:
    return ApiError(
        ErrorCode.UPLOAD_EXPIRED,
        "This upload link has expired. Start a new upload.",
        status_code=409,
    )


async def _audit(
    session: AsyncSession,
    context: OrgContext,
    document: ProjectDocument,
    version: DocumentVersion,
    action: str,
    extra: dict[str, Any],
) -> None:
    await audit.record(
        session,
        organisation_id=context.organisation_id,
        project_id=document.project_id,
        actor_type="user",
        actor_id=str(context.user.id),
        action=action,
        resource_type="document_version",
        resource_id=str(version.id),
        details={
            "document_id": str(document.id),
            "version": version.version,
            "filename": version.filename,
            "size_bytes": version.size_bytes,
            **extra,
        },
    )
