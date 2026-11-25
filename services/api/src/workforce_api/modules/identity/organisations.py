"""Organisations and memberships."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.tenancy import OrgContext
from workforce_api.db import set_tenant_context
from workforce_api.errors import ApiError
from workforce_api.modules.audit import service as audit
from workforce_api.modules.identity.models import Organisation, OrganisationMember, Role, User
from workforce_contracts import ErrorCode


@dataclass(frozen=True)
class Membership:
    organisation: Organisation
    role: Role


@dataclass(frozen=True)
class MemberView:
    user: User
    role: Role


async def create_organisation(
    session: AsyncSession, *, creator: User, name: str, slug: str
) -> Organisation:
    """Create an organisation with the creator as its first org admin."""
    org_id = uuid.uuid4()
    # Policies only allow inserting the organisation the request is acting in.
    await set_tenant_context(session, organisation_id=org_id, user_id=creator.id)
    organisation = Organisation(id=org_id, name=name, slug=slug)
    session.add(organisation)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "That organisation slug is already taken.",
            status_code=409,
            details={"field": "slug"},
        ) from exc
    session.add(OrganisationMember(organisation_id=org_id, user_id=creator.id, role=Role.ORG_ADMIN))
    await session.flush()
    await audit.record(
        session,
        organisation_id=org_id,
        actor_type="user",
        actor_id=str(creator.id),
        action="organisation.create",
        resource_type="organisation",
        resource_id=str(org_id),
        details={"slug": slug},
    )
    await audit.emit(
        session,
        organisation_id=org_id,
        aggregate_type="organisation",
        aggregate_id=org_id,
        event_type="organisation.created",
        payload={"organisation_id": str(org_id), "created_by": str(creator.id)},
    )
    await session.refresh(organisation)
    return organisation


async def list_my_memberships(session: AsyncSession, user: User) -> list[Membership]:
    rows = await session.execute(
        select(Organisation, OrganisationMember.role)
        .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
        .where(OrganisationMember.user_id == user.id)
        .order_by(Organisation.name)
    )
    return [Membership(organisation=org, role=Role(role)) for org, role in rows]


async def get_organisation(session: AsyncSession, context: OrgContext) -> Organisation:
    organisation = await session.get(Organisation, context.organisation_id)
    if organisation is None:  # pragma: no cover - membership was just confirmed
        raise ApiError(ErrorCode.NOT_FOUND, "Organisation not found.", status_code=404)
    return organisation


async def list_members(session: AsyncSession, context: OrgContext) -> list[MemberView]:
    rows = await session.execute(
        select(User, OrganisationMember.role)
        .join(OrganisationMember, OrganisationMember.user_id == User.id)
        .where(OrganisationMember.organisation_id == context.organisation_id)
        .order_by(User.display_name, User.email)
    )
    return [MemberView(user=user, role=Role(role)) for user, role in rows]


async def change_member_role(
    session: AsyncSession, context: OrgContext, *, user_id: uuid.UUID, role: Role
) -> MemberView:
    member = await _locked_member(session, context, user_id)
    if member.role == Role.ORG_ADMIN and role != Role.ORG_ADMIN:
        await _ensure_another_admin(session, context, excluding=user_id)
    previous = Role(member.role)
    member.role = role
    await session.flush()
    await _audit_member_change(
        session,
        context,
        user_id,
        action="member.role_change",
        event_type="member.role_changed",
        facts={"from": previous.value, "to": role.value},
    )
    user = await session.get(User, user_id)
    assert user is not None  # noqa: S101 - visible as a member of the current organisation
    return MemberView(user=user, role=role)


async def remove_member(session: AsyncSession, context: OrgContext, *, user_id: uuid.UUID) -> None:
    member = await _locked_member(session, context, user_id)
    if member.role == Role.ORG_ADMIN:
        await _ensure_another_admin(session, context, excluding=user_id)
    role = member.role
    await session.delete(member)
    await session.flush()
    await _audit_member_change(
        session,
        context,
        user_id,
        action="member.remove",
        event_type="member.removed",
        facts={"role": role},
    )


async def _locked_member(
    session: AsyncSession, context: OrgContext, user_id: uuid.UUID
) -> OrganisationMember:
    # Lock every admin row too, so two admins can't demote each other at the same moment.
    await session.execute(
        select(OrganisationMember.user_id)
        .where(
            OrganisationMember.organisation_id == context.organisation_id,
            OrganisationMember.role == Role.ORG_ADMIN,
        )
        .with_for_update()
    )
    member = await session.scalar(
        select(OrganisationMember)
        .where(
            OrganisationMember.organisation_id == context.organisation_id,
            OrganisationMember.user_id == user_id,
        )
        .with_for_update()
    )
    if member is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Member not found.", status_code=404)
    return member


async def _ensure_another_admin(
    session: AsyncSession, context: OrgContext, *, excluding: uuid.UUID
) -> None:
    others = await session.scalar(
        select(func.count())
        .select_from(OrganisationMember)
        .where(
            OrganisationMember.organisation_id == context.organisation_id,
            OrganisationMember.role == Role.ORG_ADMIN,
            OrganisationMember.user_id != excluding,
        )
    )
    if not others:
        raise ApiError(
            ErrorCode.CONFLICT,
            "An organisation must keep at least one org admin.",
            status_code=409,
        )


async def _audit_member_change(
    session: AsyncSession,
    context: OrgContext,
    user_id: uuid.UUID,
    *,
    action: str,
    event_type: str,
    facts: dict[str, str],
) -> None:
    await audit.record(
        session,
        organisation_id=context.organisation_id,
        actor_type="user",
        actor_id=str(context.user.id),
        action=action,
        resource_type="member",
        resource_id=str(user_id),
        details=facts,
    )
    await audit.emit(
        session,
        organisation_id=context.organisation_id,
        aggregate_type="member",
        aggregate_id=user_id,
        event_type=event_type,
        payload={"user_id": str(user_id), **facts},
    )
