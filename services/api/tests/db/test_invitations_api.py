"""Organisation invitations (#11): invite, accept on sign-in, revoke, expiry, audit."""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

Api = Any  # the `api` fixture from conftest.py


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def _admin_org(api: Api) -> tuple[dict[str, str], dict[str, str]]:
    admin = await api.sign_in()
    org = await api.create_org(admin)
    return api.in_org(admin, org["id"]), org


async def _invitee(api: Api) -> tuple[dict[str, str], str]:
    name = unique("invitee")
    return await api.sign_in(name), f"{name}@example.com"


async def test_invite_and_accept_joins_with_role(api: Api) -> None:
    admin, org = await _admin_org(api)
    invitee, email = await _invitee(api)
    invitation, token = await api.invite(admin, email.upper(), role="project_manager")
    assert invitation["email"] == email  # stored lower-case
    assert invitation["status"] == "pending"
    assert invitation["email_sent"] is True

    preview = await api.client.post(
        "/api/v1/invitations/preview", json={"token": token}, headers=invitee
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["organisation_name"] == org["name"]
    assert preview.json()["role"] == "project_manager"

    # Not a member yet.
    assert (
        await api.client.get("/api/v1/projects", headers=api.in_org(invitee, org["id"]))
    ).status_code == 404

    accepted = await api.client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=invitee
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"organisation_id": org["id"], "role": "project_manager"}

    members = await api.client.get("/api/v1/organisations/current/members", headers=admin)
    roles = {m["email"]: m["role"] for m in members.json()}
    assert roles[email] == "project_manager"

    listed = await api.client.get("/api/v1/organisations/current/invitations", headers=admin)
    assert [i["status"] for i in listed.json()] == ["accepted"]

    actions = [
        r["action"]
        for r in await api.owner_read(
            "audit_events", "organisation_id = :o ORDER BY created_at", {"o": org["id"]}
        )
    ]
    assert "invitation.create" in actions
    assert "invitation.accept" in actions
    events = await api.owner_read("outbox_events", "organisation_id = :o", {"o": org["id"]})
    assert "member.joined" in {e["event_type"] for e in events}


async def test_token_is_single_use(api: Api) -> None:
    admin, _ = await _admin_org(api)
    invitee, email = await _invitee(api)
    _, token = await api.invite(admin, email)
    first = await api.client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=invitee
    )
    assert first.status_code == 200
    again = await api.client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=invitee
    )
    assert again.status_code == 409
    assert again.json()["error"]["details"]["status"] == "accepted"


async def test_only_the_invited_email_can_accept(api: Api) -> None:
    admin, org = await _admin_org(api)
    _, email = await _invitee(api)
    stranger = await api.sign_in()
    _, token = await api.invite(admin, email)
    r = await api.client.post("/api/v1/invitations/accept", json={"token": token}, headers=stranger)
    assert r.status_code == 403
    assert email not in r.text  # masked
    rows = await api.owner_read(
        "organisation_invitations", "organisation_id = :o", {"o": org["id"]}
    )
    assert rows[0]["status"] == "pending"


async def test_revoked_invitation_cannot_be_used(api: Api) -> None:
    admin, _ = await _admin_org(api)
    invitee, email = await _invitee(api)
    invitation, token = await api.invite(admin, email)
    r = await api.client.delete(
        f"/api/v1/organisations/current/invitations/{invitation['id']}", headers=admin
    )
    assert r.status_code == 204
    again = await api.client.delete(
        f"/api/v1/organisations/current/invitations/{invitation['id']}", headers=admin
    )
    assert again.status_code == 409
    used = await api.client.post(
        "/api/v1/invitations/accept", json={"token": token}, headers=invitee
    )
    assert used.status_code == 409
    assert used.json()["error"]["details"]["status"] == "revoked"


async def test_expired_invitation_cannot_be_used(api: Api) -> None:
    admin, org = await _admin_org(api)
    invitee, email = await _invitee(api)
    invitation, token = await api.invite(admin, email)
    owner = create_async_engine(api.database.owner_url)
    try:
        async with owner.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.organisation_id', :o, true)"), {"o": org["id"]}
            )
            await conn.execute(
                text(
                    "UPDATE organisation_invitations "
                    "SET expires_at = now() - interval '1 minute' WHERE id = :i"
                ),
                {"i": invitation["id"]},
            )
    finally:
        await owner.dispose()
    listed = await api.client.get("/api/v1/organisations/current/invitations", headers=admin)
    assert listed.json()[0]["status"] == "expired"
    r = await api.client.post("/api/v1/invitations/accept", json={"token": token}, headers=invitee)
    assert r.status_code == 409
    assert r.json()["error"]["details"]["status"] == "expired"


async def test_duplicate_pending_and_existing_member_are_refused(api: Api) -> None:
    admin, _ = await _admin_org(api)
    _, email = await _invitee(api)
    await api.invite(admin, email)
    dup = await api.client.post(
        "/api/v1/organisations/current/invitations", json={"email": email}, headers=admin
    )
    assert dup.status_code == 409
    me = (await api.client.get("/api/v1/me", headers=admin)).json()["email"]
    self_invite = await api.client.post(
        "/api/v1/organisations/current/invitations", json={"email": me}, headers=admin
    )
    assert self_invite.status_code == 409


async def test_unknown_token_is_not_found(api: Api) -> None:
    user = await api.sign_in()
    r = await api.client.post("/api/v1/invitations/preview", json={"token": "x" * 43}, headers=user)
    assert r.status_code == 404


async def test_members_cannot_manage_invitations(api: Api) -> None:
    _, org = await _admin_org(api)
    member = await api.sign_in()
    await api.add_member(org["id"], await api.user_id(member), "project_manager")
    headers = api.in_org(member, org["id"])
    r = await api.client.post(
        "/api/v1/organisations/current/invitations",
        json={"email": "a@example.com"},
        headers=headers,
    )
    assert r.status_code == 403
    assert (
        await api.client.get("/api/v1/organisations/current/invitations", headers=headers)
    ).status_code == 403


async def test_token_hash_reveals_only_its_own_invitation(api: Api) -> None:
    """The by-token RLS policy must not leak other invitations to a token holder."""
    admin, _ = await _admin_org(api)
    other_admin, _ = await _admin_org(api)
    invitee, email = await _invitee(api)
    _, token = await api.invite(admin, email)
    await api.invite(other_admin, unique("someone") + "@example.com")
    preview: Any = await api.client.post(
        "/api/v1/invitations/preview", json={"token": token}, headers=invitee
    )
    assert preview.status_code == 200
    assert preview.json()["email"] == email


async def test_token_is_never_stored(api: Api) -> None:
    admin, org = await _admin_org(api)
    _, email = await _invitee(api)
    _, token = await api.invite(admin, email)
    rows = await api.owner_read(
        "organisation_invitations", "organisation_id = :o", {"o": org["id"]}
    )
    assert token not in str(dict(rows[0]))
