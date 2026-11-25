"""Sign-in through the HTTP API against a real database, as the API's own role."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from workforce_api.config import Settings
from workforce_api.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(test_database: Any) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        env="test",
        database_url=test_database.app_url.render_as_string(hide_password=False),
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def sign_in(client: httpx.AsyncClient, subject: str, **claims: str) -> dict[str, str]:
    response = await client.post("/api/v1/dev-auth/token", json={"subject": subject, **claims})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_first_sign_in_creates_the_user(client: httpx.AsyncClient) -> None:
    headers = await sign_in(client, "first-timer", email="first@example.com", name="First")
    response = await client.get("/api/v1/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "first@example.com"
    assert body["display_name"] == "First"


async def test_repeat_sign_in_returns_the_same_user(client: httpx.AsyncClient) -> None:
    headers = await sign_in(client, "returning")
    first = (await client.get("/api/v1/me", headers=headers)).json()
    second = (await client.get("/api/v1/me", headers=headers)).json()
    assert first["id"] == second["id"]


async def test_profile_follows_the_identity_provider(client: httpx.AsyncClient) -> None:
    before = (await client.get("/api/v1/me", headers=await sign_in(client, "mover"))).json()
    after_headers = await sign_in(client, "mover", email="new@example.com")
    after = (await client.get("/api/v1/me", headers=after_headers)).json()
    assert after["id"] == before["id"]
    assert after["email"] == "new@example.com"


async def test_different_subjects_are_different_users(client: httpx.AsyncClient) -> None:
    a = (await client.get("/api/v1/me", headers=await sign_in(client, "user-a"))).json()
    b = (await client.get("/api/v1/me", headers=await sign_in(client, "user-b"))).json()
    assert a["id"] != b["id"]


async def test_concurrent_first_sign_ins_create_one_user(client: httpx.AsyncClient) -> None:
    headers = await sign_in(client, "racer")
    responses = await asyncio.gather(*(client.get("/api/v1/me", headers=headers) for _ in range(5)))
    assert {r.status_code for r in responses} == {200}
    assert len({r.json()["id"] for r in responses}) == 1


async def test_disabled_user_is_refused(client: httpx.AsyncClient, test_database: Any) -> None:
    headers = await sign_in(client, "to-disable")
    user_id = (await client.get("/api/v1/me", headers=headers)).json()["id"]

    owner = create_async_engine(test_database.owner_url)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": user_id})
            await conn.execute(
                text("UPDATE users SET status = 'disabled' WHERE id = :u"), {"u": user_id}
            )
    finally:
        await owner.dispose()

    response = await client.get("/api/v1/me", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
