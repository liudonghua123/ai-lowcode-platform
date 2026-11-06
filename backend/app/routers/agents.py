"""AI agents: query / act / hybrid, AgentScope runtime and conversations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..config import settings
from ..services import llm, mcp_tools

router = APIRouter(prefix="/agents", tags=["AI Agents"])

AGENT_MODES = ["query", "act", "hybrid"]


class AgentIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str
    description: str | None = None
    mode: str = "hybrid"
    model: str | None = None
    system_prompt: str | None = None
    temperature: float = 0.3
    kb_ids: list[int] = Field(default_factory=list)
    skill_ids: list[int] = Field(default_factory=list)
    workflow_ids: list[int] = Field(default_factory=list)
    status: str = "active"


class AgentPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    mode: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    kb_ids: list[int] | None = None
    skill_ids: list[int] | None = None
    workflow_ids: list[int] | None = None
    status: str | None = None


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: int | None = None
    context: dict | None = None


def _out(row: dict) -> dict:
    return db.loads(row, "kb_ids", "skill_ids", "workflow_ids") or {}


@router.get("/meta/runtime", summary="LLM / AgentScope runtime information")
def runtime(_user: dict = Depends(deps.require("agent:read"))):
    return {"runtime": llm.describe(), "tools": mcp_tools.list_tools(),
            "modes": AGENT_MODES, "models": [settings.llm_model]}


@router.get("", summary="List agents")
def list_agents(_user: dict = Depends(deps.require("agent:read"))):
    rows = db.q("SELECT * FROM agents ORDER BY id")
    return {"agents": [_out(r) for r in rows], "total": len(rows)}


@router.post("", status_code=201, summary="Create an agent")
def create_agent(body: AgentIn, user: dict = Depends(deps.require("agent:write")),
                 request: Request = None):
    if body.mode not in AGENT_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {AGENT_MODES}")
    if db.q1("SELECT id FROM agents WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Agent code already exists")
    aid = db.insert("agents", {**body.model_dump(), "created_by": user["username"],
                               "created_at": db.now(), "updated_at": db.now()})
    deps.audit(user["username"], "agent.create", f"agent:{body.code}", {"mode": body.mode}, request=request)
    return _out(db.q1("SELECT * FROM agents WHERE id=?", (aid,)))


@router.get("/conversations/{conversation_id}", summary="Get a conversation")
def get_conversation(conversation_id: int, user: dict = Depends(deps.require("agent:chat"))):
    row = db.q1("SELECT * FROM conversations WHERE id=?", (conversation_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    out = db.loads(row, "messages") or {}
    if out.get("user_id") not in (user["username"], None) and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Not your conversation")
    return out


@router.delete("/conversations/{conversation_id}", summary="Delete a conversation")
def delete_conversation(conversation_id: int, user: dict = Depends(deps.require("agent:chat"))):
    row = db.q1("SELECT user_id FROM conversations WHERE id=?", (conversation_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if row["user_id"] not in (user["username"], None) and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Not your conversation")
    db.delete("conversations", conversation_id)
    return {"ok": True}


@router.get("/{agent_id}", summary="Get an agent")
def get_agent(agent_id: int, _user: dict = Depends(deps.require("agent:read"))):
    row = db.q1("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _out(row)


@router.put("/{agent_id}", summary="Update an agent")
def update_agent(agent_id: int, body: AgentPatch,
                 user: dict = Depends(deps.require("agent:write")), request: Request = None):
    row = db.q1("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    patch = body.model_dump(exclude_none=True)
    if patch.get("mode") and patch["mode"] not in AGENT_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {AGENT_MODES}")
    patch["updated_at"] = db.now()
    db.update("agents", agent_id, patch)
    deps.audit(user["username"], "agent.update", f"agent:{row['code']}", patch, request=request)
    return _out(db.q1("SELECT * FROM agents WHERE id=?", (agent_id,)))


@router.delete("/{agent_id}", summary="Delete an agent")
def delete_agent(agent_id: int, user: dict = Depends(deps.require("agent:write")),
                 request: Request = None):
    row = db.q1("SELECT code FROM agents WHERE id=?", (agent_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.run("DELETE FROM conversations WHERE agent_id=?", (agent_id,))
    db.delete("agents", agent_id)
    deps.audit(user["username"], "agent.delete", f"agent:{row['code']}", {}, request=request)
    return {"ok": True}


@router.get("/{agent_id}/conversations", summary="List conversations of an agent")
def list_conversations(agent_id: int, user: dict = Depends(deps.require("agent:chat"))):
    rows = db.q("SELECT * FROM conversations WHERE agent_id=? AND (user_id=? OR user_id IS NULL) "
                "ORDER BY id DESC", (agent_id, user["username"]))
    return {"conversations": [db.loads(r, "messages") for r in rows], "total": len(rows)}


@router.post("/{agent_id}/chat", summary="Chat with a query / act agent (ReAct tool loop)")
async def chat(agent_id: int, body: ChatIn, user: dict = Depends(deps.require("agent:chat")),
               request: Request = None):
    row = db.q1("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = _out(row)
    if agent.get("status") != "active":
        raise HTTPException(status_code=400, detail="Agent is inactive")
    history: list[dict] = []
    conversation_id = body.conversation_id
    if conversation_id:
        conv = db.q1("SELECT * FROM conversations WHERE id=?", (conversation_id,))
        if conv and (conv.get("user_id") in (user["username"], None) or user["is_admin"]):
            history = (db.loads(conv, "messages") or {}).get("messages") or []
    mcp_tools.bind_user(user)
    result = await llm.run_agent(agent, body.message, history, user)
    messages = history + [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": result["answer"]},
    ]
    if conversation_id and db.q1("SELECT id FROM conversations WHERE id=?", (conversation_id,)):
        db.update("conversations", conversation_id, {"messages": messages})
    else:
        conversation_id = db.insert("conversations", {
            "agent_id": agent_id, "title": body.message[:60], "messages": messages,
            "user_id": user["username"], "created_at": db.now()})
    deps.audit(user["username"], "agent.chat", f"agent:{agent['code']}",
               {"steps": len(result["steps"]), "provider": result["provider"]}, request=request)
    return {**result, "conversation_id": conversation_id, "agent": agent["code"]}
