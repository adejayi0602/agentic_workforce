"""Dev-only token endpoint. Mounted only when auth_mode is 'dev' (local and test only)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field

from workforce_api.auth.dev_issuer import DevTokenIssuer

router = APIRouter(prefix="/dev-auth", tags=["dev-only"])

TOKEN_TTL_SECONDS = 3600


class DevTokenRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200, examples=["alice"])
    email: EmailStr | None = None
    name: str | None = Field(default=None, max_length=200)


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - token type, not a secret
    expires_in: int


def get_dev_issuer(request: Request) -> DevTokenIssuer:
    issuer: DevTokenIssuer = request.app.state.dev_issuer
    return issuer


class DevMail(BaseModel):
    to: str
    subject: str
    body: str
    sent_at: datetime


@router.get("/mail", response_model=list[DevMail])
async def dev_mailbox(request: Request, to: str | None = None) -> list[DevMail]:
    """Emails the API has 'sent' (local and test only), newest first. Lets developers and
    browser tests follow invitation links without a real mail server."""
    mailer = request.app.state.mailer
    sent = getattr(mailer, "sent", [])
    wanted = to.strip().lower() if to else None
    return [
        DevMail(to=m.to, subject=m.subject, body=m.body, sent_at=m.sent_at)
        for m in reversed(sent)
        if wanted is None or m.to == wanted
    ]


@router.post("/token", response_model=DevTokenResponse)
async def issue_dev_token(
    body: DevTokenRequest,
    issuer: Annotated[DevTokenIssuer, Depends(get_dev_issuer)],
) -> DevTokenResponse:
    """Sign in as anyone, for local development. Never available in deployed environments."""
    token = issuer.issue(
        subject=body.subject,
        email=str(body.email) if body.email else None,
        name=body.name,
        ttl_seconds=TOKEN_TTL_SECONDS,
    )
    return DevTokenResponse(access_token=token, expires_in=TOKEN_TTL_SECONDS)
