"""RBAC management: users, roles, permissions and the access matrix."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps, security

router = APIRouter(prefix="/rbac", tags=["RBAC"])


class RoleIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    name: str
    description: str | None = None
    permission_ids: list[int] = []
    mfa_required: bool = False


class RolePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_ids: list[int] | None = None
    mfa_required: bool | None = None


class UserIn(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str | None = Field(None, min_length=8)
    email: str | None = None
    display_name: str | None = None
    dept: str | None = None
    tags: list[str] = []
    role_ids: list[int] = []
    status: str = "active"


class UserPatch(BaseModel):
    email: str | None = None
    display_name: str | None = None
    dept: str | None = None
    tags: list[str] | None = None
    role_ids: list[int] | None = None
    status: str | None = None
    password: str | None = Field(None, min_length=8)


class ResetPasswordIn(BaseModel):
    password: str = Field(..., min_length=8)


class PermissionCheckIn(BaseModel):
    permission: str
    user_id: int | None = None


def _role_out(row: dict) -> dict:
    out = db.loads(row, "permission_ids") or {}
    out["builtin"] = bool(out.get("builtin"))
    out["mfa_required"] = bool(out.get("mfa_required"))
    return out


def _user_out(row: dict) -> dict:
    out = db.loads(row, "role_ids", "passkeys", "tags") or {}
    out.pop("password_hash", None)
    out.pop("otp_secret", None)
    out["status"] = out.get("status")
    out["otp_enabled"] = bool(out.get("otp_enabled"))
    out["passkey_enabled"] = bool(out.get("passkey_enabled"))
    out["passkey_count"] = len(out.get("passkeys") or [])
    out.pop("passkeys", None)
    return out


@router.get("/permissions", summary="Permission catalog")
def permissions(_user: dict = Depends(deps.require("rbac:read"))):
    rows = db.q("SELECT * FROM permissions ORDER BY resource,action")
    return {"permissions": rows, "total": len(rows)}


@router.get("/matrix", summary="Role x permission matrix")
def matrix(_user: dict = Depends(deps.require("rbac:read"))):
    perms = db.q("SELECT id,code,resource,action FROM permissions ORDER BY resource,action")
    roles = [db.loads(r, "permission_ids") for r in db.q("SELECT * FROM roles ORDER BY id")]
    return {"permissions": perms,
            "roles": [{"id": r["id"], "code": r["code"], "name": r["name"],
                       "permission_ids": r.get("permission_ids") or [],
                       "mfa_required": bool(r.get("mfa_required"))} for r in roles]}


@router.get("/roles", summary="List roles")
def list_roles(_user: dict = Depends(deps.require("rbac:read"))):
    rows = db.q("SELECT * FROM roles ORDER BY id")
    return {"roles": [_role_out(r) for r in rows], "total": len(rows)}


@router.post("/roles", status_code=201, summary="Create a role")
def create_role(body: RoleIn, user: dict = Depends(deps.require("rbac:write")),
                request: Request = None):
    if db.q1("SELECT id FROM roles WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Role code already exists")
    rid = db.insert("roles", {"code": body.code, "name": body.name,
                              "description": body.description,
                              "permission_ids": body.permission_ids,
                              "builtin": 0, "mfa_required": int(body.mfa_required),
                              "created_at": db.now()})
    deps.audit(user["username"], "rbac.role.create", f"role:{body.code}", body.model_dump(), request=request)
    return _role_out(db.q1("SELECT * FROM roles WHERE id=?", (rid,)))


@router.put("/roles/{role_id}", summary="Update a role")
def update_role(role_id: int, body: RolePatch,
                user: dict = Depends(deps.require("rbac:write")), request: Request = None):
    row = db.q1("SELECT * FROM roles WHERE id=?", (role_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Role not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "mfa_required" in patch:
        patch["mfa_required"] = int(patch["mfa_required"])
    db.update("roles", role_id, patch)
    deps.audit(user["username"], "rbac.role.update", f"role:{row['code']}", patch, request=request)
    return _role_out(db.q1("SELECT * FROM roles WHERE id=?", (role_id,)))


@router.delete("/roles/{role_id}", summary="Delete a custom role")
def delete_role(role_id: int, user: dict = Depends(deps.require("rbac:write")),
                request: Request = None):
    row = db.q1("SELECT * FROM roles WHERE id=?", (role_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Role not found")
    if row["builtin"] or row["code"] == "admin":
        raise HTTPException(status_code=400, detail="Built-in roles cannot be deleted")
    for u in db.q("SELECT id,role_ids FROM users"):
        ids = (db.loads(u, "role_ids") or {}).get("role_ids") or []
        if role_id in ids:
            db.update("users", u["id"], {"role_ids": [i for i in ids if i != role_id]})
    db.delete("roles", role_id)
    deps.audit(user["username"], "rbac.role.delete", f"role:{row['code']}", {}, request=request)
    return {"ok": True}


@router.get("/users", summary="List users")
def list_users(_user: dict = Depends(deps.require("rbac:read"))):
    rows = db.q("SELECT * FROM users ORDER BY id")
    return {"users": [_user_out(r) for r in rows], "total": len(rows)}


@router.post("/users", status_code=201, summary="Create a user")
def create_user(body: UserIn, user: dict = Depends(deps.require("rbac:write")),
                request: Request = None):
    if db.q1("SELECT id FROM users WHERE username=?", (body.username,)):
        raise HTTPException(status_code=409, detail="Username already exists")
    uid = db.insert("users", {
        "username": body.username, "email": body.email, "display_name": body.display_name or body.username,
        "password_hash": security.hash_password(body.password or "demo1234"),
        "status": body.status, "dept": body.dept, "tags": body.tags,
        "role_ids": body.role_ids,
        "provider": "local", "created_at": db.now(), "updated_at": db.now()})
    deps.audit(user["username"], "rbac.user.create", f"user:{body.username}",
               {"role_ids": body.role_ids}, request=request)
    return _user_out(db.q1("SELECT * FROM users WHERE id=?", (uid,)))


@router.put("/users/{user_id}", summary="Update a user")
def update_user(user_id: int, body: UserPatch,
                user: dict = Depends(deps.require("rbac:write")), request: Request = None):
    row = db.q1("SELECT * FROM users WHERE id=?", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "password" in patch:
        patch["password_hash"] = security.hash_password(patch.pop("password"))
    patch["updated_at"] = db.now()
    db.update("users", user_id, patch)
    deps.audit(user["username"], "rbac.user.update", f"user:{row['username']}",
               {k: v for k, v in patch.items() if k != "password_hash"}, request=request)
    return _user_out(db.q1("SELECT * FROM users WHERE id=?", (user_id,)))


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetPasswordIn,
                   user: dict = Depends(deps.require("rbac:write")), request: Request = None):
    row = db.q1("SELECT username FROM users WHERE id=?", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    db.update("users", user_id, {"password_hash": security.hash_password(body.password),
                                 "updated_at": db.now()})
    deps.audit(user["username"], "rbac.user.reset_password", f"user:{row['username']}",
               {}, request=request)
    return {"ok": True}


@router.delete("/users/{user_id}", summary="Delete a user")
def delete_user(user_id: int, user: dict = Depends(deps.require("rbac:write")),
                request: Request = None):
    row = db.q1("SELECT * FROM users WHERE id=?", (user_id,))
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if row["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if row["username"] == "admin":
        raise HTTPException(status_code=400, detail="The bootstrap administrator cannot be deleted")
    db.delete("users", user_id)
    deps.audit(user["username"], "rbac.user.delete", f"user:{row['username']}", {}, request=request)
    return {"ok": True}


class GroupIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    name: str
    description: str | None = None
    members: list[str] = []
    tags: list[str] = []
    enabled: bool = True


class GroupPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    members: list[str] | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


def _group_out(row: dict) -> dict:
    out = db.loads(row, "members", "tags") or {}
    out["enabled"] = bool(out.get("enabled"))
    out["member_count"] = len(out.get("members") or [])
    return out


@router.get("/groups", summary="List member groups (used by the groups approver rule)")
def list_groups(_user: dict = Depends(deps.require("rbac:read"))):
    rows = db.q("SELECT * FROM user_groups ORDER BY id")
    return {"groups": [_group_out(r) for r in rows], "total": len(rows)}


@router.post("/groups", status_code=201, summary="Create a member group")
def create_group(body: GroupIn, user: dict = Depends(deps.require("rbac:write")),
                 request: Request = None):
    if db.q1("SELECT id FROM user_groups WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Group code already exists")
    gid = db.insert("user_groups", {
        "code": body.code, "name": body.name, "description": body.description,
        "members": body.members, "tags": body.tags, "enabled": int(body.enabled),
        "created_by": user["username"], "created_at": db.now()})
    deps.audit(user["username"], "rbac.group.create", f"group:{body.code}",
               {"members": body.members}, request=request)
    return _group_out(db.q1("SELECT * FROM user_groups WHERE id=?", (gid,)))


@router.put("/groups/{group_id}", summary="Update a member group")
def update_group(group_id: int, body: GroupPatch,
                 user: dict = Depends(deps.require("rbac:write")), request: Request = None):
    row = db.q1("SELECT * FROM user_groups WHERE id=?", (group_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Group not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "enabled" in patch:
        patch["enabled"] = int(patch["enabled"])
    db.update("user_groups", group_id, patch)
    deps.audit(user["username"], "rbac.group.update", f"group:{row['code']}", patch,
               request=request)
    return _group_out(db.q1("SELECT * FROM user_groups WHERE id=?", (group_id,)))


@router.delete("/groups/{group_id}", summary="Delete a member group")
def delete_group(group_id: int, user: dict = Depends(deps.require("rbac:write")),
                 request: Request = None):
    row = db.q1("SELECT * FROM user_groups WHERE id=?", (group_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Group not found")
    db.delete("user_groups", group_id)
    deps.audit(user["username"], "rbac.group.delete", f"group:{row['code']}", {},
               request=request)
    return {"ok": True}


@router.post("/check", summary="Check whether a user holds a permission")
def check_permission(body: PermissionCheckIn, current: dict = Depends(deps.require("rbac:read"))):
    target = deps._load_user(body.user_id) if body.user_id else current
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": target["username"], "permission": body.permission,
            "allowed": deps.has_permission(target, body.permission)}
