"""Skill Hub management API (independent from the MCP server registry)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import deps
from ..services import skill_hubs

router = APIRouter(prefix="/skill-hubs", tags=["Skill Hubs"])


class HubIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    name: str
    description: str = ""
    kind: str = "builtin"
    url: str | None = None
    enabled: bool = True
    sync_interval_min: int = 60
    auth_config: dict = Field(default_factory=dict)


class HubPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    kind: str | None = None
    url: str | None = None
    enabled: bool | None = None
    sync_interval_min: int | None = None
    auth_config: dict | None = None


class HubInstallIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    name: str | None = None
    type: str | None = None
    endpoint: str | None = None
    command: str | None = None


def _hub_or_404(hub_id: int) -> dict:
    hub = skill_hubs.get(hub_id)
    if not hub:
        raise HTTPException(status_code=404, detail="Skill hub not found")
    return hub


@router.get("", summary="List skill hubs with statistics")
def list_hubs(_user: dict = Depends(deps.require("skill:read"))):
    return {"hubs": skill_hubs.rows(), "total": len(skill_hubs.rows()),
            "stats": skill_hubs.stats(), "kinds": skill_hubs.KINDS,
            "categories": skill_hubs.CATEGORIES}


@router.get("/search", summary="Search skills across all enabled hubs")
def search_all(q: str = "", category: str | None = None,
               _user: dict = Depends(deps.require("skill:read"))):
    return skill_hubs.search_all(q, category)


@router.get("/stats", summary="Skill hub statistics")
def hub_stats(_user: dict = Depends(deps.require("skill:read"))):
    return skill_hubs.stats()


@router.post("", status_code=201, summary="Create a skill hub")
def create_hub(body: HubIn, user: dict = Depends(deps.require("skill:write")),
               request: Request = None):
    try:
        hub = skill_hubs.create(body.model_dump(), actor=user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "skillhub.create", f"hub:{hub['code']}",
               {"kind": hub["kind"]}, request=request)
    return hub


@router.get("/{hub_id}", summary="Get one skill hub")
def get_hub(hub_id: int, _user: dict = Depends(deps.require("skill:read"))):
    return _hub_or_404(hub_id)


@router.put("/{hub_id}", summary="Update a skill hub")
def update_hub(hub_id: int, body: HubPatch,
               user: dict = Depends(deps.require("skill:write")), request: Request = None):
    _hub_or_404(hub_id)
    try:
        hub = skill_hubs.update(hub_id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "skillhub.update", f"hub:{hub['code']}", {}, request=request)
    return hub


@router.delete("/{hub_id}", summary="Delete a skill hub")
def delete_hub(hub_id: int, user: dict = Depends(deps.require("skill:write")),
               request: Request = None):
    hub = _hub_or_404(hub_id)
    skill_hubs.delete(hub_id)
    deps.audit(user["username"], "skillhub.delete", f"hub:{hub['code']}", {}, request=request)
    return {"ok": True, "code": hub["code"]}


@router.post("/{hub_id}/sync", summary="Sync a remote hub index (or refresh a builtin one)")
def sync_hub(hub_id: int, user: dict = Depends(deps.require("skill:write")),
             request: Request = None):
    _hub_or_404(hub_id)
    result = skill_hubs.sync(hub_id)
    deps.audit(user["username"], "skillhub.sync", f"hub:{hub_id}", result, request=request)
    return result


@router.get("/{hub_id}/skills", summary="Search skills inside one hub")
def search_hub(hub_id: int, q: str = "", category: str | None = None,
               _user: dict = Depends(deps.require("skill:read"))):
    _hub_or_404(hub_id)
    try:
        return skill_hubs.search_hub(hub_id, q, category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{hub_id}/skills/{code}", summary="Get one hub skill detail")
def hub_skill(hub_id: int, code: str, _user: dict = Depends(deps.require("skill:read"))):
    hub = _hub_or_404(hub_id)
    try:
        item = skill_hubs.find(hub, code)
    except skill_hubs.HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="Skill not found in hub")
    return skill_hubs._public(item)


@router.post("/{hub_id}/install", status_code=201,
             summary="Install a skill from this hub into the local registry")
def install_from_hub(hub_id: int, body: HubInstallIn,
                     user: dict = Depends(deps.require("skill:write")), request: Request = None):
    _hub_or_404(hub_id)
    try:
        result = skill_hubs.install(hub_id, body.code,
                                    body.model_dump(exclude={"code"}, exclude_none=True))
    except (ValueError, skill_hubs.HubError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "skillhub.install", f"skill:{body.code}",
               {"hub_id": hub_id, **result}, request=request)
    return result
