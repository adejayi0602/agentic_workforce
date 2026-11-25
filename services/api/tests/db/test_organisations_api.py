"""Organisations, memberships and roles through the API, against a real database."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from workforce_api.config import Settings
from workforce_api.main import create_app

pytestmark = pytest.mark.integration

SignIn = Callable[[str], Awaitable[dict[str, str]]]


@pytest.fixture
async def client(test_database: Any) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        env="test",
        organisation_creation="open",
        database_url=test_database.app_url.render_as_string(hide_password=False),
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


@pytest.fixture
def sign_in(client: httpx.AsyncClient) -> SignIn:
    async def _sign_in(subject: str) -> dict[str, str]:
        r = await client.post(
            "/api/v1/dev-auth/token",
            json={"subject": subject, "email": f"{subject}@example.com", "name": subject},
        )
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await client.get("/api/v1/me", headers=headers)  # provision the user
        return headers

    return _sign_in


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def create_org(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    slug = unique("org")
    r = await client.post(
        "/api/v1/organisations", json={"name": slug, "slug": slug}, headers=headers
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def in_org(headers: dict[str, str], org_id: str) -> dict[str, str]:
    return {**headers, "X-Organisation-ID": org_id}


async def add_member(test_database: Any, org_id: str, user_id: str, role: str) -> None:
    """Invitations arrive later; until then tests add members directly as the schema owner."""
    owner = create_async_engine(test_database.owner_url)
    try:
        async with owner.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.organisation_id', :o, true)"), {"o": org_id}
            )
            await conn.execute(
                text(
                    "INSERT INTO organisation_members (organisation_id, user_id, role) "
                    "VALUES (:o, :u, :r)"
                ),
                {"o": org_id, "u": user_id, "r": role},
            )
    finally:
        await owner.dispose()


async def user_id(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    return str((await client.get("/api/v1/me", headers=headers)).json()["id"])


async def test_creator_becomes_org_admin_and_sees_membership(
    client: httpx.AsyncClient, sign_in: SignIn
) -> None:
    alice = await sign_in(unique("alice"))
    org = await create_org(client, alice)
    assert org["your_role"] == "org_admin"

    me = (await client.get("/api/v1/me", headers=alice)).json()
    assert [m["organisation_id"] for m in me["memberships"]] == [org["id"]]
    assert me["memberships"][0]["role"] == "org_admin"


async def test_duplicate_slug_is_a_conflict(client: httpx.AsyncClient, sign_in: SignIn) -> None:
    alice = await sign_in(unique("alice"))
    org = await create_org(client, alice)
    r = await client.post(
        "/api/v1/organisations", json={"name": "again", "slug": org["slug"]}, headers=alice
    )
    assert r.status_code == 409
    assert r.json()["error"]["details"] == {"field": "slug"}


async def test_organisation_creation_can_be_closed(test_database: Any) -> None:
    settings = Settings(
        env="test",
        organisation_creation="closed",
        database_url=test_database.app_url.render_as_string(hide_password=False),
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c,
    ):
        token = (await c.post("/api/v1/dev-auth/token", json={"subject": unique("x")})).json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        r = await c.post(
            "/api/v1/organisations", json={"name": "n", "slug": unique("o")}, headers=headers
        )
    assert r.status_code == 403


async def test_current_organisation_requires_the_header(
    client: httpx.AsyncClient, sign_in: SignIn
) -> None:
    alice = await sign_in(unique("alice"))
    r = await client.get("/api/v1/organisations/current", headers=alice)
    assert r.status_code == 400
    assert r.json()["error"]["details"] == {"header": "X-Organisation-ID"}


async def test_current_organisation_shows_role_and_permissions(
    client: httpx.AsyncClient, sign_in: SignIn
) -> None:
    alice = await sign_in(unique("alice"))
    org = await create_org(client, alice)
    r = await client.get("/api/v1/organisations/current", headers=in_org(alice, org["id"]))
    assert r.status_code == 200
    assert r.json()["your_role"] == "org_admin"
    assert "members.manage" in r.json()["your_permissions"]


async def test_non_member_gets_404_not_403(client: httpx.AsyncClient, sign_in: SignIn) -> None:
    alice, mallory = await sign_in(unique("alice")), await sign_in(unique("mallory"))
    org = await create_org(client, alice)
    for path in ("/api/v1/organisations/current", "/api/v1/organisations/current/members"):
        r = await client.get(path, headers=in_org(mallory, org["id"]))
        assert r.status_code == 404, path
    r = await client.get(
        "/api/v1/organisations/current", headers=in_org(mallory, str(uuid.uuid4()))
    )
    assert r.status_code == 404


async def test_member_can_read_but_not_manage(
    client: httpx.AsyncClient, sign_in: SignIn, test_database: Any
) -> None:
    alice, bob = await sign_in(unique("alice")), await sign_in(unique("bob"))
    org = await create_org(client, alice)
    alice_id, bob_id = await user_id(client, alice), await user_id(client, bob)
    await add_member(test_database, org["id"], bob_id, "member")

    members = await client.get(
        "/api/v1/organisations/current/members", headers=in_org(bob, org["id"])
    )
    assert members.status_code == 200
    assert {m["user_id"] for m in members.json()} == {alice_id, bob_id}

    r = await client.patch(
        f"/api/v1/organisations/current/members/{alice_id}",
        json={"role": "member"},
        headers=in_org(bob, org["id"]),
    )
    assert r.status_code == 403
    assert r.json()["error"]["details"] == {"permission": "members.manage", "role": "member"}


async def test_admin_changes_roles_but_cannot_remove_last_admin(
    client: httpx.AsyncClient, sign_in: SignIn, test_database: Any
) -> None:
    alice, bob = await sign_in(unique("alice")), await sign_in(unique("bob"))
    org = await create_org(client, alice)
    alice_id, bob_id = await user_id(client, alice), await user_id(client, bob)
    await add_member(test_database, org["id"], bob_id, "member")
    as_alice = in_org(alice, org["id"])
    base = "/api/v1/organisations/current/members"

    promoted = await client.patch(
        f"{base}/{bob_id}", json={"role": "project_owner"}, headers=as_alice
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "project_owner"

    demote_self = await client.patch(
        f"{base}/{alice_id}", json={"role": "member"}, headers=as_alice
    )
    assert demote_self.status_code == 409
    remove_self = await client.delete(f"{base}/{alice_id}", headers=as_alice)
    assert remove_self.status_code == 409

    removed = await client.delete(f"{base}/{bob_id}", headers=as_alice)
    assert removed.status_code == 204
    gone = await client.delete(f"{base}/{bob_id}", headers=as_alice)
    assert gone.status_code == 404


async def test_with_two_admins_one_can_step_down(
    client: httpx.AsyncClient, sign_in: SignIn, test_database: Any
) -> None:
    alice, bob = await sign_in(unique("alice")), await sign_in(unique("bob"))
    org = await create_org(client, alice)
    alice_id, bob_id = await user_id(client, alice), await user_id(client, bob)
    await add_member(test_database, org["id"], bob_id, "org_admin")
    r = await client.patch(
        f"/api/v1/organisations/current/members/{alice_id}",
        json={"role": "member"},
        headers=in_org(alice, org["id"]),
    )
    assert r.status_code == 200


async def test_cannot_manage_members_of_another_organisation(
    client: httpx.AsyncClient, sign_in: SignIn
) -> None:
    alice, carol = await sign_in(unique("alice")), await sign_in(unique("carol"))
    org_a = await create_org(client, alice)
    org_c = await create_org(client, carol)
    carol_id = await user_id(client, carol)
    # Alice is admin of A, and targets Carol (a member of C only) while acting in A.
    r = await client.delete(
        f"/api/v1/organisations/current/members/{carol_id}", headers=in_org(alice, org_a["id"])
    )
    assert r.status_code == 404
    still_there = await client.get(
        "/api/v1/organisations/current/members", headers=in_org(carol, org_c["id"])
    )
    assert carol_id in {m["user_id"] for m in still_there.json()}
