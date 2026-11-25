"""Cross-tenant isolation suite (FR-025, §16.1, ADR-0003).

Two organisations, A and B, each with an admin (the strongest role) and real data. Organisation
B then attacks A through every route the API exposes. The suite discovers routes from the app
itself, so a new endpoint is attacked automatically, and the suite fails until it says how.

Expected behaviour: anything that names A's organisation or A's resources returns 404, so B
learns nothing, not even that the resource exists. A's data is unchanged afterwards.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from workforce_api.common.routes import iter_api_routes
from workforce_api.config import Settings
from workforce_api.main import create_app

pytestmark = pytest.mark.integration

# Routes that are not organisation-scoped. Each is checked separately below.
NOT_ORG_SCOPED = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/dev-auth/token"),
    ("GET", "/api/v1/me"),
    ("POST", "/api/v1/organisations"),
}

# A valid body for every route that takes one, so a 404 can't be masked by a 422.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/api/v1/projects"): {"key": "XTEN", "name": "x", "type": "software"},
    ("PATCH", "/api/v1/projects/{project_id}"): {"name": "hijacked"},
    ("PATCH", "/api/v1/organisations/current/members/{user_id}"): {"role": "member"},
}

# List endpoints, and the A identifiers that must never appear in B's results.
LISTS = {
    "/api/v1/projects": "project_id",
    "/api/v1/audit-events": "any",
    "/api/v1/organisations/current/members": "user_id",
}


@dataclass
class Org:
    id: str
    admin: dict[str, str]
    admin_id: str
    project_id: str

    def headers(self) -> dict[str, str]:
        return {**self.admin, "X-Organisation-ID": self.id}


async def make_org(api: Any) -> Org:
    admin = await api.sign_in()
    org = await api.create_org(admin)
    headers = api.in_org(admin, org["id"])
    project = await api.client.post(
        "/api/v1/projects",
        json={"key": "P" + uuid.uuid4().hex[:6].upper(), "name": "Secret", "type": "software"},
        headers=headers,
    )
    return Org(org["id"], admin, await api.user_id(admin), project.json()["id"])


def routes() -> list[tuple[str, str]]:
    return [(r.method, r.path) for r in iter_api_routes(create_app(Settings(env="test")))]


def org_scoped_routes() -> list[tuple[str, str]]:
    return [r for r in routes() if r not in NOT_ORG_SCOPED]


def fill(path: str, victim: Org) -> str:
    values = {"project_id": victim.project_id, "user_id": victim.admin_id}

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise AssertionError(f"No cross-tenant value for path parameter {{{name}}} in {path}")
        return values[name]

    return re.sub(r"\{(\w+)\}", sub, path)


@pytest.fixture
async def orgs(api: Any) -> tuple[Org, Org]:
    return await make_org(api), await make_org(api)


def test_suite_covers_every_route() -> None:
    """Fails when a route is added without telling this suite how to attack it."""
    assert len(org_scoped_routes()) >= 10, "route discovery looks broken"
    for method, path in org_scoped_routes():
        fill(path, Org("a", {}, "u", "p"))  # every path parameter has a value
        if method in {"POST", "PATCH", "PUT"}:
            assert (method, path) in BODIES, f"Add a valid body for {method} {path} to BODIES"


@pytest.mark.parametrize(("method", "path"), org_scoped_routes())
async def test_non_member_cannot_reach_another_organisation(
    api: Any, orgs: tuple[Org, Org], method: str, path: str
) -> None:
    a, b = orgs
    response = await api.client.request(
        method,
        fill(path, a),
        json=BODIES.get((method, path)),
        headers={**b.admin, "X-Organisation-ID": a.id},
    )
    assert response.status_code == 404, f"{method} {path}: {response.status_code} {response.text}"


@pytest.mark.parametrize(("method", "path"), [r for r in org_scoped_routes() if "{" in r[1]])
async def test_member_cannot_reach_another_organisations_resources(
    api: Any, orgs: tuple[Org, Org], method: str, path: str
) -> None:
    a, b = orgs
    response = await api.client.request(
        method, fill(path, a), json=BODIES.get((method, path)), headers=b.headers()
    )
    assert response.status_code == 404, f"{method} {path}: {response.status_code} {response.text}"


async def test_lists_never_include_another_organisations_data(
    api: Any, orgs: tuple[Org, Org]
) -> None:
    a, b = orgs
    a_ids = {a.id, a.project_id, a.admin_id}
    for path in LISTS:
        body = (await api.client.get(path, headers=b.headers())).json()
        items = body["items"] if isinstance(body, dict) else body
        flat = repr(items)
        leaked = {i for i in a_ids if i in flat}
        assert not leaked, f"{path} leaked {leaked}"


async def test_list_routes_are_all_checked() -> None:
    gets = {path for method, path in org_scoped_routes() if method == "GET" and "{" not in path}
    assert gets - {"/api/v1/organisations/current"} == set(LISTS), "Add new list routes to LISTS"


async def test_me_shows_only_own_memberships(api: Any, orgs: tuple[Org, Org]) -> None:
    _, b = orgs
    me = (await api.client.get("/api/v1/me", headers=b.admin)).json()
    assert [m["organisation_id"] for m in me["memberships"]] == [b.id]


async def test_victim_data_is_untouched_after_the_attacks(api: Any, orgs: tuple[Org, Org]) -> None:
    a, b = orgs
    for method, path in org_scoped_routes():
        await api.client.request(
            method,
            fill(path, a),
            json=BODIES.get((method, path)),
            headers={**b.admin, "X-Organisation-ID": a.id},
        )
        if "{" in path:
            await api.client.request(
                method, fill(path, a), json=BODIES.get((method, path)), headers=b.headers()
            )

    project = (await api.client.get(f"/api/v1/projects/{a.project_id}", headers=a.headers())).json()
    assert project["name"] == "Secret"
    members = (
        await api.client.get("/api/v1/organisations/current/members", headers=a.headers())
    ).json()
    assert {m["user_id"]: m["role"] for m in members} == {a.admin_id: "org_admin"}
    a_projects = (await api.client.get("/api/v1/projects", headers=a.headers())).json()["items"]
    assert [p["id"] for p in a_projects] == [a.project_id], "an attack created a project in A"
