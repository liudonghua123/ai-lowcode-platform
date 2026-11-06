"""LLM runtime + AgentScope-compatible ReAct orchestration for query/act agents.

Three execution backends, selected by ``LLM_PROVIDER``:

* ``mock`` (default): deterministic, offline intent recognition and grounded
  answers, so every demo works without an API key.
* ``openai-compatible``: any OpenAI-compatible chat-completions endpoint.
* ``agentscope``: builds an ``agentscope.model`` chat model when credentials are
  present, otherwise transparently degrades to the backends above.

The ReAct tool loop is shared with the MCP tool registry, so an agent can really
submit forms, run workflows and query the knowledge base.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import date
from typing import Any

import httpx

from .. import db
from ..config import settings
from . import mcp_tools, rag


def _agentscope_info() -> dict:
    info = {"available": False, "version": None, "modules": []}
    try:
        import importlib

        import agentscope
        info["available"] = True
        info["version"] = getattr(agentscope, "__version__", "unknown")
        for name in ("agentscope.message", "agentscope.model", "agentscope.agent", "agentscope.tool"):
            try:
                importlib.import_module(name)
                info["modules"].append(name)
            except Exception:
                pass
    except Exception as exc:
        info["error"] = str(exc)[:120]
    return info


AGENTSCOPE_INFO = _agentscope_info()


def describe() -> dict:
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "agentscope": AGENTSCOPE_INFO,
        "agentscope_enabled": settings.agentscope_enabled and AGENTSCOPE_INFO["available"],
        "orchestration": "ReAct tool loop (AgentScope-compatible)",
        "tools": len(mcp_tools.TOOL_SPECS),
        "has_api_key": bool(settings.llm_api_key),
    }


def _is_zh(text: str) -> bool:
    return len(re.findall(r"[\u4e00-\u9fff]", text or "")) >= 2


def _demo_form_data(code: str, user: dict | None) -> dict:
    row = db.q1("SELECT * FROM forms WHERE code=?", (code,))
    if not row:
        return {"note": "AI agent demo submission"}
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    username = (user or {}).get("username") or "ai-agent"
    today = date.today().isoformat()
    data: dict[str, Any] = {}
    for f in schema:
        key, ftype = f.get("key"), f.get("type")
        if not key:
            continue
        if ftype == "select":
            data[key] = (f.get("options") or [""])[0]
        elif ftype == "date":
            data[key] = today
        elif ftype == "number":
            data[key] = (f.get("validation") or {}).get("min") or 1
        elif ftype == "switch":
            data[key] = bool(f.get("defaultValue"))
        elif ftype == "user":
            data[key] = username
        elif ftype == "textarea":
            data[key] = "Submitted via AI agent (auto-generated demo data)."
        else:
            data[key] = "AI agent demo"
    return data


def _intent_tool_calls(message: str, user: dict | None) -> list[dict]:
    m = (message or "").lower()
    calls: list[dict] = []

    def add(name: str, args: dict) -> None:
        calls.append({"id": f"call_{len(calls) + 1}_{name}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})

    if re.search(r"(run|start|trigger|执行|运行|启动).*(workflow|流程)|(workflow|流程).*(run|执行|运行)", m):
        code = "purchase_approval" if "purchase" in m or "采购" in message else "leave_approval"
        ctx = {"days": 2, "budget": 5000, "initiator": (user or {}).get("username") or "ai-agent"}
        add("run_workflow", {"code": code, "context": ctx})
    if len(calls) < 3 and re.search(r"(submit|create|申请|提交).*(form|leave|purchase|表单|请假|采购)|"
                   r"(form|表单).*(submit|提交)", m):
        code = "purchase_request" if "purchase" in m or "采购" in message else "leave_request"
        add("submit_form", {"code": code, "data": _demo_form_data(code, user)})
    if len(calls) < 3 and re.search(r"(record|submission|提交记录|数据|记录查询|query records)", m):
        add("query_records", {"limit": 10})
    if len(calls) < 3 and re.search(r"(stats|statistic|dashboard|overview|统计|概览|多少.*表单|数据概览)", m):
        add("get_stats", {})
    if len(calls) < 3 and re.search(r"(list|show|all).*(users|user)|用户列表|有哪些用户", m):
        add("list_users", {})
    if len(calls) < 3 and re.search(r"\b(list|show)\s+(all\s+|the\s+)?(forms?)\b|表单列表|有哪些表单", m):
        add("list_forms", {})
    if len(calls) < 3 and re.search(r"\b(list|show)\s+(all\s+|the\s+)?(workflows?|flows?)\b|流程列表|有哪些流程", m):
        add("list_workflows", {})
    if len(calls) < 3 and re.search(r"(search|find|查询|检索).*(knowledge|document|policy|知识|文档|制度)", m):
        add("search_knowledge", {"query": message, "top_k": 4})
    return calls


def _grounded_answer(message: str, hits: list[dict]) -> str:
    zh = _is_zh(message)
    if hits:
        lines = []
        for i, h in enumerate(hits[:3], 1):
            snippet = h["snippet"].replace("\n", " ")[:220]
            lines.append(f"[{i}] {h['title']}：{snippet}")
        body = "\n".join(lines)
        if zh:
            return (f"根据知识库检索结果，与「{message}」最相关的内容如下：\n\n{body}\n\n"
                    "以上片段来自平台知识库，可作为回答依据。如需执行操作，请直接告诉我「运行流程」或「提交表单」。")
        return (f"Based on the knowledge base, here is what I found for \"{message}\":\n\n{body}\n\n"
                "These excerpts are retrieved from the platform knowledge base. "
                "You can also ask me to run a workflow or submit a form.")
    if zh:
        return (f"关于「{message}」，当前知识库没有直接匹配的文档。我是平台 AI 助手，可以："
                "检索知识库、查询表单与流程、提交表单、运行审批流程、调用 MCP 工具以及查看平台统计。"
                "请换一种表述或指定具体任务。")
    return (f"I could not find a directly matching document for \"{message}\". "
            "I am the platform AI assistant: I can search the knowledge base, query forms and "
            "workflows, submit forms, run approval workflows, invoke MCP tools and report platform stats. "
            "Try rephrasing or give me a concrete task.")


def _summarize_tool_result(messages: list[dict], message: str) -> str:
    tool_messages = [m for m in messages if m.get("role") == "tool"]
    zh = _is_zh(message)
    parts = []
    for tm in tool_messages[-3:]:
        try:
            payload = json.loads(tm.get("content") or "{}")
        except ValueError:
            payload = {"raw": tm.get("content")}
        if "error" in payload:
            parts.append(f"• {payload['error']}")
        elif isinstance(payload.get("forms"), list):
            parts.append("• " + (f"共 {payload.get('total')} 个表单：" if zh else f"Found {payload.get('total')} forms: ") +
                         ", ".join(f"{f['code']}({f['status']})" for f in payload["forms"][:6]))
        elif isinstance(payload.get("workflows"), list):
            parts.append("• " + (f"共 {payload.get('total')} 个流程：" if zh else f"Found {payload.get('total')} workflows: ") +
                         ", ".join(f"{w['code']}({w['status']})" for w in payload["workflows"][:6]))
        elif "form_submissions" in payload:
            parts.append("• " + (f"平台统计：{payload.get('forms')} 个表单、{payload.get('workflows')} 个流程、"
                                 f"{payload.get('form_submissions')} 条提交、{payload.get('users')} 位用户"
                                 if zh else
                                 f"Platform stats: {payload.get('forms')} forms, {payload.get('workflows')} workflows, "
                                 f"{payload.get('form_submissions')} submissions, {payload.get('users')} users"))
        elif "records" in payload:
            parts.append("• " + (f"查询到 {payload.get('count')} 条记录" if zh else f"Retrieved {payload.get('count')} records"))
        elif "hits" in payload:
            parts.append("• " + (f"命中 {payload.get('count')} 篇知识文档" if zh else f"Matched {payload.get('count')} documents") +
                         ": " + ", ".join(h["title"] for h in payload["hits"][:3]))
        elif "instance_id" in payload:
            parts.append("• " + (f"流程实例 #{payload['instance_id']} 状态 {payload.get('status')}，"
                                 f"执行 {payload.get('steps')} 步" if zh else
                                 f"Workflow instance #{payload['instance_id']} is {payload.get('status')} "
                                 f"after {payload.get('steps')} steps"))
        elif "submission_id" in payload:
            parts.append("• " + (f"表单提交成功，记录 #{payload['submission_id']}" if zh else
                                 f"Form submitted, record #{payload['submission_id']}"))
        elif isinstance(payload.get("users"), list):
            parts.append("• " + (f"共 {payload.get('total')} 位用户" if zh else f"{payload.get('total')} users"))
        else:
            keys = ", ".join(list(payload.keys())[:6])
            parts.append("• " + (f"工具返回字段：{keys}" if zh else f"Tool returned fields: {keys}"))
    body = "\n".join(parts)
    if zh:
        return f"已通过工具完成你的请求，执行结果如下：\n\n{body}\n\n以上操作均由平台工具实时执行。"
    return f"Done — here are the live tool results:\n\n{body}\n\nAll actions were executed by platform tools in real time."


def _mock_chat(messages: list[dict], tools: list[dict] | None) -> dict:
    last = messages[-1] if messages else {}
    if last.get("role") == "tool":
        user_msg = next((m["content"] for m in reversed(messages)
                         if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        return {"role": "assistant", "content": _summarize_tool_result(messages, user_msg),
                "tool_calls": None}
    user_msg = str(last.get("content") or "")
    system = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
    if tools:
        calls = _intent_tool_calls(user_msg, mcp_tools.current_user())
        if calls:
            return {"role": "assistant", "content": "", "tool_calls": calls}
    hits = []
    match = re.search(r"\[Knowledge Context\]\s*(.*)", system, re.S)
    if match and "No relevant knowledge" not in match.group(1):
        hits = [{"title": t, "snippet": ""} for t in re.findall(r"^\[\d+\] (.+?) \(", match.group(1), re.M)]
        for h in hits:
            title = h["title"]
            pos = match.group(1).find(title)
            h["snippet"] = match.group(1)[pos + len(title):pos + len(title) + 230].strip(" )\n")
    return {"role": "assistant", "content": _grounded_answer(user_msg, hits), "tool_calls": None}


async def _http_chat(messages: list[dict], tools: list[dict] | None,
                     temperature: float | None) -> dict:
    payload: dict[str, Any] = {
        "model": settings.llm_model, "messages": messages,
        "temperature": settings.llm_temperature if temperature is None else temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions", json=payload,
            headers={"Authorization": f"Bearer {settings.llm_api_key}",
                     "Content-Type": "application/json"})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        return {"role": "assistant", "content": msg.get("content") or "",
                "tool_calls": msg.get("tool_calls")}


async def _agentscope_chat(messages: list[dict], tools: list[dict] | None,
                           temperature: float | None) -> dict:
    """Use an agentscope.model chat model when the installed version supports it."""
    from agentscope.model import OpenAIChatModel  # type: ignore
    sig = inspect.signature(OpenAIChatModel.__init__)
    candidates = {
        "model_name": settings.llm_model,
        "api_key": settings.llm_api_key,
        "base_url": settings.llm_base_url,
        "stream": False,
        "temperature": settings.llm_temperature if temperature is None else temperature,
    }
    kwargs = {k: v for k, v in candidates.items() if k in sig.parameters}
    model = OpenAIChatModel(**kwargs)
    call_kwargs: dict[str, Any] = {"messages": messages}
    if tools and "tools" in inspect.signature(model.__call__).parameters:
        call_kwargs["tools"] = tools
    response = await model(**call_kwargs)
    content = getattr(response, "content", None)
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text += str(block.get("text", ""))
            elif hasattr(block, "text"):
                text += str(getattr(block, "text", ""))
    if not text:
        raise ValueError("AgentScope model returned no text content")
    return {"role": "assistant", "content": text, "tool_calls": None}


async def chat(messages: list[dict], tools: list[dict] | None = None,
               temperature: float | None = None) -> dict:
    provider = settings.llm_provider
    if provider == "agentscope" and settings.agentscope_enabled and settings.llm_api_key:
        try:
            result = await _agentscope_chat(messages, tools, temperature)
            result["provider"] = "agentscope"
            return result
        except Exception:
            pass
    if provider in {"openai-compatible", "openai", "agentscope"} and settings.llm_api_key:
        try:
            result = await _http_chat(messages, tools, temperature)
            result["provider"] = "openai-compatible"
            return result
        except Exception:
            pass
    result = _mock_chat(messages, tools)
    result["provider"] = "mock"
    return result


async def run_agent(agent: dict, message: str, history: list[dict] | None = None,
                    user: dict | None = None, max_rounds: int = 5) -> dict:
    """Retrieve knowledge, then run a ReAct loop with the agent's allowed tools."""
    kb_ids = agent.get("kb_ids") or []
    hits = rag.search(message, kb_ids or None, top_k=settings.rag_top_k)
    context = rag.build_context(hits)
    allow_actions = agent.get("mode") in {"act", "hybrid"}
    tools = mcp_tools.list_tools("openai") if allow_actions else None
    tool_names = ", ".join(t["name"] for t in mcp_tools.TOOL_SPECS)
    system = (
        f"{agent.get('system_prompt') or 'You are a helpful platform assistant.'}\n\n"
        f"[Agent] name={agent.get('name')} mode={agent.get('mode')} model={agent.get('model') or settings.llm_model}\n"
        f"[Available tools] {tool_names}\n"
        "[Rules] Use tools for live platform data and actions. Never invent tool results. "
        "Answer in the same language as the user. Cite knowledge sources when used.\n\n"
        f"[Knowledge Context]\n{context}"
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in (history or [])[-6:]:
        if h.get("role") in {"user", "assistant"} and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    steps: list[dict] = []
    answer = ""
    provider_used = "mock"
    for _ in range(max_rounds):
        resp = await chat(messages, tools=tools, temperature=agent.get("temperature"))
        provider_used = resp.get("provider", provider_used)
        calls = resp.get("tool_calls") or []
        if not calls:
            answer = resp.get("content") or ""
            break
        messages.append({"role": "assistant", "content": resp.get("content") or "",
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            try:
                result = mcp_tools.call_tool(name, args, user)
            except Exception as exc:
                result = {"error": str(exc)}
            steps.append({"tool": name, "arguments": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.get("id") or name,
                             "content": json.dumps(result, ensure_ascii=False)})
    if not answer:
        answer = _summarize_tool_result(messages, message)
    return {
        "answer": answer, "steps": steps,
        "sources": [{"doc_id": h["doc_id"], "title": h["title"], "score": h["score"]} for h in hits],
        "model": agent.get("model") or settings.llm_model,
        "provider": provider_used,
        "orchestration": "ReAct tool loop (AgentScope-compatible)",
    }
