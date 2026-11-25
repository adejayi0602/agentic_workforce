"""Identity: turn a validated Principal into a platform User."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.principal import Principal
from workforce_api.db.tenant import set_identity_context, set_tenant_context
from workforce_api.errors import ApiError
from workforce_api.modules.identity.models import User
from workforce_contracts import ErrorCode


async def resolve_user(session: AsyncSession, principal: Principal) -> User:
    """Find or create the user for this principal, keep profile fields current, and set
    `app.user_id` so the rest of the request's queries run as this user.

    Disabled users are refused. Concurrent first sign-ins are safe: the insert ignores a
    conflict on (issuer, subject) and both requests read back the same row.
    """
    await set_identity_context(session, issuer=principal.issuer, subject=principal.subject)
    by_identity = select(User).where(
        User.identity_issuer == principal.issuer,
        User.identity_subject == principal.subject,
    )
    user = await session.scalar(by_identity)

    if user is None:
        new_id = uuid.uuid4()
        await set_tenant_context(session, organisation_id=None, user_id=new_id)
        await session.execute(
            insert(User)
            .values(
                id=new_id,
                identity_issuer=principal.issuer,
                identity_subject=principal.subject,
                email=principal.email,
                display_name=principal.name,
            )
            .on_conflict_do_nothing(index_elements=["identity_issuer", "identity_subject"])
        )
        user = await session.scalar(by_identity.execution_options(populate_existing=True))
        if user is None:  # pragma: no cover - only if RLS policies are misconfigured
            raise ApiError(ErrorCode.INTERNAL_ERROR, "Could not provision the user.", 500)

    await set_tenant_context(session, organisation_id=None, user_id=user.id)

    if user.status != "active":
        raise ApiError(ErrorCode.FORBIDDEN, "This account is disabled.", status_code=403)

    # The identity provider is the source of truth for profile fields it supplies.
    if principal.email and principal.email != user.email:
        user.email = principal.email
    if principal.name and principal.name != user.display_name:
        user.display_name = principal.name
    await session.flush()
    return user
