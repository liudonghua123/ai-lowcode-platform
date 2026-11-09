"""Authentication / RBAC dependencies and audit helpers."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from . import db, security


def _load_user(user_id: Any) -> dict | None:
    row = db.q1("SELECT * FROM users WHERE id=?", (user_id,))
    if not row or row.get("status") != "active":
        return None
    user = db.loads(row, "role_ids", "passkeys") or {}
    role_ids = user.get("role_ids") or []
    roles = []
    if role_ids:
        marks = ",".join("?" for _ in role_ids)
        roles = db.q(f"SELECT * FROM roles WHERE id IN ({marks})", tuple(role_ids))
    role_codes = [r["code"] for r in roles]
    permission_ids: list[int] = []
    for r in roles:
        loaded = db.loads(r, "permission_ids") or {}
        permission_ids.extend(loaded.get("permission_ids") or [])
    permissions = ["*"] if "admin" in role_codes else []
    if permission_ids:
        marks = ",".join("?" for _ in set(permission_ids))
        permissions += [p["code"] for p in db.q(
            f"SELECT code FROM permissions WHERE id IN ({marks})", tuple(set(permission_ids)))]
    from .services import data_scope
    admin = "admin" in role_codes or "*" in permissions
    user.update({
        "roles": roles,
        "role_codes": role_codes,
        "permissions": sorted(set(permissions)),
        "is_admin": admin,
        "is_auditor": not admin and ("auditor" in role_codes or "data:audit" in permissions),
        "data_scope": "all" if admin else
                      ("audit" if "auditor" in role_codes or "data:audit" in permissions else "self"),
    })
    user["data_scopes"] = data_scope.describe(user)
    return user


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = security.jwt_decode(token, expected_type="access")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user = _load_user(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")
    return user


def get_optional_user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization:
        return None
    try:
        return get_current_user(authorization)
    except HTTPException:
        return None


def has_permission(user: dict, permission: str) -> bool:
    perms = user.get("permissions") or []
    if "*" in perms:
        return True
    if permission in perms:
        return True
    resource = permission.split(":", 1)[0]
    return f"{resource}:*" in perms


def require(permission: str):
    """Dependency factory: ``Depends(require("workflow:write"))``."""
    def _checker(user: dict = Depends(get_current_user)) -> dict:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission}",
            )
        # Defence in depth: the audit administrator is a read-only role even if
        # somebody later grants it a write permission code by mistake.
        action = permission.rsplit(":", 1)[-1]
        if user.get("data_scope") == "audit" and action not in {"read", "view", "audit", "chat"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The audit administrator role is read-only",
            )
        return user
    return _checker


def audit(actor: str, action: str, resource: str | None = None,
          detail: dict | None = None, ip: str | None = None,
          level: str = "info", request: Request | None = None) -> None:
    if request is not None and not ip:
        ip = request.client.host if request.client else None
    db.insert("audit_logs", {
        "actor": actor or "anonymous",
        "action": action,
        "resource": resource,
        "detail": detail or {},
        "ip": ip,
        "level": level,
        "created_at": db.now(),
    })


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
