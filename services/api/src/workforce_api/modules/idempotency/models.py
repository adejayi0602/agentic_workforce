"""Idempotency keys for mutation endpoints (spec §6)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from workforce_api.db.base import Base, created_at


class IdempotencyKey(Base):
    """One row per (organisation, user, key). Reserved before the work, completed with it."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint("status IN ('in_progress', 'completed')", name="status"),
        CheckConstraint("length(key) BETWEEN 8 AND 200", name="key_length"),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    # "POST /api/v1/projects": a key is bound to one operation.
    operation: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
