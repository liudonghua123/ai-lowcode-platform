"""Row-level data scopes for business data.

The platform distinguishes three visibility levels:

* ``all``   — the super administrator (role ``admin`` / ``*`` permission): full
  read/write access to every row.
* ``audit`` — the audit administrator (role ``auditor`` / ``data:audit``): a
  **read-only** role that can see *all* rows of the audit-class resources
  (form submissions, workflow instances, approval tasks, audit logs, MCP call
  logs). It never gets write access, and other resources still fall back to
  ``self``.
* ``self``  — everyone else: only rows they own (``submitted_by``,
  ``started_by``, ``assignee``, ``user_id`` …).

Design decisions (see ADR-0010):

* **Definition assets are shared.** Forms, workflows, agents, knowledge
  collections, MCP servers/skills, AI providers, users and roles are platform
  configuration, not personal business data. They stay governed by RBAC
  permission codes (``form:read`` …), not by owner filtering.
* **Business data is owner-scoped.** Submissions, instances, tasks,
  conversations and journals are filtered through :func:`owner_clause`.
* Every helper takes the user dict produced by ``deps._load_user`` so it can be
  used from REST routers, MCP tools and the AI agent runtime alike.
"""
from __future__ import annotations

from typing import Any

# owner column, backing table, whether auditors may read every row of it
OWNED_RESOURCES: dict[str, dict[str, Any]] = {
    "form_submissions": {"owner": "submitted_by", "table": "form_submissions", "audit": True},
    "workflow_instances": {"owner": "started_by", "table": "workflow_instances", "audit": True},
    "flow_tasks": {"owner": "assignee", "table": "flow_tasks", "audit": True,
                   "also_instance_initiator": True},
    "conversations": {"owner": "user_id", "table": "conversations", "audit": False},
    "audit_logs": {"owner": "actor", "table": "audit_logs", "audit": True},
    "mcp_call_logs": {"owner": "actor", "table": "mcp_call_logs", "audit": True},
}

SHARED_RESOURCES: list[str] = [
    "forms", "workflows", "agents", "kb_collections", "kb_documents",
    "mcp_servers", "mcp_skills", "ai_providers", "roles", "users", "org_units",
]

AUDIT_RESOURCES: list[str] = sorted(k for k, v in OWNED_RESOURCES.items() if v["audit"])


def is_super_admin(user: dict | None) -> bool:
    return bool(user and (user.get("is_admin") or "*" in (user.get("permissions") or [])))


def is_auditor(user: dict | None) -> bool:
    if not user or is_super_admin(user):
        return False
    return "auditor" in (user.get("role_codes") or []) or \
        "data:audit" in (user.get("permissions") or [])


def role(user: dict | None) -> str:
    """Return the coarse data scope of a user: all | audit | self | anonymous."""
    if not user:
        return "anonymous"
    if is_super_admin(user):
        return "all"
    if is_auditor(user):
        return "audit"
    return "self"


def scope_for(user: dict | None, resource: str) -> str:
    """Effective scope for one resource: all | audit | self | anonymous."""
    coarse = role(user)
    if coarse in {"all", "anonymous"}:
        return coarse
    if coarse == "audit" and resource in AUDIT_RESOURCES:
        return "audit"
    return "self"


def can_read_all(user: dict | None, resource: str) -> bool:
    return scope_for(user, resource) in {"all", "audit"}


def read_only(user: dict | None) -> bool:
    """The audit administrator must never mutate business data."""
    return role(user) == "audit"


def owner_column(resource: str) -> str:
    return (OWNED_RESOURCES.get(resource) or {}).get("owner") or "created_by"


def owner_clause(user: dict | None, resource: str, alias: str = "",
                 column: str | None = None) -> tuple[str, list[Any]]:
    """Build a SQL predicate + args limiting a query to the rows a user may see.

    Returns ``("", [])`` when the user may read all rows. The optional ``alias``
    prefixes the owner column (e.g. ``"s"`` for ``SELECT s.* FROM ... s``).
    """
    meta = OWNED_RESOURCES.get(resource)
    if not meta:
        return "", []
    scope = scope_for(user, resource)
    if scope in {"all", "audit"}:
        return "", []
    if scope == "anonymous":
        return "1=0", []
    username = (user or {}).get("username") or ""
    col = f"{alias}.{column or meta['owner']}" if alias else (column or meta["owner"])
    if meta.get("also_instance_initiator"):
        return (f"({col}=? OR {alias + '.' if alias else ''}instance_id IN "
                "(SELECT id FROM workflow_instances WHERE started_by=?))",
                [username, username])
    return f"{col}=?", [username]


def row_visible(user: dict | None, resource: str, row: dict | None) -> bool:
    """Check a single row against the user's scope (used by detail endpoints)."""
    if row is None:
        return False
    if can_read_all(user, resource):
        return True
    if role(user) == "anonymous":
        return False
    username = (user or {}).get("username")
    if row.get(owner_column(resource)) == username:
        return True
    if resource == "flow_tasks":
        inst = str(row.get("instance_id") or "")
        return bool(inst and _instance_owner(inst) == username)
    return False


def _instance_owner(instance_id: str) -> str | None:
    from .. import db
    row = db.q1("SELECT started_by FROM workflow_instances WHERE id=?", (instance_id,))
    return row["started_by"] if row else None


def describe(user: dict | None) -> dict:
    """Human/machine readable scope description for /auth/me and who_am_i."""
    coarse = role(user)
    detail = {r: scope_for(user, r) for r in OWNED_RESOURCES}
    return {
        "role": coarse,
        "is_super_admin": is_super_admin(user),
        "is_auditor": is_auditor(user),
        "read_only": read_only(user),
        "owned_resources": detail,
        "audit_resources": AUDIT_RESOURCES,
        "shared_resources": SHARED_RESOURCES,
        "rule": {
            "all": "full read/write on every row",
            "audit": "read-only full visibility on audit-class resources; self on the rest",
            "self": "only rows owned by the current user",
            "anonymous": "no access",
        }[coarse],
    }
