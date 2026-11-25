"""Tenant context for row-level security (ADR-0003).

RLS policies read two transaction-local settings:

- `app.organisation_id`: the organisation the request acts in. Tenant-owned rows are
  visible only when their organisation_id matches it.
- `app.user_id`: the signed-in user. Lets a user see their own memberships (and the
  organisations they belong to) before an organisation is chosen.

Both are set with `set_config(..., is_local => true)`, so they end with the transaction and
can never leak to the next request on a pooled connection. When neither is set, every
tenant-owned query returns no rows: the system fails closed.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SET = text(
    "SELECT set_config('app.organisation_id', :organisation_id, true), "
    "set_config('app.user_id', :user_id, true)"
)


async def set_tenant_context(
    session: AsyncSession,
    *,
    organisation_id: UUID | None,
    user_id: UUID | None,
) -> None:
    """Set the tenant context for the current transaction. Call after the transaction begins."""
    await session.execute(
        _SET,
        {
            "organisation_id": str(organisation_id) if organisation_id else "",
            "user_id": str(user_id) if user_id else "",
        },
    )
