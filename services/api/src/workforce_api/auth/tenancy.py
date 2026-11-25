"""Organisation context: which organisation a request acts in, and as which role (ADR-0003).

Organisation-scoped requests name the organisation in the `X-Organisation-ID` header. The
caller must be a member. Non-members get 404, not 403, so organisation ids can't be probed.
Once membership is confirmed, `app.organisation_id` is set and row-level security scopes
every query in the request to that organisation.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.dependencies import CurrentUser
from workforce_api.auth.permissions import Permission, is_allowed, permissions_for
from workforce_api.db import Database, get_db_session, set_tenant_context
from workforce_api.errors import ApiError
from workforce_api.modules.audit.service import record_denial
from workforce_api.modules.identity.models import OrganisationMember, Role, User
from workforce_contracts import ErrorCode

ORGANISATION_HEADER = "X-Organisation-ID"


@dataclass(frozen=True)
class OrgContext:
    organisation_id: uuid.UUID
    user: User
    role: Role

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.role)


async def get_org_context(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    organisation_id: Annotated[
        str | None,
        Header(
            alias=ORGANISATION_HEADER,
            description="The organisation this request acts in. The caller must be a member.",
        ),
    ] = None,
) -> OrgContext:
    if not organisation_id:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"The {ORGANISATION_HEADER} header is required for this endpoint.",
            status_code=400,
            details={"header": ORGANISATION_HEADER},
        )
    try:
        org_id = uuid.UUID(organisation_id)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"The {ORGANISATION_HEADER} header must be a UUID.",
            status_code=400,
            details={"header": ORGANISATION_HEADER},
        ) from exc

    # Visible through RLS because it is the user's own membership.
    role = await session.scalar(
        select(OrganisationMember.role).where(
            OrganisationMember.organisation_id == org_id,
            OrganisationMember.user_id == user.id,
        )
    )
    if role is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Organisation not found.", status_code=404)

    await set_tenant_context(session, organisation_id=org_id, user_id=user.id)
    return OrgContext(organisation_id=org_id, user=user, role=Role(role))


def require(permission: Permission) -> Callable[..., Awaitable[OrgContext]]:
    """Dependency factory: the organisation context, if the caller's role has `permission`."""

    async def dependency(
        context: Annotated[OrgContext, Depends(get_org_context)],
        request: Request,
    ) -> OrgContext:
        if not is_allowed(context.role, permission):
            database: Database = request.app.state.database
            await record_denial(
                database,
                organisation_id=context.organisation_id,
                user_id=context.user.id,
                action=permission.value,
                resource_type="permission",
                details={
                    "role": context.role.value,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "Your role does not allow this action.",
                status_code=403,
                details={"permission": permission.value, "role": context.role.value},
            )
        return context

    dependency.required_permission = permission  # type: ignore[attr-defined]
    return dependency
