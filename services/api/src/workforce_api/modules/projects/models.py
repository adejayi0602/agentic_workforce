"""Projects (spec §5)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from workforce_api.db.base import Base, created_at, updated_at, uuid_pk

PROJECT_TYPES = ("software", "infrastructure", "data", "operations", "other")
PROJECT_STATUSES = ("active", "archived")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organisation_id", "key"),
        CheckConstraint("key ~ '^[A-Z][A-Z0-9]{1,9}$'", name="key_format"),
        CheckConstraint(
            "type IN ('software', 'infrastructure', 'data', 'operations', 'other')", name="type"
        ),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )
    # Short human key, e.g. "PAY". Prefixes requirement and task keys (REQ-PAY-014).
    key: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
