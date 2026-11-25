import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.permissions import Permission, is_allowed
from workforce_api.auth.tenancy import OrgContext, require
from workforce_api.common.pagination import Page, PageParams, encode_cursor, page_params
from workforce_api.db import Database, get_db_session
from workforce_api.errors import ApiError
from workforce_api.modules.audit import service as audit
from workforce_api.modules.audit.routes import AuditEventOut
from workforce_api.modules.idempotency import service as idempotency
from workforce_api.modules.projects import service
from workforce_api.modules.projects.models import Project
from workforce_contracts import ErrorCode

router = APIRouter(prefix="/projects", tags=["projects"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
ProjectType = Literal["software", "infrastructure", "data", "operations", "other"]
ProjectStatus = Literal["active", "archived"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        pattern=r"^[A-Z][A-Z0-9]{1,9}$",
        description="Short uppercase key, e.g. PAY. Prefixes requirement and task keys.",
        examples=["PAY"],
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    type: ProjectType
    owner_id: uuid.UUID | None = Field(default=None, description="Defaults to the caller")


class ProjectUpdate(BaseModel):
    """Only the fields sent are changed. `key` and `type` are fixed at creation."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    owner_id: uuid.UUID | None = None
    status: ProjectStatus | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: str | None
    type: str
    status: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _out(project: Project) -> ProjectOut:
    return ProjectOut.model_validate(project, from_attributes=True)


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    context: Annotated[OrgContext, Depends(require(Permission.PROJECT_CREATE))],
    session: Session,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias=idempotency.IDEMPOTENCY_HEADER,
            description="Optional. Retrying with the same key returns the original result.",
        ),
    ] = None,
) -> ProjectOut | JSONResponse:
    reservation = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            organisation_id=context.organisation_id,
            user_id=context.user.id,
            key=idempotency_key,
            operation="POST /api/v1/projects",
            body=body,
        )
        if isinstance(outcome, idempotency.StoredResponse):
            return JSONResponse(
                status_code=outcome.status_code,
                content=outcome.body,
                headers={idempotency.REPLAYED_HEADER: "true"},
            )
        reservation = outcome

    project = await service.create_project(
        session,
        context,
        key=body.key,
        name=body.name,
        description=body.description,
        project_type=body.type,
        owner_id=body.owner_id,
    )
    result = _out(project)
    if reservation:
        await idempotency.complete(session, reservation, status_code=201, body=result)
    return result


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    context: Annotated[OrgContext, Depends(require(Permission.PROJECT_READ))],
    session: Session,
    page: Annotated[PageParams, Depends(page_params)],
    status: Annotated[ProjectStatus | None, Query()] = None,
) -> Page[ProjectOut]:
    rows = await service.list_projects(session, context, page=page, status=status)
    items, more = rows[: page.limit], len(rows) > page.limit
    return Page[ProjectOut](
        items=[_out(p) for p in items],
        next_cursor=encode_cursor(items[-1].created_at, items[-1].id) if more else None,
    )


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.PROJECT_READ))],
    session: Session,
) -> ProjectOut:
    return _out(await service.get_project(session, context, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    context: Annotated[OrgContext, Depends(require(Permission.PROJECT_UPDATE))],
    session: Session,
    request: Request,
) -> ProjectOut:
    """Update name, description or owner. Changing status also needs project.archive."""
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "status", "owner_id"):
        if field in changes and changes[field] is None:
            raise ApiError(
                ErrorCode.VALIDATION_FAILED,
                f"{field} cannot be null.",
                status_code=422,
                details={"field": field},
            )
    project = await service.get_project(session, context, project_id)
    changes_status = "status" in changes and changes["status"] != project.status
    if changes_status and not is_allowed(context.role, Permission.PROJECT_ARCHIVE):
        database: Database = request.app.state.database
        await audit.record_denial(
            database,
            organisation_id=context.organisation_id,
            user_id=context.user.id,
            action=Permission.PROJECT_ARCHIVE.value,
            resource_type="project",
            details={"role": context.role.value, "project_id": str(project_id)},
        )
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Your role does not allow this action.",
            status_code=403,
            details={
                "permission": Permission.PROJECT_ARCHIVE.value,
                "role": context.role.value,
            },
        )
    return _out(await service.update_project(session, context, project, changes))


@router.get("/{project_id}/audit-events", response_model=Page[AuditEventOut])
async def list_project_audit_events(
    project_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.AUDIT_READ))],
    session: Session,
    page: Annotated[PageParams, Depends(page_params)],
) -> Page[AuditEventOut]:
    """The project's audit trail (spec §6), newest first."""
    await service.get_project(session, context, project_id)
    rows = await audit.list_events(
        session, organisation_id=context.organisation_id, page=page, project_id=project_id
    )
    items, more = rows[: page.limit], len(rows) > page.limit
    return Page[AuditEventOut](
        items=[AuditEventOut.model_validate(e, from_attributes=True) for e in items],
        next_cursor=encode_cursor(items[-1].created_at, items[-1].id) if more else None,
    )
