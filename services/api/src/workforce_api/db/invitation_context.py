"""Reveal one invitation to whoever holds its token (see migration 0006)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_invitation_context(session: AsyncSession, *, token_hash: str) -> None:
    await session.execute(
        text("SELECT set_config('app.invitation_token_hash', :h, true)"), {"h": token_hash}
    )
