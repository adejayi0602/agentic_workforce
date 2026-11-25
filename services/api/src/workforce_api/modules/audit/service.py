"""Audit trail and transactional outbox (spec FR-022, §5.2).

`record` and `emit` write in the caller's transaction, so the audit event and domain event
commit or roll back together with the change they describe.

Denied actions are different: the request's transaction rolls back, which would erase an audit
row written inside it. `record_denial` therefore writes in its own short transaction.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.common.pagination import PageParams
from workforce_api.correlation import get_correlation_id
from workforce_api.db import Database, set_tenant_context
from workforce_api.modules.audit.models import AuditEvent, OutboxEvent

ActorType = Literal["user", "agent", "system"]


async def record(
    session: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    actor_type: ActorType,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    project_id: uuid.UUID | None = None,
    decision: Literal["allowed", "denied"] = "allowed",
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Record a consequential action in the current transaction.

    `details` holds identifiers and small facts only: never secrets or document content.
    """
    event = AuditEvent(
        organisation_id=organisation_id,
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        decision=decision,
        correlation_id=get_correlation_id(),
        details=details or {},
    )
    session.add(event)
    await session.flush()
    return event


async def emit(
    session: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Add a domain event to the outbox, in the current transaction.

    A plain INSERT with no RETURNING: the API role may write the outbox but never read it.
    """
    await session.execute(
        insert(OutboxEvent).values(
            organisation_id=organisation_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
            correlation_id=get_correlation_id(),
        )
    )


async def record_denial(
    database: Database,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record a refused action in its own transaction, so the request's rollback keeps it."""
    async with database.sessions() as session, session.begin():
        await set_tenant_context(session, organisation_id=organisation_id, user_id=user_id)
        await record(
            session,
            organisation_id=organisation_id,
            actor_type="user",
            actor_id=str(user_id),
            action=action,
            resource_type=resource_type,
            decision="denied",
            details=details,
        )


async def list_events(
    session: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    page: PageParams,
    project_id: uuid.UUID | None = None,
) -> list[AuditEvent]:
    """Newest first. Returns up to limit + 1 rows so the caller can tell if there is more."""
    query = select(AuditEvent).where(AuditEvent.organisation_id == organisation_id)
    if project_id is not None:
        query = query.where(AuditEvent.project_id == project_id)
    if page.after is not None:
        created, last_id = page.after
        query = query.where(_before(created, last_id))
    query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(page.limit + 1)
    return list(await session.scalars(query))


def _before(created: datetime, last_id: uuid.UUID) -> Any:
    return or_(
        AuditEvent.created_at < created,
        and_(AuditEvent.created_at == created, AuditEvent.id < last_id),
    )
