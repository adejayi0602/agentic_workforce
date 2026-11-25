"""Tenant and identity context for row-level security (ADR-0003).

RLS policies read transaction-local settings:

- `app.organisation_id`: the organisation the request acts in. Tenant-owned rows are
  visible only when their organisation_id matches it.
- `app.user_id`: the signed-in user. Lets a user see their own row and memberships (and
  the organisations they belong to) before an organisation is chosen.
- `app.identity_issuer` / `app.identity_subject`: the validated token's issuer and subject.
  Let the API find the caller's own user row before it knows the user's id (first step of
  every request). Set only from a token that has passed validation.

All are set with `set_config(..., is_local => true)`, so they end with the transaction and
can never leak to the next request on a pooled connection. When none are set, every
tenant-owned query returns no rows: the system fails closed.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SET_TENANT = text(
    "SELECT set_config('app.organisation_id', :organisation_id, true), "
    "set_config('app.user_id', :user_id, true)"
)
_SET_IDENTITY = text(
    "SELECT set_config('app.identity_issuer', :issuer, true), "
    "set_config('app.identity_subject', :subject, true)"
)


async def set_tenant_context(
    session: AsyncSession,
    *,
    organisation_id: UUID | None,
    user_id: UUID | None,
) -> None:
    """Set the tenant context for the current transaction. Call after the transaction begins."""
    await session.execute(
        _SET_TENANT,
        {
            "organisation_id": str(organisation_id) if organisation_id else "",
            "user_id": str(user_id) if user_id else "",
        },
    )


async def set_identity_context(session: AsyncSession, *, issuer: str, subject: str) -> None:
    """Expose the caller's own user row by (issuer, subject). Only for validated tokens."""
    await session.execute(_SET_IDENTITY, {"issuer": issuer, "subject": subject})
