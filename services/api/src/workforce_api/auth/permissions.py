"""Role → permission policy (spec §6 access column).

Deterministic and table-driven: no LLM, no I/O. Changing what a role may do means changing
this table, which `test_permissions.py` pins so the change is visible in review.
"""

from enum import StrEnum

from workforce_api.modules.identity.models import Role


class Permission(StrEnum):
    ORG_READ = "org.read"
    ORG_UPDATE = "org.update"
    MEMBERS_READ = "members.read"
    MEMBERS_MANAGE = "members.manage"
    PROJECT_CREATE = "project.create"
    PROJECT_READ = "project.read"
    PROJECT_UPDATE = "project.update"
    PROJECT_ARCHIVE = "project.archive"
    AUDIT_READ = "audit.read"


_EVERYONE = frozenset({Permission.ORG_READ, Permission.MEMBERS_READ, Permission.PROJECT_READ})

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ORG_ADMIN: frozenset(Permission),
    Role.PROJECT_OWNER: _EVERYONE
    | {Permission.PROJECT_CREATE, Permission.PROJECT_UPDATE, Permission.PROJECT_ARCHIVE},
    Role.PROJECT_MANAGER: _EVERYONE | {Permission.PROJECT_UPDATE},
    Role.MEMBER: _EVERYONE,
    Role.AUDITOR: _EVERYONE | {Permission.AUDIT_READ},
}


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def is_allowed(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
