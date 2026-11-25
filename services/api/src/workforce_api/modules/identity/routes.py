import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.dependencies import CurrentUser
from workforce_api.auth.permissions import Permission, permissions_for
from workforce_api.auth.tenancy import OrgContext, require
from workforce_api.config import Settings
from workforce_api.db import get_db_session
from workforce_api.errors import ApiError
from workforce_api.modules.identity import organisations as service
from workforce_api.modules.identity.models import Organisation, Role
from workforce_contracts import ErrorCode

router = APIRouter(tags=["identity"])

Session = Annotated[AsyncSession, Depends(get_db_session)]


class MembershipOut(BaseModel):
    organisation_id: uuid.UUID
    name: str
    slug: str
    role: Role


class Me(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None
    memberships: list[MembershipOut]


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", examples=["acme"])


class OrganisationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    your_role: Role
    your_permissions: list[str]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: Role


class MemberUpdate(BaseModel):
    role: Role


@router.get("/me", response_model=Me)
async def get_me(user: CurrentUser, session: Session) -> Me:
    """The signed-in user and their organisations. The first call creates the user record."""
    memberships = await service.list_my_memberships(session, user)
    return Me(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        memberships=[
            MembershipOut(
                organisation_id=m.organisation.id,
                name=m.organisation.name,
                slug=m.organisation.slug,
                role=m.role,
            )
            for m in memberships
        ],
    )


@router.post("/organisations", response_model=OrganisationOut, status_code=201)
async def create_organisation(
    body: OrganisationCreate, user: CurrentUser, session: Session, request: Request
) -> OrganisationOut:
    """Create an organisation. The caller becomes its first org admin."""
    settings: Settings = request.app.state.settings
    if settings.organisation_creation != "open":
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Creating organisations is disabled on this platform.",
            status_code=403,
        )
    org = await service.create_organisation(session, creator=user, name=body.name, slug=body.slug)
    return _organisation_out(org, Role.ORG_ADMIN)


@router.get("/organisations/current", response_model=OrganisationOut)
async def get_current_organisation(
    context: Annotated[OrgContext, Depends(require(Permission.ORG_READ))], session: Session
) -> OrganisationOut:
    """The organisation named in X-Organisation-ID, with your role and permissions in it."""
    org = await service.get_organisation(session, context)
    return _organisation_out(org, context.role)


@router.get("/organisations/current/members", response_model=list[MemberOut])
async def list_members(
    context: Annotated[OrgContext, Depends(require(Permission.MEMBERS_READ))], session: Session
) -> list[MemberOut]:
    members = await service.list_members(session, context)
    return [_member_out(m) for m in members]


@router.patch("/organisations/current/members/{user_id}", response_model=MemberOut)
async def change_member_role(
    user_id: uuid.UUID,
    body: MemberUpdate,
    context: Annotated[OrgContext, Depends(require(Permission.MEMBERS_MANAGE))],
    session: Session,
) -> MemberOut:
    """Change a member's role. The last org admin cannot be demoted."""
    member = await service.change_member_role(session, context, user_id=user_id, role=body.role)
    return _member_out(member)


@router.delete("/organisations/current/members/{user_id}", status_code=204)
async def remove_member(
    user_id: uuid.UUID,
    context: Annotated[OrgContext, Depends(require(Permission.MEMBERS_MANAGE))],
    session: Session,
) -> Response:
    """Remove a member. The last org admin cannot be removed."""
    await service.remove_member(session, context, user_id=user_id)
    return Response(status_code=204)


def _organisation_out(org: Organisation, role: Role) -> OrganisationOut:
    return OrganisationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        status=org.status,
        your_role=role,
        your_permissions=sorted(p.value for p in permissions_for(role)),
    )


def _member_out(member: service.MemberView) -> MemberOut:
    return MemberOut(
        user_id=member.user.id,
        email=member.user.email,
        display_name=member.user.display_name,
        role=member.role,
    )
