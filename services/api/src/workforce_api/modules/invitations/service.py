"""Organisation invitations (#11).

A random token goes in the link; only its SHA-256 is stored. The link puts the token in the URL
fragment (`#token=...`), which browsers never send to servers, so it stays out of logs and
referrer headers. Accepting requires being signed in with the invited email address.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.tenancy import OrgContext
from workforce_api.db import set_tenant_context
from workforce_api.db.invitation_context import set_invitation_context
from workforce_api.errors import ApiError
from workforce_api.mail import Message
from workforce_api.modules.audit import service as audit
from workforce_api.modules.identity.models import (
    Organisation,
    OrganisationMember,
    Role,
    User,
)
from workforce_api.modules.invitations.models import OrganisationInvitation
from workforce_contracts import ErrorCode

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def effective_status(invitation: OrganisationInvitation) -> str:
    """'expired' is computed, never stored: a pending invitation past its expiry."""
    if invitation.status == "pending" and invitation.expires_at <= datetime.now(UTC):
        return "expired"
    return invitation.status


@dataclass(frozen=True)
class NewInvitation:
    invitation: OrganisationInvitation
    message: Message


@dataclass(frozen=True)
class Preview:
    invitation: OrganisationInvitation
    organisation_name: str
    invited_by: str | None


async def create(
    session: AsyncSession,
    context: OrgContext,
    *,
    email: str,
    role: Role,
    web_base_url: str,
    ttl_days: int,
) -> NewInvitation:
    email = email.strip().lower()
    already_member = await session.scalar(
        select(User.id)
        .join(OrganisationMember, OrganisationMember.user_id == User.id)
        .where(
            OrganisationMember.organisation_id == context.organisation_id,
            func.lower(User.email) == email,
        )
    )
    if already_member is not None:
        raise ApiError(
            ErrorCode.CONFLICT,
            "That person is already a member of this organisation.",
            status_code=409,
            details={"field": "email"},
        )

    token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = OrganisationInvitation(
        id=uuid.uuid4(),
        organisation_id=context.organisation_id,
        email=email,
        role=role.value,
        token_hash=hash_token(token),
        invited_by=context.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
    )
    session.add(invitation)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "There's already an open invitation for that email address. "
            "Revoke it to send a new one.",
            status_code=409,
            details={"field": "email"},
        ) from exc
    await session.refresh(invitation)

    organisation = await session.get(Organisation, context.organisation_id)
    org_name = organisation.name if organisation else "an organisation"
    inviter = context.user.display_name or context.user.email or "A colleague"
    link = f"{web_base_url.rstrip('/')}/invitations/accept#token={token}"
    message = Message(
        to=email,
        subject=f"You're invited to {org_name} on Agentic Workforce",
        body=(
            f"{inviter} has invited you to join {org_name} as {role.value.replace('_', ' ')}.\n\n"
            f"Accept the invitation: {link}\n\n"
            f"Sign in with this email address ({email}). The link expires in {ttl_days} days "
            "and works once."
        ),
    )
    await _audit(session, context.organisation_id, context.user.id, invitation, "invitation.create")
    return NewInvitation(invitation=invitation, message=message)


async def list_for_organisation(
    session: AsyncSession, context: OrgContext
) -> list[OrganisationInvitation]:
    return list(
        await session.scalars(
            select(OrganisationInvitation)
            .where(OrganisationInvitation.organisation_id == context.organisation_id)
            .order_by(OrganisationInvitation.created_at.desc())
            .limit(200)
        )
    )


async def revoke(session: AsyncSession, context: OrgContext, invitation_id: uuid.UUID) -> None:
    invitation = await session.scalar(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.id == invitation_id,
            OrganisationInvitation.organisation_id == context.organisation_id,
        )
        .with_for_update()
    )
    if invitation is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Invitation not found.", status_code=404)
    if invitation.status != "pending":
        raise ApiError(
            ErrorCode.INVALID_STATE,
            f"This invitation has already been {invitation.status}.",
            status_code=409,
        )
    invitation.status = "revoked"
    await session.flush()
    await _audit(session, context.organisation_id, context.user.id, invitation, "invitation.revoke")


async def preview(session: AsyncSession, user: User, token: str) -> Preview:
    invitation = await _by_token(session, token)
    # The token proves the right to see this one organisation's name and the inviter's name.
    await set_tenant_context(session, organisation_id=invitation.organisation_id, user_id=user.id)
    organisation = await session.get(Organisation, invitation.organisation_id)
    inviter = await session.get(User, invitation.invited_by)
    return Preview(
        invitation=invitation,
        organisation_name=organisation.name if organisation else "",
        invited_by=(inviter.display_name or inviter.email) if inviter else None,
    )


async def accept(session: AsyncSession, user: User, token: str) -> OrganisationInvitation:
    invitation = await _by_token(session, token, lock_for=user.id)
    status = effective_status(invitation)
    if status != "pending":
        raise ApiError(
            ErrorCode.INVALID_STATE,
            {
                "accepted": "This invitation has already been used.",
                "revoked": "This invitation has been withdrawn.",
                "expired": "This invitation has expired. Ask for a new one.",
            }.get(status, "This invitation can't be used."),
            status_code=409,
            details={"status": status},
        )
    if (user.email or "").strip().lower() != invitation.email:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            f"This invitation was sent to {_mask(invitation.email)}. Sign in with that email "
            "address to accept it.",
            status_code=403,
        )

    await set_tenant_context(session, organisation_id=invitation.organisation_id, user_id=user.id)
    existing = await session.scalar(
        select(OrganisationMember).where(
            OrganisationMember.organisation_id == invitation.organisation_id,
            OrganisationMember.user_id == user.id,
        )
    )
    if existing is None:
        session.add(
            OrganisationMember(
                organisation_id=invitation.organisation_id, user_id=user.id, role=invitation.role
            )
        )
    invitation.status = "accepted"
    invitation.accepted_by = user.id
    invitation.accepted_at = datetime.now(UTC)
    await session.flush()
    await _audit(session, invitation.organisation_id, user.id, invitation, "invitation.accept")
    await audit.emit(
        session,
        organisation_id=invitation.organisation_id,
        aggregate_type="member",
        aggregate_id=user.id,
        event_type="member.joined",
        payload={"user_id": str(user.id), "role": invitation.role},
    )
    return invitation


async def _by_token(
    session: AsyncSession, token: str, *, lock_for: uuid.UUID | None = None
) -> OrganisationInvitation:
    digest = hash_token(token.strip())
    await set_invitation_context(session, token_hash=digest)
    query = select(OrganisationInvitation).where(OrganisationInvitation.token_hash == digest)
    invitation = await session.scalar(query)
    if invitation is None:
        raise ApiError(ErrorCode.NOT_FOUND, "This invitation link isn't valid.", status_code=404)
    if lock_for is not None:
        # The token policy is read-only, and a row lock needs UPDATE rights, so enter the
        # invitation's organisation (as user `lock_for`) and re-read under the lock.
        await set_tenant_context(
            session, organisation_id=invitation.organisation_id, user_id=lock_for
        )
        locked = await session.scalar(
            query.with_for_update().execution_options(populate_existing=True)
        )
        if locked is None:
            raise ApiError(
                ErrorCode.NOT_FOUND, "This invitation link isn't valid.", status_code=404
            )
        invitation = locked
    return invitation


def _mask(email: str) -> str:
    """j***@example.com: enough to recognise, not enough to harvest."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


async def _audit(
    session: AsyncSession,
    organisation_id: uuid.UUID,
    actor_id: uuid.UUID,
    invitation: OrganisationInvitation,
    action: str,
) -> None:
    await audit.record(
        session,
        organisation_id=organisation_id,
        actor_type="user",
        actor_id=str(actor_id),
        action=action,
        resource_type="invitation",
        resource_id=str(invitation.id),
        details={"email": invitation.email, "role": invitation.role},
    )
