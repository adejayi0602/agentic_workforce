import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.permissions import Permission
from workforce_api.auth.tenancy import OrgContext, require
from workforce_api.common.pagination import Page, PageParams, encode_cursor, page_params
from workforce_api.db import get_db_session
from workforce_api.modules.audit import service

router = APIRouter(tags=["audit"])


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    project_id: uuid.UUID | None
    actor_type: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None
    decision: str
    correlation_id: uuid.UUID
    details: dict[str, Any]


@router.get("/audit-events", response_model=Page[AuditEventOut])
async def list_audit_events(
    context: Annotated[OrgContext, Depends(require(Permission.AUDIT_READ))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[PageParams, Depends(page_params)],
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AuditEventOut]:
    """The organisation's audit trail, newest first. Includes denied attempts."""
    rows = await service.list_events(
        session, organisation_id=context.organisation_id, page=page, project_id=project_id
    )
    items, more = rows[: page.limit], len(rows) > page.limit
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(e, from_attributes=True) for e in items],
        next_cursor=encode_cursor(items[-1].created_at, items[-1].id) if more else None,
    )
