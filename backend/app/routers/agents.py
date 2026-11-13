"""AI agents: query / act / hybrid, AgentScope runtime and conversations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps
from ..config import settings
from ..services import agent_intents, llm, mcp_servers, mcp_tools, model_providers, skill_catalog

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
    server_ids: list[int] = Field(default_factory=list)
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
    server_ids: list[int] | None = None
    workflow_ids: list[int] | None = None
    status: str | None = None


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: int | None = None
    context: dict | None = None


class ActionIn(BaseModel):
    kind: str
    code: str
    data: dict = Field(default_factory=dict)
    conversation_id: int | None = None


class ConversationIn(BaseModel):
    """An empty conversation can be started before the first message is sent."""
    title: str | None = None


def _out(row: dict) -> dict:
    return db.loads(row, "kb_ids", "skill_ids", "server_ids", "workflow_ids") or {}


def _conv_out(row: dict | None) -> dict:
    return db.loads(row, "messages") or {}


def _owns_conversation(conv: dict, user: dict) -> bool:
    return conv.get("user_id") in (user["username"], None) or bool(user.get("is_admin"))


def _conv_visible_sql(user: dict) -> tuple[str, tuple]:
    """Admins see every conversation; other users only their own + shared ones."""
    if user.get("is_admin"):
        return "agent_id=?", ()
    return "agent_id=? AND (user_id=? OR user_id IS NULL)", (user["username"],)


@router.get("/meta/runtime", summary="LLM runtime, permission-filtered tools and capability matrix")
def runtime(user: dict = Depends(deps.require("agent:read"))):
    return {"runtime": llm.describe(),
            "tools": mcp_tools.list_tools("catalog", user=user),
            "capabilities": mcp_tools.capability_matrix(user),
            "modes": AGENT_MODES, "models": [settings.llm_model],
            "model_providers": model_providers.meta()}


@router.get("/meta/bindings", summary="All bindable resources for agent configuration")
def bindings(_user: dict = Depends(deps.require("agent:read"))):
    """One request gives the Agent editor everything it needs to bind resources."""
    servers = [{"id": s["id"], "code": s["code"], "name": s["name"],
                "transport": s["transport"], "enabled": s["enabled"],
                "health": s["health"], "tool_count": s["tool_count"]}
               for s in mcp_servers.rows()]
    skills = [{"id": r["id"], "code": r["code"], "name": r["name"],
               "status": r["status"], "enabled": bool(r["enabled"]),
               "server_id": r["server_id"], "tool_count": len(
                   (db.loads(r, "tools") or {}).get("tools") or [])}
              for r in db.q("SELECT * FROM mcp_skills ORDER BY id")]
    collections = [{"id": r["id"], "code": r["code"], "name": r["name"],
                    "document_count": r["document_count"]} for r in db.q(
                        "SELECT c.*, (SELECT COUNT(*) FROM kb_documents d "
                        "WHERE d.collection_id=c.id) AS document_count "
                        "FROM kb_collections c ORDER BY c.id")]
    workflows = [{"id": r["id"], "code": r["code"], "name": r["name"],
                  "status": r["status"]} for r in db.q(
                      "SELECT id,code,name,status FROM workflows ORDER BY id")]
    models = [{"id": p["id"], "code": p["code"], "name": p["name"],
               "model": p["model"], "category": p["category"],
               "is_default": p["is_default"], "enabled": p["enabled"]}
              for p in model_providers.rows("llm")]
    return {"servers": servers, "skills": skills, "collections": collections,
            "workflows": workflows, "models": models, "modes": AGENT_MODES,
            "catalog_count": len(skill_catalog.CATALOG_SPECS),
            "counts": {k: len(v) for k, v in {
                "servers": servers, "skills": skills, "collections": collections,
                "workflows": workflows, "models": models}.items()}}


@router.get("", summary="List agents")
def list_agents(_user: dict = Depends(deps.require("agent:read"))):
    rows = db.q("SELECT * FROM agents ORDER BY id")
    return {"agents": [_out(r) for r in rows], "total": len(rows)}


_ID_TABLES = {"kb_ids": "kb_collections", "skill_ids": "mcp_skills",
              "server_ids": "mcp_servers", "workflow_ids": "workflows"}


def _clean_ids(data: dict) -> dict:
    """Drop ids that no longer exist, so a stale binding cannot break an agent."""
    for field, table in _ID_TABLES.items():
        values = data.get(field)
        if not values:
            continue
        marks = ",".join("?" for _ in values)
        found = {r["id"] for r in db.q(
            f"SELECT id FROM {table} WHERE id IN ({marks})", tuple(values))}
        data[field] = [int(v) for v in values if int(v) in found]
    return data


@router.post("", status_code=201, summary="Create an agent")
def create_agent(body: AgentIn, user: dict = Depends(deps.require("agent:write")),
                 request: Request = None):
    if body.mode not in AGENT_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {AGENT_MODES}")
    if db.q1("SELECT id FROM agents WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Agent code already exists")
    payload = _clean_ids(body.model_dump())
    aid = db.insert("agents", {**payload, "created_by": user["username"],
                               "created_at": db.now(), "updated_at": db.now()})
    deps.audit(user["username"], "agent.create", f"agent:{body.code}",
               {"mode": body.mode, "server_ids": payload.get("server_ids")}, request=request)
    return _out(db.q1("SELECT * FROM agents WHERE id=?", (aid,)))


@router.get("/conversations/{conversation_id}", summary="Get a conversation")
def get_conversation(conversation_id: int, user: dict = Depends(deps.require("agent:chat"))):
    row = db.q1("SELECT * FROM conversations WHERE id=?", (conversation_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    out = _conv_out(row)
    if not _owns_conversation(out, user):
        raise HTTPException(status_code=403, detail="Not your conversation")
    return out


@router.delete("/conversations/{conversation_id}", summary="Delete a conversation")
def delete_conversation(conversation_id: int, user: dict = Depends(deps.require("agent:chat")),
                        request: Request = None):
    row = db.q1("SELECT user_id FROM conversations WHERE id=?", (conversation_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not _owns_conversation(row, user):
        raise HTTPException(status_code=403, detail="Not your conversation")
    db.delete("conversations", conversation_id)
    deps.audit(user["username"], "agent.conversation.delete", f"conversation:{conversation_id}",
               {}, request=request)
    return {"ok": True, "deleted": 1}


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
    patch = _clean_ids(body.model_dump(exclude_none=True))
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
    where, extra = _conv_visible_sql(user)
    rows = db.q(f"SELECT * FROM conversations WHERE {where} ORDER BY id DESC",
                (agent_id,) + extra)
    return {"conversations": [_conv_out(r) for r in rows], "total": len(rows)}


@router.post("/{agent_id}/conversations", status_code=201,
             summary="Start a new empty conversation for an agent")
def create_conversation(agent_id: int, body: ConversationIn,
                        user: dict = Depends(deps.require("agent:chat")),
                        request: Request = None):
    """Persist an empty session so it appears in the agent's history group immediately."""
    row = db.q1("SELECT id FROM agents WHERE id=?", (agent_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    cid = db.insert("conversations", {
        "agent_id": agent_id, "title": (body.title or "").strip()[:80],
        "messages": [], "user_id": user["username"], "created_at": db.now()})
    deps.audit(user["username"], "agent.conversation.create", f"agent:{agent_id}",
               {"conversation_id": cid}, request=request)
    return {"conversation": _conv_out(db.q1("SELECT * FROM conversations WHERE id=?", (cid,)))}


@router.delete("/{agent_id}/conversations",
               summary="Delete all conversations belonging to an agent")
def clear_conversations(agent_id: int, user: dict = Depends(deps.require("agent:chat")),
                        request: Request = None):
    """Clear an agent's whole history group without deleting the agent itself."""
    if not db.q1("SELECT id FROM agents WHERE id=?", (agent_id,)):
        raise HTTPException(status_code=404, detail="Agent not found")
    where, extra = _conv_visible_sql(user)
    cur = db.run(f"DELETE FROM conversations WHERE {where}", (agent_id,) + extra)
    deps.audit(user["username"], "agent.conversation.clear", f"agent:{agent_id}",
               {"deleted": cur.rowcount}, request=request)
    return {"ok": True, "deleted": cur.rowcount}


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
    conv = db.q1("SELECT * FROM conversations WHERE id=?", (conversation_id,)) if conversation_id else None
    if conv and _owns_conversation(conv, user):
        history = _conv_out(conv).get("messages") or []
    else:
        conv = None  # never append to a conversation owned by somebody else
    mcp_tools.bind_user(user)
    mcp_tools.bind_context(source="agent", transport="react", method="agent.tool",
                           actor=user["username"], request_id=db.uid()[:12])
    decision = agent_intents.plan(body.message, user, body.context)
    model = agent.get("model") or settings.llm_model
    if decision["mode"] == "collect":
        # No side effects yet: the chat UI renders a dynamic form from the
        # request schema and calls /actions once the user submits it.
        result = {
            "answer": decision["answer"], "steps": [], "sources": [], "model": model,
            "provider": "intent", "tools_available": len(mcp_tools.agent_tools(agent, "openai") or []),
            "bound_servers": agent.get("server_ids") or [],
            "orchestration": "intent + schema-driven dynamic form",
            "action_request": decision["action_request"],
        }
    elif decision["mode"] == "tool":
        try:
            tool_result = mcp_tools.call_tool(decision["tool"], decision["args"], user)
        except Exception as exc:
            tool_result = {"error": str(exc)}
        result = {
            "answer": agent_intents.summarize_direct(decision["tool"], tool_result, body.message),
            "steps": [{"tool": decision["tool"], "arguments": decision["args"],
                       "result": tool_result}],
            "sources": [], "model": model, "provider": "scoped-tool",
            "tools_available": len(mcp_tools.agent_tools(agent, "openai") or []),
            "bound_servers": agent.get("server_ids") or [],
            "orchestration": "scoped self-service tool",
        }
    else:
        result = await llm.run_agent(agent, body.message, history, user)
    messages = history + [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": result["answer"]},
    ]
    if conv:
        # An explicitly created empty session gets its title from the first message.
        patch = {"messages": messages}
        if not (conv.get("title") or "").strip():
            patch["title"] = body.message[:60]
        db.update("conversations", conversation_id, patch)
    else:
        conversation_id = db.insert("conversations", {
            "agent_id": agent_id, "title": body.message[:60], "messages": messages,
            "user_id": user["username"], "created_at": db.now()})
    deps.audit(user["username"], "agent.chat", f"agent:{agent['code']}",
               {"steps": len(result["steps"]), "provider": result["provider"],
                "intent": decision["mode"]}, request=request)
    return {**result, "conversation_id": conversation_id, "agent": agent["code"]}


@router.post("/{agent_id}/actions",
             summary="Execute an action collected by a schema-driven dynamic form")
def agent_action(agent_id: int, body: ActionIn,
                 user: dict = Depends(deps.require("agent:chat")), request: Request = None):
    row = db.q1("SELECT * FROM agents WHERE id=?", (agent_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = _out(row)
    if agent.get("status") != "active":
        raise HTTPException(status_code=400, detail="Agent is inactive")
    mcp_tools.bind_user(user)
    mcp_tools.bind_context(source="agent", transport="action", method="agent.action",
                           actor=user["username"], request_id=db.uid()[:12])
    try:
        result = agent_intents.execute(body.kind, body.code, body.data, user, agent)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cid = body.conversation_id
    entry = [{"role": "user", "content": f"[dynamic form submitted] {body.code}"},
             {"role": "assistant", "content": result["answer"]}]
    if cid and db.q1("SELECT id FROM conversations WHERE id=?", (cid,)):
        conv = db.q1("SELECT * FROM conversations WHERE id=?", (cid,))
        if conv.get("user_id") in (user["username"], None) or user["is_admin"]:
            history = (db.loads(conv, "messages") or {}).get("messages") or []
            db.update("conversations", cid, {"messages": history + entry})
    else:
        cid = db.insert("conversations", {
            "agent_id": agent_id, "title": f"[form] {body.code}", "messages": entry,
            "user_id": user["username"], "created_at": db.now()})
    deps.audit(user["username"], "agent.action", f"agent:{agent['code']}",
               {"kind": body.kind, "code": body.code, "ok": result["ok"]}, request=request)
    return {**result, "conversation_id": cid, "agent": agent["code"]}
