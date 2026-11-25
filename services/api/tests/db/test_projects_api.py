"""Projects API (FR-001) against a real database."""

import asyncio
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def new_key() -> str:
    return "P" + uuid.uuid4().hex[:6].upper()


def project_body(**overrides: Any) -> dict[str, Any]:
    return {"key": new_key(), "name": "Payments", "type": "software", **overrides}


async def org_with(api: Any, *roles: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    """An organisation (admin = first returned headers) plus one member per role."""
    admin = await api.sign_in()
    org = await api.create_org(admin)
    people = [api.in_org(admin, org["id"])]
    for role in roles:
        person = await api.sign_in()
        await api.add_member(org["id"], await api.user_id(person), role)
        people.append(api.in_org(person, org["id"]))
    return org, people


async def test_create_and_read_a_project(api: Any) -> None:
    _, [admin] = await org_with(api)
    body = project_body(description="Card payments")
    created = await api.client.post("/api/v1/projects", json=body, headers=admin)
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["key"] == body["key"]
    assert project["status"] == "active"
    assert project["owner_id"] == await api.user_id(admin)

    fetched = await api.client.get(f"/api/v1/projects/{project['id']}", headers=admin)
    assert fetched.json() == project


async def test_who_may_create(api: Any) -> None:
    _, [_, owner, manager, member] = await org_with(
        api, "project_owner", "project_manager", "member"
    )
    assert (
        await api.client.post("/api/v1/projects", json=project_body(), headers=owner)
    ).status_code == 201
    for headers in (manager, member):
        r = await api.client.post("/api/v1/projects", json=project_body(), headers=headers)
        assert r.status_code == 403


async def test_duplicate_key_is_a_conflict(api: Any) -> None:
    _, [admin] = await org_with(api)
    body = project_body()
    await api.client.post("/api/v1/projects", json=body, headers=admin)
    again = await api.client.post("/api/v1/projects", json={**body, "name": "Other"}, headers=admin)
    assert again.status_code == 409
    assert again.json()["error"]["details"] == {"field": "key"}


async def test_same_key_in_two_organisations_is_fine(api: Any) -> None:
    _, [a] = await org_with(api)
    _, [b] = await org_with(api)
    body = project_body()
    assert (await api.client.post("/api/v1/projects", json=body, headers=a)).status_code == 201
    assert (await api.client.post("/api/v1/projects", json=body, headers=b)).status_code == 201


async def test_invalid_input_is_rejected(api: Any) -> None:
    _, [admin] = await org_with(api)
    for bad in (
        project_body(key="lowercase"),
        project_body(type="spaceship"),
        project_body(name=""),
        {**project_body(), "unexpected": True},
    ):
        r = await api.client.post("/api/v1/projects", json=bad, headers=admin)
        assert r.status_code == 422, bad


async def test_owner_must_be_a_member(api: Any) -> None:
    _, [admin, member] = await org_with(api, "member")
    outsider = await api.sign_in()
    r = await api.client.post(
        "/api/v1/projects", json=project_body(owner_id=await api.user_id(outsider)), headers=admin
    )
    assert r.status_code == 422
    member_id = await api.user_id(member)
    ok = await api.client.post(
        "/api/v1/projects", json=project_body(owner_id=member_id), headers=admin
    )
    assert ok.json()["owner_id"] == member_id


async def test_list_pages_and_filters(api: Any) -> None:
    _, [admin] = await org_with(api)
    ids = [
        (await api.client.post("/api/v1/projects", json=project_body(), headers=admin)).json()["id"]
        for _ in range(3)
    ]
    await api.client.patch(f"/api/v1/projects/{ids[0]}", json={"status": "archived"}, headers=admin)

    first = (await api.client.get("/api/v1/projects", params={"limit": 2}, headers=admin)).json()
    second = (
        await api.client.get(
            "/api/v1/projects", params={"limit": 2, "cursor": first["next_cursor"]}, headers=admin
        )
    ).json()
    assert {p["id"] for p in first["items"] + second["items"]} == set(ids)
    assert second["next_cursor"] is None

    active = (
        await api.client.get("/api/v1/projects", params={"status": "active"}, headers=admin)
    ).json()
    assert {p["id"] for p in active["items"]} == set(ids[1:])


async def test_projects_of_another_organisation_are_invisible(api: Any) -> None:
    _, [a] = await org_with(api)
    _, [b] = await org_with(api)
    theirs = (await api.client.post("/api/v1/projects", json=project_body(), headers=b)).json()

    assert (await api.client.get(f"/api/v1/projects/{theirs['id']}", headers=a)).status_code == 404
    patch = await api.client.patch(
        f"/api/v1/projects/{theirs['id']}", json={"name": "x"}, headers=a
    )
    assert patch.status_code == 404
    listed = (await api.client.get("/api/v1/projects", headers=a)).json()
    assert theirs["id"] not in {p["id"] for p in listed["items"]}


async def test_update_and_archive_permissions(api: Any) -> None:
    _, [admin, manager] = await org_with(api, "project_manager")
    project = (await api.client.post("/api/v1/projects", json=project_body(), headers=admin)).json()
    url = f"/api/v1/projects/{project['id']}"

    renamed = await api.client.patch(url, json={"name": "Payments v2"}, headers=manager)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Payments v2"

    archive = await api.client.patch(url, json={"status": "archived"}, headers=manager)
    assert archive.status_code == 403
    assert archive.json()["error"]["details"]["permission"] == "project.archive"

    archived = await api.client.patch(url, json={"status": "archived"}, headers=admin)
    assert archived.json()["status"] == "archived"


async def test_key_is_immutable_and_nulls_are_refused(api: Any) -> None:
    _, [admin] = await org_with(api)
    project = (await api.client.post("/api/v1/projects", json=project_body(), headers=admin)).json()
    url = f"/api/v1/projects/{project['id']}"
    assert (await api.client.patch(url, json={"key": "NEWKEY"}, headers=admin)).status_code == 422
    assert (await api.client.patch(url, json={"name": None}, headers=admin)).status_code == 422
    cleared = await api.client.patch(url, json={"description": None}, headers=admin)
    assert cleared.status_code == 200


async def test_project_changes_are_audited(api: Any) -> None:
    _, [admin, manager] = await org_with(api, "project_manager")
    project = (await api.client.post("/api/v1/projects", json=project_body(), headers=admin)).json()
    url = f"/api/v1/projects/{project['id']}"
    await api.client.patch(url, json={"name": "Renamed", "description": "d"}, headers=admin)
    await api.client.patch(url, json={"status": "archived"}, headers=manager)  # denied
    await api.client.patch(url, json={"status": "archived"}, headers=admin)

    events = (await api.client.get(f"{url}/audit-events", headers=admin)).json()["items"]
    summary = sorted((e["action"], e["decision"]) for e in events)
    assert summary == [
        ("project.archive", "allowed"),
        ("project.create", "allowed"),
        ("project.update", "allowed"),
    ]
    update = next(e for e in events if e["action"] == "project.update")
    assert update["details"] == {"fields": ["description", "name"]}

    org_events = (await api.client.get("/api/v1/audit-events", headers=admin)).json()["items"]
    denial = next(e for e in org_events if e["decision"] == "denied")
    assert denial["action"] == "project.archive"


async def test_idempotent_create_replays_the_original(api: Any) -> None:
    _, [admin] = await org_with(api)
    body = project_body()
    headers = {**admin, "Idempotency-Key": f"create-{uuid.uuid4()}"}
    first = await api.client.post("/api/v1/projects", json=body, headers=headers)
    second = await api.client.post("/api/v1/projects", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert "Idempotent-Replayed" not in first.headers


async def test_idempotency_key_reused_with_a_different_body(api: Any) -> None:
    _, [admin] = await org_with(api)
    headers = {**admin, "Idempotency-Key": f"create-{uuid.uuid4()}"}
    await api.client.post("/api/v1/projects", json=project_body(), headers=headers)
    r = await api.client.post("/api/v1/projects", json=project_body(), headers=headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_concurrent_retries_create_one_project(api: Any) -> None:
    _, [admin] = await org_with(api)
    body = project_body()
    headers = {**admin, "Idempotency-Key": f"create-{uuid.uuid4()}"}
    responses = await asyncio.gather(
        *(api.client.post("/api/v1/projects", json=body, headers=headers) for _ in range(5))
    )
    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    listed = (await api.client.get("/api/v1/projects", headers=admin)).json()["items"]
    assert [p["key"] for p in listed].count(body["key"]) == 1


async def test_a_failed_create_does_not_burn_the_key(api: Any) -> None:
    org, [admin] = await org_with(api)
    newcomer = await api.sign_in()
    newcomer_id = await api.user_id(newcomer)
    body = project_body(owner_id=newcomer_id)
    headers = {**admin, "Idempotency-Key": f"create-{uuid.uuid4()}"}

    failed = await api.client.post("/api/v1/projects", json=body, headers=headers)
    assert failed.status_code == 422  # owner not yet a member
    await api.add_member(org["id"], newcomer_id, "member")
    retried = await api.client.post("/api/v1/projects", json=body, headers=headers)
    assert retried.status_code == 201


async def test_idempotency_keys_are_per_user(api: Any) -> None:
    _, [admin, owner] = await org_with(api, "project_owner")
    key = f"shared-{uuid.uuid4()}"
    a = await api.client.post(
        "/api/v1/projects", json=project_body(), headers={**admin, "Idempotency-Key": key}
    )
    b = await api.client.post(
        "/api/v1/projects", json=project_body(), headers={**owner, "Idempotency-Key": key}
    )
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


async def test_short_idempotency_key_is_rejected(api: Any) -> None:
    _, [admin] = await org_with(api)
    r = await api.client.post(
        "/api/v1/projects", json=project_body(), headers={**admin, "Idempotency-Key": "short"}
    )
    assert r.status_code == 400
