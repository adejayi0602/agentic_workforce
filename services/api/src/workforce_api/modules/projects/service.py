"""Projects (FR-001)."""

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.tenancy import OrgContext
from workforce_api.common.pagination import PageParams
from workforce_api.errors import ApiError
from workforce_api.modules.audit import service as audit
from workforce_api.modules.identity.models import OrganisationMember
from workforce_api.modules.projects.models import Project
from workforce_contracts import ErrorCode


async def create_project(
    session: AsyncSession,
    context: OrgContext,
    *,
    key: str,
    name: str,
    description: str | None,
    project_type: str,
    owner_id: uuid.UUID | None,
) -> Project:
    owner = owner_id or context.user.id
    await _ensure_member(session, context, owner)
    project = Project(
        organisation_id=context.organisation_id,
        key=key,
        name=name,
        description=description,
        type=project_type,
        owner_id=owner,
    )
    session.add(project)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"A project with key {key} already exists in this organisation.",
            status_code=409,
            details={"field": "key"},
        ) from exc
    await session.refresh(project)
    await _record(session, context, project, "project.create", "project.created", {"key": key})
    return project


async def get_project(session: AsyncSession, context: OrgContext, project_id: uuid.UUID) -> Project:
    # RLS already limits rows to the current organisation; the filter documents intent.
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.organisation_id == context.organisation_id
        )
    )
    if project is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Project not found.", status_code=404)
    return project


async def list_projects(
    session: AsyncSession, context: OrgContext, *, page: PageParams, status: str | None
) -> list[Project]:
    """Newest first. Returns up to limit + 1 rows so the caller can tell if there is more."""
    query = select(Project).where(Project.organisation_id == context.organisation_id)
    if status:
        query = query.where(Project.status == status)
    if page.after is not None:
        created, last_id = page.after
        query = query.where(
            or_(
                Project.created_at < created,
                and_(Project.created_at == created, Project.id < last_id),
            )
        )
    query = query.order_by(Project.created_at.desc(), Project.id.desc()).limit(page.limit + 1)
    return list(await session.scalars(query))


async def update_project(
    session: AsyncSession,
    context: OrgContext,
    project: Project,
    changes: dict[str, Any],
) -> Project:
    """Apply field changes. `key` is immutable: it prefixes requirement and task keys."""
    if "owner_id" in changes:
        await _ensure_member(session, context, changes["owner_id"])
    changed = {f: v for f, v in changes.items() if getattr(project, f) != v}
    if not changed:
        return project
    previous_status = project.status
    for field, value in changed.items():
        setattr(project, field, value)
    await session.flush()
    await session.refresh(project)

    if "status" in changed:
        action = "project.archive" if project.status == "archived" else "project.unarchive"
        await _record(
            session,
            context,
            project,
            action,
            f"{action.split('.')[1]}d",
            {"from": previous_status, "to": project.status},
        )
    other = sorted(set(changed) - {"status"})
    if other:
        await _record(
            session, context, project, "project.update", "project.updated", {"fields": other}
        )
    return project


async def _ensure_member(session: AsyncSession, context: OrgContext, user_id: uuid.UUID) -> None:
    exists = await session.scalar(
        select(OrganisationMember.user_id).where(
            OrganisationMember.organisation_id == context.organisation_id,
            OrganisationMember.user_id == user_id,
        )
    )
    if exists is None:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "The project owner must be a member of the organisation.",
            status_code=422,
            details={"field": "owner_id"},
        )


async def _record(
    session: AsyncSession,
    context: OrgContext,
    project: Project,
    action: str,
    event_suffix: str,
    details: dict[str, Any],
) -> None:
    event_type = event_suffix if "." in event_suffix else f"project.{event_suffix}"
    await audit.record(
        session,
        organisation_id=context.organisation_id,
        project_id=project.id,
        actor_type="user",
        actor_id=str(context.user.id),
        action=action,
        resource_type="project",
        resource_id=str(project.id),
        details=details,
    )
    await audit.emit(
        session,
        organisation_id=context.organisation_id,
        aggregate_type="project",
        aggregate_id=project.id,
        event_type=event_type,
        payload={"project_id": str(project.id), "key": project.key, **details},
    )
