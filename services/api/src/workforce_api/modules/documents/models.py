"""Project documents, their immutable versions, and processing runs (spec §5, ADR-0012).

Composite foreign keys tie each row's organisation_id to its parent's, so the database itself
refuses a row whose organisation doesn't match its parent, independently of RLS.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from workforce_api.db.base import Base, created_at, updated_at, uuid_pk

CATEGORIES = ("srs", "brief", "architecture", "supporting")
STATUSES = (
    "awaiting_upload",
    "uploaded",
    "expired",
    "scanning",
    "clean",
    "quarantined",
    "scan_failed",
    "processing",
    "ready",
    "needs_ocr",
    "processing_failed",
)
RUN_STATUSES = ("running", "succeeded", "needs_ocr", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ProjectDocument(Base):
    """A logical document in a project. Its content lives in versions."""

    __tablename__ = "project_documents"
    __table_args__ = (
        UniqueConstraint("id", "organisation_id"),
        ForeignKeyConstraint(
            ["project_id", "organisation_id"],
            ["projects.id", "projects.organisation_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("category", CATEGORIES), name="category"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DocumentVersion(Base):
    """One immutable upload. Status changes only along lifecycle.TRANSITIONS."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version"),
        UniqueConstraint("id", "organisation_id"),
        UniqueConstraint("s3_key"),
        ForeignKeyConstraint(
            ["document_id", "organisation_id"],
            ["project_documents.id", "project_documents.organisation_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("status", STATUSES), name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 15728640", name="size_limit"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    s3_bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DocumentProcessingRun(Base):
    """One attempt to extract a version. Records exactly which parser produced the result."""

    __tablename__ = "document_processing_runs"
    __table_args__ = (
        UniqueConstraint("document_version_id", "attempt"),
        ForeignKeyConstraint(
            ["document_version_id", "organisation_id"],
            ["document_versions.id", "document_versions.organisation_id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("status", RUN_STATUSES), name="status"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    workflow_id: Mapped[str | None] = mapped_column(String(200))
    result_s3_key: Mapped[str | None] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    # Counts and warnings only (sections, tables, slides, pages). Never document content.
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
