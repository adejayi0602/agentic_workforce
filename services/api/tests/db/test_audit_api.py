"""Audit trail and outbox through the API (FR-022)."""

from typing import Any

import pytest

pytestmark = pytest.mark.integration


async def test_creating_an_organisation_is_audited(api: Any) -> None:
    alice = await api.sign_in()
    org = await api.create_org(alice)
    alice_id = await api.user_id(alice)

    r = await api.client.get("/api/v1/audit-events", headers=api.in_org(alice, org["id"]))
    assert r.status_code == 200
    [event] = r.json()["items"]
    assert event["action"] == "organisation.create"
    assert event["decision"] == "allowed"
    assert event["actor_id"] == alice_id
    assert event["resource_id"] == org["id"]


async def test_audit_event_carries_the_request_correlation_id(api: Any) -> None:
    alice = await api.sign_in()
    correlation_id = "0b5f6d1e-1a2b-4c3d-8e9f-0a1b2c3d4e5f"
    slug = "corr-" + correlation_id[:8]
    r = await api.client.post(
        "/api/v1/organisations",
        json={"name": slug, "slug": slug},
        headers={**alice, "X-Correlation-ID": correlation_id},
    )
    events = await api.client.get("/api/v1/audit-events", headers=api.in_org(alice, r.json()["id"]))
    assert events.json()["items"][0]["correlation_id"] == correlation_id


async def test_member_changes_are_audited_and_emitted_to_the_outbox(api: Any) -> None:
    alice, bob = await api.sign_in(), await api.sign_in()
    org = await api.create_org(alice)
    bob_id = await api.user_id(bob)
    await api.add_member(org["id"], bob_id, "member")
    as_alice = api.in_org(alice, org["id"])

    await api.client.patch(
        f"/api/v1/organisations/current/members/{bob_id}",
        json={"role": "auditor"},
        headers=as_alice,
    )
    await api.client.delete(f"/api/v1/organisations/current/members/{bob_id}", headers=as_alice)

    events = (await api.client.get("/api/v1/audit-events", headers=as_alice)).json()["items"]
    actions = [(e["action"], e["details"]) for e in events if e["resource_type"] == "member"]
    assert ("member.role_change", {"from": "member", "to": "auditor"}) in actions
    assert ("member.remove", {"role": "auditor"}) in actions

    outbox = await api.owner_read("outbox_events", "organisation_id = :o", {"o": org["id"]})
    assert sorted(e["event_type"] for e in outbox) == [
        "member.removed",
        "member.role_changed",
        "organisation.created",
    ]


async def test_denied_attempts_are_audited_even_though_the_request_fails(api: Any) -> None:
    alice, bob = await api.sign_in(), await api.sign_in()
    org = await api.create_org(alice)
    alice_id, bob_id = await api.user_id(alice), await api.user_id(bob)
    await api.add_member(org["id"], bob_id, "member")

    denied = await api.client.patch(
        f"/api/v1/organisations/current/members/{alice_id}",
        json={"role": "member"},
        headers=api.in_org(bob, org["id"]),
    )
    assert denied.status_code == 403

    events = (
        await api.client.get("/api/v1/audit-events", headers=api.in_org(alice, org["id"]))
    ).json()
    [denial] = [e for e in events["items"] if e["decision"] == "denied"]
    assert denial["actor_id"] == bob_id
    assert denial["action"] == "members.manage"
    assert denial["details"]["role"] == "member"
    assert denial["correlation_id"] == denied.json()["error"]["correlation_id"]


async def test_only_admins_and_auditors_read_the_audit_trail(api: Any) -> None:
    alice, auditor, member = await api.sign_in(), await api.sign_in(), await api.sign_in()
    org = await api.create_org(alice)
    await api.add_member(org["id"], await api.user_id(auditor), "auditor")
    await api.add_member(org["id"], await api.user_id(member), "member")

    ok = await api.client.get("/api/v1/audit-events", headers=api.in_org(auditor, org["id"]))
    assert ok.status_code == 200
    refused = await api.client.get("/api/v1/audit-events", headers=api.in_org(member, org["id"]))
    assert refused.status_code == 403


async def test_audit_trail_pages_with_a_cursor(api: Any) -> None:
    alice, bob = await api.sign_in(), await api.sign_in()
    org = await api.create_org(alice)
    bob_id = await api.user_id(bob)
    await api.add_member(org["id"], bob_id, "member")
    as_alice = api.in_org(alice, org["id"])
    for role in ("auditor", "member", "project_manager", "member"):
        await api.client.patch(
            f"/api/v1/organisations/current/members/{bob_id}", json={"role": role}, headers=as_alice
        )

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (
            await api.client.get("/api/v1/audit-events", params=params, headers=as_alice)
        ).json()
        assert len(page["items"]) <= 2
        seen += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5  # 1 create + 4 role changes
    assert len(set(seen)) == 5


async def test_invalid_cursor_is_a_400(api: Any) -> None:
    alice = await api.sign_in()
    org = await api.create_org(alice)
    r = await api.client.get(
        "/api/v1/audit-events", params={"cursor": "!!!"}, headers=api.in_org(alice, org["id"])
    )
    assert r.status_code == 400
    assert r.json()["error"]["details"] == {"parameter": "cursor"}


async def test_audit_trail_is_scoped_to_the_organisation(api: Any) -> None:
    alice, carol = await api.sign_in(), await api.sign_in()
    org_a = await api.create_org(alice)
    org_c = await api.create_org(carol)
    events = (
        await api.client.get("/api/v1/audit-events", headers=api.in_org(alice, org_a["id"]))
    ).json()
    assert org_c["id"] not in {e["resource_id"] for e in events["items"]}
