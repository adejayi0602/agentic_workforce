"""The permission policy, pinned. A change here must be deliberate and visible in review."""

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from workforce_api.auth.permissions import ROLE_PERMISSIONS, Permission, is_allowed
from workforce_api.config import Settings
from workforce_api.main import create_app
from workforce_api.modules.identity.models import Role

EXPECTED: dict[Role, set[str]] = {
    Role.ORG_ADMIN: {p.value for p in Permission},
    Role.PROJECT_OWNER: {
        "org.read",
        "members.read",
        "project.read",
        "project.create",
        "project.update",
        "project.archive",
    },
    Role.PROJECT_MANAGER: {"org.read", "members.read", "project.read", "project.update"},
    Role.MEMBER: {"org.read", "members.read", "project.read"},
    Role.AUDITOR: {"org.read", "members.read", "project.read", "audit.read"},
}

# Routes that deliberately need no organisation permission.
PUBLIC_ROUTES = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/dev-auth/token"),
    ("GET", "/api/v1/me"),  # signed-in user only; shows the user's own data
    ("POST", "/api/v1/organisations"),  # signed-in user; gated by organisation_creation
}


def test_every_role_has_a_policy() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_policy_matches_the_agreed_matrix() -> None:
    actual = {role: {p.value for p in perms} for role, perms in ROLE_PERMISSIONS.items()}
    assert actual == EXPECTED


def test_only_org_admins_manage_members() -> None:
    assert [r for r in Role if is_allowed(r, Permission.MEMBERS_MANAGE)] == [Role.ORG_ADMIN]


def test_audit_trail_is_limited_to_admins_and_auditors() -> None:
    allowed = {r for r in Role if is_allowed(r, Permission.AUDIT_READ)}
    assert allowed == {Role.ORG_ADMIN, Role.AUDITOR}


def _required_permissions(dependant: Dependant) -> set[Permission]:
    found: set[Permission] = set()
    for dep in dependant.dependencies:
        permission = getattr(dep.call, "required_permission", None)
        if permission is not None:
            found.add(permission)
        found |= _required_permissions(dep)
    return found


def test_every_non_public_route_declares_a_permission() -> None:
    app = create_app(Settings(env="test"))
    missing = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if (method, route.path) in PUBLIC_ROUTES:
                continue
            if not _required_permissions(route.dependant):
                missing.append(f"{method} {route.path}")
    assert not missing, f"Routes without a required permission: {missing}"
