"""Imports every model so `Base.metadata` is complete (for Alembic and tests)."""

from workforce_api.db.base import Base
from workforce_api.modules.audit.models import AuditEvent, OutboxEvent
from workforce_api.modules.documents.models import (
    DocumentProcessingRun,
    DocumentVersion,
    ProjectDocument,
)
from workforce_api.modules.idempotency.models import IdempotencyKey
from workforce_api.modules.identity.models import Organisation, OrganisationMember, Role, User
from workforce_api.modules.projects.models import Project

__all__ = [
    "AuditEvent",
    "Base",
    "DocumentProcessingRun",
    "DocumentVersion",
    "IdempotencyKey",
    "Organisation",
    "OrganisationMember",
    "OutboxEvent",
    "Project",
    "ProjectDocument",
    "Role",
    "User",
]
