"""FastAPI dependencies: bearer token → Principal → platform User."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from workforce_api.auth.principal import AuthenticationError, FailureReason, Principal
from workforce_api.auth.tokens import TokenValidator
from workforce_api.db import get_db_session
from workforce_api.errors import ApiError
from workforce_api.modules.identity.models import User
from workforce_api.modules.identity.service import resolve_user
from workforce_contracts import ErrorCode

_bearer = HTTPBearer(auto_error=False, description="OIDC access or ID token")


def unauthenticated(reason: FailureReason) -> ApiError:
    return ApiError(
        ErrorCode.UNAUTHENTICATED,
        "Authentication is required. Provide a valid bearer token.",
        status_code=401,
        details={"reason": reason},
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def get_token_validator(request: Request) -> TokenValidator:
    validator: TokenValidator = request.app.state.token_validator
    return validator


async def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    validator: Annotated[TokenValidator, Depends(get_token_validator)],
) -> Principal:
    if credentials is None:
        raise unauthenticated("missing_token")
    try:
        return await validator.validate_async(credentials.credentials)
    except AuthenticationError as exc:
        raise unauthenticated(exc.reason) from exc


async def get_current_user(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """The signed-in platform user, created on first sign-in. Sets app.user_id for RLS."""
    return await resolve_user(session, principal)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
CurrentUser = Annotated[User, Depends(get_current_user)]
