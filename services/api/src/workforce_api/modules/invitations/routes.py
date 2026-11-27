import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.dependencies import CurrentUser
from workforce_api.auth.permissions import Permission
from workforce_api.auth.tenancy import OrgContext, require
from workforce_api.config import Settings
from workforce_api.db import get_db_session
from workforce_api.mail import Mailer
from workforce_api.modules.identity.models import Role
from workforce_api.modules.invitations import service
from workforce_api.modules.invitations.models import OrganisationInvitation

logger = logging.getLogger(__name__)

manage = APIRouter(prefix="/organisations/current/invitations", tags=["invitations"])
respond = APIRouter(prefix="/invitations", tags=["invitations"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
Manage = Annotated[OrgContext, Depends(require(Permission.MEMBERS_MANAGE))]


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: Role = Role.MEMBER


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    status: str  # pending | accepted | revoked | expired
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None


class InvitationSent(InvitationOut):
    email_sent: bool


class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class InvitationPreview(BaseModel):
    organisation_name: str
    role: Role
    email: str
    invited_by: str | None
    status: str
    expires_at: datetime


class Accepted(BaseModel):
    organisation_id: uuid.UUID
    role: Role


def _out(invitation: OrganisationInvitation) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=Role(invitation.role),
        status=service.effective_status(invitation),
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        accepted_at=invitation.accepted_at,
    )


@manage.post("", response_model=InvitationSent, status_code=201)
async def invite(
    body: InvitationCreate, context: Manage, session: Session, request: Request
) -> InvitationSent:
    """Invite someone by email. They join when they accept with that email address."""
    settings: Settings = request.app.state.settings
    created = await service.create(
        session,
        context,
        email=str(body.email),
        role=body.role,
        web_base_url=settings.web_base_url,
        ttl_days=settings.invitation_ttl_days,
    )
    result = _out(created.invitation)
    # Commit before sending, so nobody receives a link to an invitation that rolled back.
    await session.commit()
    mailer: Mailer = request.app.state.mailer
    try:
        await mailer.send(created.message)
        sent = True
    except Exception:
        logger.exception("Could not send invitation %s", created.invitation.id)
        sent = False
    return InvitationSent(**result.model_dump(), email_sent=sent)


@manage.get("", response_model=list[InvitationOut])
async def list_invitations(context: Manage, session: Session) -> list[InvitationOut]:
    return [_out(i) for i in await service.list_for_organisation(session, context)]


@manage.delete("/{invitation_id}", status_code=204)
async def revoke(invitation_id: uuid.UUID, context: Manage, session: Session) -> Response:
    await service.revoke(session, context, invitation_id)
    return Response(status_code=204)


@respond.post("/preview", response_model=InvitationPreview)
async def preview(body: TokenIn, user: CurrentUser, session: Session) -> InvitationPreview:
    """What an invitation is for, before accepting it. The token is sent in the body, never
    in the URL, so it stays out of logs."""
    found = await service.preview(session, user, body.token)
    return InvitationPreview(
        organisation_name=found.organisation_name,
        role=Role(found.invitation.role),
        email=found.invitation.email,
        invited_by=found.invited_by,
        status=service.effective_status(found.invitation),
        expires_at=found.invitation.expires_at,
    )


@respond.post("/accept", response_model=Accepted)
async def accept(body: TokenIn, user: CurrentUser, session: Session) -> Accepted:
    """Join the organisation. Requires being signed in with the invited email address."""
    invitation = await service.accept(session, user, body.token)
    return Accepted(organisation_id=invitation.organisation_id, role=Role(invitation.role))
