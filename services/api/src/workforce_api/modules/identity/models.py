"""Organisations, users and memberships (spec §5)."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from workforce_api.db.base import Base, created_at, updated_at, uuid_pk


class Role(StrEnum):
    """Organisation roles (spec §6 access column). Permissions per role live in the policy table."""

    ORG_ADMIN = "org_admin"
    PROJECT_OWNER = "project_owner"
    PROJECT_MANAGER = "project_manager"
    MEMBER = "member"
    AUDITOR = "auditor"


class Organisation(Base):
    """Tenant root."""

    __tablename__ = "organisations"
    __table_args__ = (CheckConstraint("status IN ('active', 'suspended')", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class User(Base):
    """A human identity. Not tenant-owned: one user can belong to several organisations."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("identity_issuer", "identity_subject"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # The OIDC `sub` claim, qualified by issuer so two identity providers can't collide.
    identity_issuer: Mapped[str] = mapped_column(Text, nullable=False)
    identity_subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class OrganisationMember(Base):
    __tablename__ = "organisation_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('org_admin', 'project_owner', 'project_manager', 'member', 'auditor')",
            name="role",
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()
