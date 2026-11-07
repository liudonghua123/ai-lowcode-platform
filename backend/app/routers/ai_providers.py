"""Runtime configuration for all AI model services (LLM / ASR / TTS / Embedding / Rerank / Vision).

API keys are write-only: list/get responses expose only a masked hint. A
``default`` flag per category decides which configuration the runtime uses.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import deps
from ..services import model_providers

router = APIRouter(prefix="/ai/providers", tags=["AI Model Providers"])

_CODE_PATTERN = r"^[a-z][a-z0-9_-]{1,49}$"


class ProviderIn(BaseModel):
    code: str = Field(..., pattern=_CODE_PATTERN)
    name: str
    category: str
    vendor: str = "custom"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = True
    is_default: bool = False
    config: dict = Field(default_factory=dict)
    description: str = ""


class ProviderPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    vendor: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    config: dict | None = None
    description: str | None = None


class TestIn(BaseModel):
    live: bool = False


def _provider(provider_id: int) -> dict:
    row = model_providers.get(provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="AI provider not found")
    return row


@router.get("", summary="List AI model service configurations")
def list_providers(category: str | None = None, enabled_only: bool = False,
                   _user: dict = Depends(deps.require("mcp:read"))):
    rows = model_providers.rows(category, enabled_only)
    return {"providers": rows, "total": len(rows),
            "categories": list(model_providers.CATEGORY_CODES)}


@router.get("/meta", summary="Category / vendor metadata and effective runtime config")
def meta(_user: dict = Depends(deps.require("mcp:read"))):
    return model_providers.meta()


@router.post("", status_code=201, summary="Create an AI model service configuration")
def create_provider(body: ProviderIn, user: dict = Depends(deps.require("settings:write")),
                    request: Request = None):
    try:
        row = model_providers.create(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "ai.provider.create", f"provider:{row['code']}",
               {"category": row["category"]}, request=request)
    return row


@router.get("/{provider_id}", summary="Get one AI model service configuration")
def get_provider(provider_id: int, _user: dict = Depends(deps.require("mcp:read"))):
    return _provider(provider_id)


@router.put("/{provider_id}", summary="Update an AI model service configuration")
def update_provider(provider_id: int, body: ProviderPatch,
                    user: dict = Depends(deps.require("settings:write")), request: Request = None):
    row = _provider(provider_id)
    try:
        updated = model_providers.update(provider_id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "ai.provider.update", f"provider:{row['code']}",
               {"fields": list(body.model_dump(exclude_none=True))}, request=request)
    return updated


@router.delete("/{provider_id}", summary="Delete an AI model service configuration")
def delete_provider(provider_id: int, user: dict = Depends(deps.require("settings:write")),
                    request: Request = None):
    row = _provider(provider_id)
    model_providers.delete(provider_id)
    deps.audit(user["username"], "ai.provider.delete", f"provider:{row['code']}", {},
               request=request)
    return {"ok": True}


@router.post("/{provider_id}/default", summary="Set a configuration as the default for its category")
def set_default(provider_id: int, user: dict = Depends(deps.require("settings:write")),
                request: Request = None):
    row = _provider(provider_id)
    try:
        updated = model_providers.set_default(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "ai.provider.default", f"provider:{row['code']}",
               {"category": row["category"]}, request=request)
    return updated


@router.post("/{provider_id}/test", summary="Validate / probe an AI model service configuration")
def test_provider(provider_id: int, body: TestIn | None = None,
                  user: dict = Depends(deps.require("mcp:read")),
                  request: Request = None):
    row = _provider(provider_id)
    live = bool(body and body.live)
    try:
        result = model_providers.test(provider_id, live=live)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    deps.audit(user["username"], "ai.provider.test", f"provider:{row['code']}",
               {"ok": result["ok"], "live": live}, request=request)
    return result
