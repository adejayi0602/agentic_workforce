import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from workforce_api.auth.dependencies import CurrentUser

router = APIRouter(tags=["identity"])


class Me(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None


@router.get("/me", response_model=Me)
async def get_me(user: CurrentUser) -> Me:
    """The signed-in user. The first call after sign-in creates the user record."""
    return Me(id=user.id, email=user.email, display_name=user.display_name)
