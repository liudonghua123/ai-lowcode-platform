"""End-to-end smoke test for the AI Low-Code Platform API.

Run from backend/:  uv run python tests/smoke.py
Requires the app dependencies; no external services or API keys are needed.
"""
from __future__ import annotations

import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import model_providers  # noqa: E402

PASSED = 0
FAILED = 0


def check(label: str, condition: bool, extra: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label} {extra}")


def main() -> int:
    suffix = uuid.uuid4().hex[:6]
    mh = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app) as c:
        print("\n== Platform / Auth ==")
        health = c.get("/api/v1/meta/health")
        check("health", health.status_code == 200 and health.json()["status"] == "ok")
        check("MCP transport is fastmcp", health.json()["mcp"]["mode"] == "fastmcp")

        login = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        check("admin login", login.status_code == 200 and "access_token" in login.json())
        token = login.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        me = c.get("/api/v1/auth/me", headers=h)
        check("current user + RBAC", me.status_code == 200 and "*" in me.json()["permissions"])
        boot = c.get("/api/v1/meta/bootstrap", headers=h)
        check("bootstrap catalogs", boot.status_code == 200 and len(boot.json()["rbac"]["permissions"]) > 20)
        stats = c.get("/api/v1/meta/stats", headers=h)
        check("dashboard stats", stats.status_code == 200 and stats.json()["forms"] >= 3)
        check("SPA served", c.get("/").status_code == 200)
        check("API 404 is JSON", c.get("/api/v1/nope", headers=h).headers.get("content-type", "").startswith("application/json"))

        print("\n== Forms ==")
        code = f"smoke_form_{suffix}"
        created = c.post("/api/v1/forms", headers=h, json={
            "code": code, "name": "Smoke Form", "status": "draft",
            "schema": [{"id": "f1", "key": "title", "type": "text", "label": "Title", "required": True, "width": 100}],
            "layout": {"columns": 2}})
        check("create form", created.status_code == 201, str(created.json() if created.status_code != 201 else ""))
        fid = created.json().get("id", 0)
        published = c.put(f"/api/v1/forms/{fid}", headers=h, json={"status": "published"})
        check("publish form", published.status_code == 200 and published.json()["status"] == "published")
        bad = c.post(f"/api/v1/forms/{fid}/submissions", headers=h, json={"data": {}})
        check("required-field validation", bad.status_code == 400)
        sub = c.post(f"/api/v1/forms/{fid}/submissions", headers=h, json={"data": {"title": "hello"}})
        check("submit form", sub.status_code == 201)
        check("list submissions", c.get(f"/api/v1/forms/{fid}/submissions", headers=h).json()["total"] >= 1)

        print("\n== Workflows ==")
        graph = {"nodes": [
            {"id": "n1", "type": "start", "name": "Start", "x": 60, "y": 100, "config": {}},
            {"id": "n2", "type": "condition", "name": "Days > 3", "x": 260, "y": 100,
             "config": {"field": "days", "operator": "gt", "value": 3}},
            {"id": "n3", "type": "approval", "name": "Manager", "x": 470, "y": 40, "config": {"approver_role": "admin"}},
            {"id": "n4", "type": "notification", "name": "Notify", "x": 470, "y": 170, "config": {"channel": "in-app"}},
            {"id": "n5", "type": "end", "name": "End", "x": 680, "y": 100, "config": {}}],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2"},
                {"id": "e2", "source": "n2", "target": "n3", "condition": "true"},
                {"id": "e3", "source": "n2", "target": "n4", "condition": "false"},
                {"id": "e4", "source": "n3", "target": "n5"},
                {"id": "e5", "source": "n4", "target": "n5"}]}
        wf = c.post("/api/v1/workflows", headers=h, json={"code": f"smoke_flow_{suffix}",
            "name": "Smoke Flow", "status": "draft", "graph": graph})
        check("create workflow DAG", wf.status_code == 201, str(wf.json() if wf.status_code != 201 else ""))
        wid = wf.json().get("id", 0)
        check("validate graph", c.post(f"/api/v1/workflows/{wid}/validate", headers=h).json()["valid"])
        run = c.post(f"/api/v1/workflows/{wid}/run", headers=h, json={"context": {"days": 5}})
        check("run workflow (true branch)", run.status_code == 201 and run.json()["status"] == "completed")
        check("condition routing", any(e.get("node") == "n3" for e in run.json()["logs"]))
        run2 = c.post(f"/api/v1/workflows/{wid}/run", headers=h, json={"context": {"days": 1}})
        check("run workflow (false branch)", any(e.get("node") == "n4" for e in run2.json()["logs"]))
        check("instance log", c.get(f"/api/v1/workflows/{wid}/instances", headers=h).json()["total"] >= 2)

        print("\n== Knowledge / RAG / uploads ==")
        search = c.post("/api/v1/knowledge/search", headers=h, json={"query": "请假制度 leave policy"})
        check("BM25 RAG search", search.status_code == 200 and search.json()["count"] > 0)
        doc = c.post("/api/v1/knowledge/documents", headers=h, json={"collection_id": 1,
            "title": f"Smoke doc {suffix}", "content": "Passkey and OTP enrollment guide for the platform."})
        check("create + index document", doc.status_code == 201 and len(doc.json().get("chunks", [])) > 0)
        check("reindex", c.post(f"/api/v1/knowledge/documents/{doc.json()['id']}/reindex", headers=h).json()["ok"])
        fmts = c.get("/api/v1/knowledge/formats", headers=h).json()
        check("upload format catalog", fmts["total"] >= 35 and any(
            f["ext"] == ".docx" for f in fmts["formats"]))
        # Build real Office/PDF fixtures with the standard library only.
        import io
        import zipfile

        def _ooxml(member: str, xml: str) -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("[Content_Types].xml", "<Types/>")
                z.writestr(member, xml)
            return buf.getvalue()

        docx = _ooxml("word/document.xml",
                      f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                      f'<w:body><w:p><w:r><w:t>Smoke Word {suffix}</w:t></w:r></w:p>'
                      f'<w:p><w:r><w:t>Passkey enrollment notes.</w:t></w:r></w:p>'
                      f'</w:body></w:document>')
        xlsx = _ooxml("xl/worksheets/sheet1.xml",
                      '<s:worksheet xmlns:s="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                      "<s:sheetData><s:row><s:c t='inlineStr'><s:is><s:t>Asset</s:t></s:is></s:c>"
                      "<s:c><s:v>42</s:v></s:c></s:row></s:sheetData></s:worksheet>")
        pptx = _ooxml("ppt/slides/slide1.xml",
                      f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                      f'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                      f'<a:p><a:r><a:t>Smoke Slide {suffix}</a:t></a:r></a:p></p:sld>')
        pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        uploads = [
            ("notes.md", b"# Markdown smoke\nUploaded knowledge document."),
            ("report.docx", docx), ("data.xlsx", xlsx), ("deck.pptx", pptx),
            ("manual.pdf", pdf), ("table.csv", b"name,value\nsmoke,1\n"),
        ]
        files = [("files", (name, payload, "application/octet-stream"))
                 for name, payload in uploads]
        up = c.post("/api/v1/knowledge/upload", headers=h,
                    data={"collection_id": "1"}, files=files)
        check("multi-format upload", up.status_code == 201 and up.json()["uploaded"] >= 5,
              str(up.json())[:260])
        check("docx text extracted", any(
            d.get("file_type") == "docx" and d.get("chars", 0) > 10
            for d in up.json()["documents"]))
        check("xlsx text extracted", any(
            d.get("file_type") == "xlsx" and d.get("chars", 0) > 3
            for d in up.json()["documents"]))
        check("upload writes file metadata", any(
            d.get("file_name") == "notes.md" and d.get("parse_status") == "parsed"
            for d in up.json()["documents"]))
        uploaded_ids = [d["id"] for d in up.json()["documents"] if d.get("ok")]
        docs = c.get("/api/v1/knowledge/documents?collection_id=1", headers=h).json()
        check("uploaded docs are listed with labels", any(
            d.get("id") in uploaded_ids and d.get("file_label") for d in docs["documents"]))
        bad = c.post("/api/v1/knowledge/upload", headers=h, data={"collection_id": "1"},
                     files=[("files", ("evil.exe", b"MZ", "application/octet-stream"))])
        check("unsupported format rejected per file", bad.status_code == 201
              and bad.json()["failed"] == 1 and bad.json()["uploaded"] == 0)
        check("knowledge stats expose upload counts", c.get(
            "/api/v1/knowledge/stats", headers=h).json()["uploaded"] >= 5)

        print("\n== AI Agents ==")
        chat1 = c.post("/api/v1/agents/1/chat", headers=h, json={"message": "What is the leave policy?"})
        check("query agent grounded answer", chat1.status_code == 200 and len(chat1.json()["sources"]) > 0)
        chat2 = c.post("/api/v1/agents/3/chat", headers=h, json={"message": "List all forms and show platform statistics"})
        check("act agent tool loop", chat2.status_code == 200 and len(chat2.json()["steps"]) >= 2,
              str(chat2.json().get("steps"))[:200])
        rt = c.get("/api/v1/agents/meta/runtime", headers=h).json()
        check("agent runtime metadata", rt["runtime"]["agentscope"]["available"])
        check("runtime exposes model categories", len(rt["model_providers"]["categories"]) >= 5)
        bind = c.get("/api/v1/agents/meta/bindings", headers=h).json()
        check("agent binding catalog", bind["counts"]["servers"] >= 3
              and bind["counts"]["skills"] >= 5 and bind["counts"]["collections"] >= 2)
        builtin_srv = next(s for s in bind["servers"] if s["transport"] == "builtin")
        new_agent = c.post("/api/v1/agents", headers=h, json={
            "code": f"smoke_agent_{suffix}", "name": "Smoke Bound Agent", "mode": "hybrid",
            "system_prompt": "You are a smoke-test agent.", "temperature": 0.2,
            "kb_ids": [1], "skill_ids": [1], "server_ids": [builtin_srv["id"]],
            "workflow_ids": [1], "status": "active"})
        check("create agent with MCP/skill/KB bindings", new_agent.status_code == 201
              and new_agent.json()["server_ids"] == [builtin_srv["id"]],
              str(new_agent.json())[:200])
        aid = new_agent.json().get("id", 0)
        patch = c.put(f"/api/v1/agents/{aid}", headers=h, json={"server_ids": [], "kb_ids": [1, 2]})
        check("update agent bindings", patch.status_code == 200
              and patch.json()["server_ids"] == [] and patch.json()["kb_ids"] == [1, 2])
        check("agent binding cleans stale ids", c.put(f"/api/v1/agents/{aid}", headers=h,
              json={"server_ids": [999999]}).json()["server_ids"] == [])
        bound_chat = c.post(f"/api/v1/agents/{aid}/chat", headers=h,
                            json={"message": "Show platform statistics"})
        check("bound agent chat", bound_chat.status_code == 200
              and bound_chat.json()["tools_available"] >= 1)

        print("\n== MCP transport ==")
        check("MCP initialize", c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1"}}}).status_code == 200)
        tl = c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        check("MCP tools/list", tl.status_code == 200 and len(tl.json()["result"]["tools"]) >= 12)
        call = c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_stats", "arguments": {}}})
        check("MCP tools/call", call.status_code == 200 and not call.json()["result"]["isError"])
        check("REST tool invoke", c.post("/api/v1/mcp/invoke", headers=h,
            json={"tool": "get_stats", "arguments": {}, "target": "server:platform-builtin"}).status_code == 200)
        tool_catalog = c.get("/api/v1/mcp/tools", headers=h).json()
        check("tool catalog separates builtin/external", tool_catalog["builtin_tools"] == 20
              and "external_tools" in tool_catalog)
        check("MCP status separates servers and skills", c.get(
            "/api/v1/mcp/status", headers=h).json()["servers"]["total"] >= 3)

        print("\n== MCP servers (independent registry) ==")
        servers = c.get("/api/v1/mcp/servers", headers=h).json()
        builtin = next((s for s in servers["servers"] if s["transport"] == "builtin"), None)
        check("MCP server registry", servers["total"] >= 3 and builtin is not None)
        check("server summary", c.get("/api/v1/mcp/servers/summary", headers=h).json()["declared_tools"] >= 12)
        synced = c.post(f"/api/v1/mcp/servers/{builtin['id']}/sync", headers=h, json={})
        check("MCP server sync", synced.json()["health"] == "healthy")
        check("server tool list", c.get(
            f"/api/v1/mcp/servers/{builtin['id']}/tools", headers=h).json()["total"] >= 12)
        srv = c.post("/api/v1/mcp/servers", headers=h, json={
            "code": f"smoke_server_{suffix}", "name": "Smoke Server", "transport": "http",
            "endpoint": "http://127.0.0.1:9209/mcp", "enabled": False,
            "tools": [{"name": "smoke_remote", "description": "Remote smoke tool"}]})
        check("create MCP server", srv.status_code == 201 and srv.json()["transport"] == "http")
        srv_id = srv.json()["id"]
        check("update MCP server", c.put(f"/api/v1/mcp/servers/{srv_id}", headers=h,
              json={"description": "updated"}).json()["description"] == "updated")
        check("enable MCP server", c.post(f"/api/v1/mcp/servers/{srv_id}/enable", headers=h,
              json={}).json()["enabled"] is True)
        check("server invoke rejects undeclared tool", c.post(
            f"/api/v1/mcp/servers/{srv_id}/invoke", headers=h,
            json={"tool": "get_stats", "arguments": {}}).status_code == 400)
        check("delete MCP server", c.delete(f"/api/v1/mcp/servers/{srv_id}", headers=h).status_code == 200)

        print("\n== MCP call journal ==")
        calls = c.get("/api/v1/mcp/calls", headers=h).json()
        check("journal records MCP methods", any(x["source"] == "mcp" for x in calls["calls"]))
        check("journal records REST invoke", any(x["source"] == "rest" for x in calls["calls"]))
        check("journal entry shape", "arguments" in calls["calls"][0] and "result" in calls["calls"][0])
        c.post("/api/v1/mcp/invoke", headers=h, json={"tool": "missing_tool", "arguments": {}})
        check("failed invocation is journaled", c.get(
            "/api/v1/mcp/calls?status=error", headers=h).json()["total"] >= 1)
        st = c.get("/api/v1/mcp/calls/stats", headers=h).json()
        check("journal statistics", st["total"] >= 4 and "by_tool" in st and "timeline" in st)
        check("journal detail", c.get(
            f"/api/v1/mcp/calls/{calls['calls'][0]['id']}", headers=h).status_code == 200)
        exp = c.get("/api/v1/mcp/calls/export", headers=h)
        check("journal CSV export", exp.status_code == 200
              and "text/csv" in exp.headers.get("content-type", ""))

        print("\n== Skills (independent registry) ==")
        skill_list = c.get("/api/v1/skills", headers=h).json()
        check("skills registry is separate from servers", skill_list["total"] >= 5
              and len(skill_list["servers"]) >= 3)
        cat = c.get("/api/v1/skills/catalog", headers=h).json()
        check("installable skill catalog", cat["total"] >= 5 and "files" in cat["catalog"][0])
        import app.services.skill_files as sf
        try:
            sf.validate_path("../escape")
            safe = False
        except ValueError:
            safe = True
        check("skill file path traversal rejected", safe)
        target = "sqlite-query"
        existing_skill = next((s for s in skill_list["skills"] if s["code"] == target), None)
        if existing_skill:
            c.post(f"/api/v1/skills/{existing_skill['id']}/uninstall", headers=h, json={})
        installed = c.post("/api/v1/skills/install", headers=h,
                           json={"code": target, "server_id": builtin["id"]})
        check("install skill from catalog", installed.status_code == 201
              and installed.json()["status"] == "installed")
        check("skill links to an MCP server", installed.json()["server"]["id"] == builtin["id"])
        sid = installed.json().get("id", 0)
        check("install creates editable files", installed.json()["files_created"] >= 4)
        fl = c.get(f"/api/v1/skills/{sid}/files", headers=h).json()
        check("skill file list + disk path", fl["total"] >= 4 and bool(fl["disk_path"]))
        mf = c.get(f"/api/v1/skills/{sid}/files/manifest.json", headers=h)
        check("read skill file", mf.status_code == 200 and "content" in mf.json())
        upd = c.put(f"/api/v1/skills/{sid}/files/notes/smoke.md", headers=h,
                    json={"content": "# smoke\n"})
        check("create / update skill file", upd.status_code == 200
              and upd.json()["path"] == "notes/smoke.md")
        check("file list reflects new file", c.get(
            f"/api/v1/skills/{sid}/files", headers=h).json()["total"] == fl["total"] + 1)
        check("disable skill", c.post(f"/api/v1/skills/{sid}/disable", headers=h,
              json={}).json()["status"] == "disabled")
        check("enable skill", c.post(f"/api/v1/skills/{sid}/enable", headers=h,
              json={}).json()["status"] == "installed")
        un = c.post(f"/api/v1/skills/{sid}/uninstall", headers=h, json={}).json()
        check("uninstall removes installed files", un["status"] == "uninstalled"
              and c.get(f"/api/v1/skills/{sid}/files", headers=h).json()["total"] == 0)
        re = c.post(f"/api/v1/skills/{sid}/reinstall", headers=h, json={}).json()
        check("reinstall restores default files", re["status"] == "installed"
              and re["files_affected"] >= 4)
        check("skill sync through linked server", c.post(
            f"/api/v1/skills/{sid}/sync", headers=h, json={}).json()["health"] == "healthy")
        check("delete skill file", c.delete(
            f"/api/v1/skills/{sid}/files/README.md", headers=h).status_code == 200)
        check("delete skill", c.delete(f"/api/v1/skills/{sid}", headers=h).status_code == 200)
        check("deleting a skill leaves servers intact", c.get(
            "/api/v1/mcp/servers", headers=h).json()["total"] >= 3)

        print("\n== AI model providers (llm / asr / tts / embedding / rerank / vision) ==")
        pmeta = c.get("/api/v1/ai/providers/meta", headers=h).json()
        check("model category metadata", len(pmeta["categories"]) >= 5
              and len(pmeta["vendors"]) >= 6)
        check("default providers seeded", all(pmeta["defaults"].get(k) for k in
              ("llm", "asr", "tts", "embedding", "rerank", "vision")))
        plist = c.get("/api/v1/ai/providers", headers=h).json()
        check("provider list masks secrets", all("api_key" not in p and "has_api_key" in p
              for p in plist["providers"]))
        created = c.post("/api/v1/ai/providers", headers=h, json={
            "code": f"smoke_llm_{suffix}", "name": "Smoke LLM", "category": "llm",
            "vendor": "openai", "base_url": "https://api.example.com/v1",
            "api_key": "sk-smoke-secret-123456", "model": "smoke-model",
            "enabled": True, "is_default": False})
        check("create LLM provider", created.status_code == 201, str(created.json())[:200])
        pid = created.json()["id"]
        check("API key is masked on read", created.json()["has_api_key"]
              and created.json()["api_key_masked"].endswith("3456")
              and "api_key" not in created.json())
        check("bad category rejected", c.post("/api/v1/ai/providers", headers=h, json={
            "code": f"bad_{suffix}", "name": "Bad", "category": "nope"}).status_code == 400)
        check("update provider keeps secret when masked", c.put(
            f"/api/v1/ai/providers/{pid}", headers=h,
            json={"model": "smoke-model-v2", "api_key": created.json()["api_key_masked"]}
        ).json()["model"] == "smoke-model-v2")
        check("set default provider", c.post(f"/api/v1/ai/providers/{pid}/default",
              headers=h, json={}).json()["is_default"] is True)
        check("default is exclusive per category", sum(1 for p in c.get(
            "/api/v1/ai/providers?category=llm", headers=h).json()["providers"]
            if p["is_default"]) == 1)
        check("effective runtime config comes from default", c.get(
            "/api/v1/ai/providers/meta", headers=h).json()["effective_llm"]["model"] == "smoke-model-v2")
        check("provider config test", c.post(f"/api/v1/ai/providers/{pid}/test",
              headers=h, json={"live": False}).json()["mode"] == "configuration")
        check("delete provider", c.delete(f"/api/v1/ai/providers/{pid}", headers=h).status_code == 200)

        print("\n== Settings -> AI model services (.env bootstrap) ==")
        ai = c.get("/api/v1/settings/ai", headers=h).json()
        cats = {i["category"]: i for i in ai["categories"]}
        check("settings ai covers all six categories",
              set(cats) == set(model_providers.CATEGORY_CODES))
        check("settings ai reads initial values from env",
              cats["llm"]["env"]["model"] == model_providers.env_values("llm")["model"]
              and "api_key" not in cats["llm"]["env"])
        check("settings ai marks untouched defaults as env-managed",
              cats["llm"]["source"] == "env" and bool(cats["llm"]["base_url"]))
        before_env = model_providers.env_values("vision")
        saved = c.put("/api/v1/settings/ai", headers=h, json={"items": [{
            "category": "vision", "base_url": "https://vision.example.com/v1",
            "model": "vision-smoke", "api_key": "sk-vision-smoke-123456", "enabled": True}]})
        vcats = {i["category"]: i for i in saved.json()["categories"]}
        check("settings ai saves per category and detaches from env",
              saved.status_code == 200 and vcats["vision"]["source"] == "manual"
              and vcats["vision"]["model"] == "vision-smoke"
              and vcats["vision"]["has_api_key"] and "api_key" not in vcats["vision"])
        check("settings ai rejects unknown category", c.put(
            "/api/v1/settings/ai", headers=h,
            json={"items": [{"category": "nope"}]}).status_code == 400)
        # Restore the demo row so the dev database keeps showing env bootstrap.
        db.update("ai_providers", vcats["vision"]["provider_id"], {
            "base_url": before_env["base_url"], "model": before_env["model"],
            "api_key": before_env["api_key"], "enabled": 0,
            "config": {"env_managed": True}})
        restored = {i["category"]: i for i in c.get(
            "/api/v1/settings/ai", headers=h).json()["categories"]}["vision"]
        check("settings ai restores env-managed state", restored["source"] == "env")

        print("\n== RBAC / Auth / Audit ==")
        check("list users", c.get("/api/v1/rbac/users", headers=h).json()["total"] >= 4)
        check("permission matrix", len(c.get("/api/v1/rbac/matrix", headers=h).json()["roles"]) >= 4)
        check("permission check", c.post("/api/v1/rbac/check", headers=h,
            json={"permission": "form:write"}).json()["allowed"])
        bob = c.post("/api/v1/auth/login", json={"username": "bob", "password": "demo1234"}).json()["access_token"]
        bh = {"Authorization": f"Bearer {bob}"}
        check("RBAC denial for operator", c.post("/api/v1/forms", headers=bh, json={
            "code": "denied", "name": "x", "schema": []}).status_code == 403)
        check("RBAC allow form:submit", c.post("/api/v1/forms/1/submissions", headers=bh,
            json={"data": {"applicant": "bob", "department": "Sales", "leave_type": "Annual",
                           "start_date": "2026-11-10", "end_date": "2026-11-10", "days": 1,
                           "reason": "smoke"}}).status_code == 201)

        providers = c.get("/api/v1/auth/providers").json()["providers"]
        check("SSO providers registered", any(p["code"] == "cas" for p in providers))
        sso = c.get("/api/v1/auth/sso/cas/authorize").json()
        check("SSO demo authorize", sso["demo"] is True)
        cb = c.post("/api/v1/auth/sso/cas/callback", json={"state": sso["state"], "code": "demo-code"})
        check("SSO demo callback provisions user", cb.status_code == 200 and cb.json()["user"]["username"] == "cas_demo")

        policy = c.get("/api/v1/auth/mfa-policy", headers=h).json()
        check("MFA policy read", "enforced_roles" in policy)
        otp = c.post("/api/v1/auth/otp/setup", headers=h, json={})
        check("TOTP setup", "otpauth_uri" in otp.json())
        import app.security as sec
        enabled = c.post("/api/v1/auth/otp/enable", headers=h,
            json={"secret": otp.json()["secret"], "code": sec.totp_code(otp.json()["secret"])})
        check("TOTP enrollment", enabled.status_code == 200)
        check("MFA policy update", c.put("/api/v1/auth/mfa-policy", headers=h,
            json={"required": False, "enforced_roles": policy["enforced_roles"],
                  "enforced_users": policy["enforced_users"]}).status_code == 200)
        check("audit logs", c.get("/api/v1/audit/logs", headers=h).json()["total"] > 10)
        check("platform settings", c.get("/api/v1/settings", headers=h).status_code == 200)

        print("\n== Domestic form features (CN scenarios) ==")
        fmeta = c.get("/api/v1/forms/meta", headers=h).json()
        check("44 form field types in 5 groups", fmeta["field_count"] == 44
              and len(fmeta["groups"]) == 5)
        check("validators include statutory CN rules", {"idcard", "mobile", "uscc", "bankcard"}
              <= {v["code"] for v in fmeta["validators"]})
        check("formula functions include CNY_UPPER + TABLE_SUM", {"CNY_UPPER", "TABLE_SUM"}
              <= {f["code"] for f in fmeta["functions"]})
        dcode = f"cn_form_{suffix}"
        df = c.post("/api/v1/forms", headers=h, json={
            "code": dcode, "name": "Domestic form", "status": "draft",
            "schema": [
                {"id": "d1", "key": "serial_no", "type": "serial", "label": "No.",
                 "serial": {"prefix": "CN", "date": True, "digits": 4}},
                {"id": "d2", "key": "mobile", "type": "mobile", "label": "Mobile", "required": True},
                {"id": "d3", "key": "idcard", "type": "idcard", "label": "ID card"},
                {"id": "d4", "key": "amount", "type": "amount", "label": "Amount",
                 "required": True, "show_upper": True},
                {"id": "d5", "key": "secret", "type": "text", "label": "Extra",
                 "visible_when": {"logic": "and", "conditions": [
                     {"field": "amount", "operator": "gt", "value": 1000}]}},
                {"id": "d6", "key": "items", "type": "table", "label": "Details",
                 "columns": [{"key": "qty", "label": "Qty", "type": "number"},
                             {"key": "price", "label": "Price", "type": "number"},
                             {"key": "sub", "label": "Sub", "type": "formula",
                              "formula": "qty * price"}],
                 "summary": [{"key": "total", "label": "Total", "column": "sub", "op": "sum"}]},
                {"id": "d7", "key": "computed_total", "type": "formula", "label": "Formula",
                 "formula": "TABLE_SUM(\"items\", \"sub\")"},
            ], "layout": {"columns": 2}}).json()
        dfid = df["id"]
        check("domestic form created", df.get("version") == 1)
        check("form version snapshot", c.get(
            f"/api/v1/forms/{dfid}/versions", headers=h).json()["total"] >= 1)
        dev = c.post(f"/api/v1/forms/{dfid}/evaluate", headers=h, json={"data": {
            "mobile": "13800138000", "idcard": "11010519491231002X", "amount": 1234.56,
            "items": [{"qty": 2, "price": 10}, {"qty": 3, "price": 100}]}}).json()
        check("detail table row formula + summary", dev["data"]["items"][1]["sub"] == 300
              and dev["data"]["items_total"] == 320)
        check("TABLE_SUM formula", dev["data"]["computed_total"] == 320)
        check("RMB amount in words", dev["computed"]["amount_upper"]
              == "壹仟贰佰叁拾肆元伍角陆分")
        check("ID card parsed (birthday/gender/age)", dev["computed"]["idcard_info"]["gender"] == "女")
        check("conditional display hides/shows fields", "secret" in dev["visible"])
        bad = c.post(f"/api/v1/forms/{dfid}/evaluate", headers=h,
                     json={"data": {"mobile": "123", "amount": 10}}).json()
        check("invalid CN mobile rejected", any(e["rule"] == "mobile" for e in bad["errors"]))
        check("form publishes", c.post(f"/api/v1/forms/{dfid}/publish", headers=h).status_code == 200)
        dsub = c.post(f"/api/v1/forms/{dfid}/submissions", headers=h, json={"data": {
            "mobile": "13800138000", "amount": 1234.56,
            "items": [{"qty": 2, "price": 10}, {"qty": 3, "price": 100}]}})
        check("submission with serial number", dsub.status_code == 201
              and bool(dsub.json()["serial_no"]))
        check("submission stores computed values", bool(dsub.json()["computed"]))
        check("CSV export", c.get(
            f"/api/v1/forms/{dfid}/submissions/export", headers=h).status_code == 200)
        check("print view includes RMB upper", any(
            f["upper"] for f in c.get(
                f"/api/v1/forms/{dfid}/print/{dsub.json()['submission_id']}",
                headers=h).json()["fields"]))
        check("mobile render is single column", c.get(
            f"/api/v1/forms/{dfid}/render?platform=mobile", headers=h).json()["columns"] == 1)
        check("version restore", c.post(f"/api/v1/forms/{dfid}/versions", headers=h,
              json={"version": 1}).status_code == 201)

        print("\n== Domestic approval runtime ==")
        wmeta = c.get("/api/v1/workflows/meta", headers=h).json()
        check("14 node types incl. parallel/join/cc", len(wmeta["node_types"]) == 14)
        check("9 approver rules + 4 sign modes", len(wmeta["approver_rules"]) == 9
              and len(wmeta["sign_modes"]) == 4)
        check("org units seeded", c.get("/api/v1/meta/health").json()["form_flow"]["org_units"] >= 5)
        ewf = next(w for w in c.get("/api/v1/workflows", headers=h).json()["workflows"]
                   if w["code"] == "expense_approval")
        started = c.post(f"/api/v1/workflows/{ewf['id']}/start", headers=h, json={
            "form_data": {"mobile": "13800138000", "claim_type": "差旅", "applicant": "admin",
                          "department": "IT", "remark": "客户拜访",
                          "items": [{"qty": 2, "price": 3000}]},
            "create_submission": True})
        check("approval instance started", started.status_code == 201, started.text[:120])
        inst = started.json()
        iid = inst["id"]
        check("leader-chain resolver produced a task", len(inst["pending"]) == 1)
        check("form submission linked to instance", inst.get("submission_id") is not None)
        fsch = c.get(f"/api/v1/workflows/instances/{iid}/form-schema", headers=h).json()
        check("per-node field permissions (readonly)", fsch["permissions"].get("total_amount") == "readonly")
        first = c.post(f"/api/v1/workflows/instances/{iid}/tasks/{inst['pending'][0]['id']}/act",
                       headers=h, json={"action": "approve", "comment": "ok"})
        check("leader approves", first.status_code == 200)
        check("parallel branch opened 3 tasks", len(first.json()["pending"]) >= 3)
        for task in list(first.json()["pending"]):
            r = c.post(f"/api/v1/workflows/instances/{iid}/tasks/{task['id']}/act",
                       headers=h, json={"action": "approve", "comment": "ok"})
            check(f"countersign task {task['assignee']} approved", r.status_code == 200)
        done = c.get(f"/api/v1/workflows/instances/{iid}", headers=h).json()
        check("join + cc -> instance approved", done["status"] == "approved")
        check("timeline records all steps", len(done["logs"]) >= 8)
        check("task center", c.get("/api/v1/workflows/tasks?all_users=true", headers=h).status_code == 200)
        check("instance timeline endpoint", c.get(
            f"/api/v1/workflows/instances/{iid}/timeline", headers=h).status_code == 200)
        s2 = c.post(f"/api/v1/workflows/{ewf['id']}/start", headers=h, json={
            "form_data": {"mobile": "13800138000", "claim_type": "办公采购",
                          "applicant": "admin", "department": "IT"},
            "create_submission": False}).json()
        i2, t2 = s2["id"], s2["pending"][0]
        tr = c.post(f"/api/v1/workflows/instances/{i2}/tasks/{t2['id']}/act", headers=h,
                    json={"action": "transfer", "assignee": "alice"})
        check("transfer task", tr.status_code == 200
              and any(t["assignee"] == "alice" for t in tr.json()["pending"]))
        t3 = next(t for t in tr.json()["pending"] if t["assignee"] == "alice")
        check("add-sign", c.post(f"/api/v1/workflows/instances/{i2}/tasks/{t3['id']}/act",
              headers=h, json={"action": "addsign_after", "assignee": "bob"}).status_code == 200)
        check("return to initiator", c.post(
            f"/api/v1/workflows/instances/{i2}/tasks/{t3['id']}/act", headers=h,
            json={"action": "return", "comment": "补充材料"}).status_code == 200)
        check("urge", c.post(f"/api/v1/workflows/instances/{i2}/urge", headers=h, json={}).status_code == 200)
        check("withdraw", c.post(f"/api/v1/workflows/instances/{i2}/withdraw", headers=h,
              json={}).status_code == 200)
        check("timeout sweep", c.post("/api/v1/workflows/instances/sweep-timeouts",
              headers=h).status_code == 200)
        check("delegation create + list", c.post("/api/v1/workflows/delegations", headers=h,
              json={"principal": "bob", "agent": "carol"}).status_code == 201
              and c.get("/api/v1/workflows/delegations", headers=h).json()["total"] >= 1)
        c.delete(f"/api/v1/forms/{dfid}", headers=h)

        print("\n== Data scopes, portal, agent intents ==")
        from app.services import data_scope
        check("admin has all data scope", me.json().get("data_scope") == "all")
        boot2 = c.get("/api/v1/meta/bootstrap", headers=h).json()
        check("data:audit permission registered",
              any(p["code"] == "data:audit" for p in boot2["rbac"]["permissions"]))
        check("auditor builtin role seeded",
              any(r["code"] == "auditor" for r in boot2["rbac"]["roles"]))
        check("20 builtin MCP tool specs",
              boot2["mcp"].get("builtin_tool_count") == 20,
              str(boot2["mcp"].get("builtin_tool_count")))
        hs = c.get("/api/v1/meta/health").json().get("security", {})
        check("health advertises data scopes",
              set(hs.get("data_scopes", [])) == {"all", "audit", "self"}
              and hs.get("auditor_role") is True)

        bob_login = c.post("/api/v1/auth/login",
                           json={"username": "bob", "password": "demo1234"})
        check("operator demo login", "access_token" in bob_login.json())
        bh = {"Authorization": f"Bearer {bob_login.json().get('access_token', '')}"}
        diana_login = c.post("/api/v1/auth/login",
                             json={"username": "diana", "password": "demo1234"})
        check("auditor demo login", "access_token" in diana_login.json())
        dh = {"Authorization": f"Bearer {diana_login.json().get('access_token', '')}"}
        bob_me = c.get("/api/v1/auth/me", headers=bh).json()
        diana_me = c.get("/api/v1/auth/me", headers=dh).json()
        check("operator is self-scoped",
              bob_me.get("data_scope") == "self" and not bob_me.get("is_admin"))
        check("auditor has audit scope",
              diana_me.get("data_scope") == "audit" and diana_me.get("is_auditor") is True)
        check("data_scope.read_only(auditor)", data_scope.read_only(diana_me))
        check("data_scope self for form submissions",
              data_scope.scope_for(bob_me, "form_submissions") == "self")

        admin_subs = c.get(f"/api/v1/forms/{fid}/submissions", headers=h).json()["total"]
        bob_subs = c.get(f"/api/v1/forms/{fid}/submissions", headers=bh).json()["total"]
        diana_subs = c.get(f"/api/v1/forms/{fid}/submissions", headers=dh).json()["total"]
        check("self scope hides other owners' submissions", bob_subs == 0)
        check("auditor reads all submissions", diana_subs == admin_subs >= 1)
        check("auditor is read-only on writes", c.post("/api/v1/workflows", headers=dh,
              json={"code": f"denied_{suffix}", "name": "denied",
                    "graph": {"nodes": [], "edges": []}}).status_code == 403)
        check("self user cannot list all users' tasks", c.get(
              "/api/v1/workflows/tasks?all_users=true", headers=bh).json().get("assignee") == "bob")

        # --- redesigned workflow portal -------------------------------------
        cat = c.get("/api/v1/workflows/catalog", headers=h).json()
        check("portal catalog lists published workflows", cat.get("total", 0) >= 2
              and any(w["startable"] for w in cat.get("workflows", [])))
        check("catalog share paths require auth", all(
              w["requires_auth"] and w["start_path"].startswith("/#/start/")
              for w in cat.get("workflows", [])))
        mine = c.get("/api/v1/workflows/mine/instances?status=all", headers=h).json()
        check("my instances endpoint", "instances" in mine and mine.get("scope") == "all")
        check("mine instances status filter", all(i["status"] == "approved" for i in c.get(
              "/api/v1/workflows/mine/instances?status=approved", headers=h).json()["instances"]))
        bob_mine = c.get("/api/v1/workflows/mine/instances?status=all", headers=bh).json()
        check("self scope hides other initiators", bob_mine.get("scope") == "self"
              and all(i.get("started_by") == "bob" for i in bob_mine.get("instances", [])))
        pstats = c.get("/api/v1/workflows/mine/stats", headers=h).json()
        check("portal stats", pstats.get("startable_workflows", 0) >= 1
              and pstats.get("total", 0) >= 1)
        share = c.get("/api/v1/workflows/share-info/expense_approval")
        check("public share-info needs no token", share.status_code == 200)
        sj = share.json() if share.status_code == 200 else {}
        check("share-info is auth-gated", sj.get("requires_auth") is True
              and "next=" in sj.get("login_path", "")
              and sj.get("start_path") == "/#/start/expense_approval")
        check("share-info exposes workflow_id", isinstance(sj.get("workflow_id"), int))
        sch = c.get(f"/api/v1/workflows/{ewf['id']}/start-schema", headers=h).json()
        check("dynamic start schema from bound form", len(sch.get("fields", [])) >= 1
              and (sch.get("form") or {}).get("code") == "expense_claim")
        check("start schema is auth-gated", c.get(
              f"/api/v1/workflows/{ewf['id']}/start-schema").status_code in (401, 403))

        # --- agent self-service intents + schema-driven dynamic form --------
        rt2 = c.get("/api/v1/agents/meta/runtime", headers=h).json()
        check("20 tool specs in runtime metadata", len(rt2.get("tools", [])) == 20)
        who = c.post("/api/v1/agents/1/chat", headers=h,
                     json={"message": "我是谁，有哪些权限？"})
        check("identity intent uses scoped tool", who.status_code == 200
              and who.json().get("provider") == "scoped-tool")
        appr = c.post("/api/v1/agents/1/chat", headers=h,
                      json={"message": "查询我的审批及进度"})
        check("my approvals intent uses scoped tool", appr.status_code == 200
              and appr.json().get("provider") == "scoped-tool")
        collect = c.post(f"/api/v1/agents/{aid}/chat", headers=h,
                         json={"message": "帮我创建一个费用报销流程"})
        ar = (collect.json().get("action_request") or {}) if collect.status_code == 200 else {}
        check("collect intent returns action_request", bool(ar))
        check("action_request carries dynamic schema", ar.get("kind") == "start_workflow"
              and len(ar.get("schema", [])) >= 1 and "instance_id" not in ar)
        act = c.post(f"/api/v1/agents/{aid}/actions", headers=h, json={
            "kind": ar.get("kind", ""), "code": ar.get("code", ""),
            "data": {"mobile": "13800138000", "claim_type": "差旅", "applicant": "admin",
                     "department": "IT", "remark": "smoke",
                     "items": [{"qty": 1, "price": 100}]},
            "conversation_id": collect.json().get("conversation_id")})
        check("dynamic form action creates a real instance", act.status_code == 200
              and act.json().get("ok") is True and act.json().get("instance_id"),
              act.text[:160])
        if act.json().get("instance_id"):
            c.post(f"/api/v1/workflows/instances/{act.json()['instance_id']}/withdraw",
                   headers=h, json={})

        print("\n== Cleanup ==")
        check("delete smoke workflow", c.delete(f"/api/v1/workflows/{wid}", headers=h).status_code == 200)
        check("delete smoke form", c.delete(f"/api/v1/forms/{fid}", headers=h).status_code == 200)
        check("delete smoke agent", c.delete(f"/api/v1/agents/{aid}", headers=h).status_code == 200)
        for did in uploaded_ids:
            c.delete(f"/api/v1/knowledge/documents/{did}", headers=h)
        c.delete(f"/api/v1/knowledge/documents/{doc.json()['id']}", headers=h)
        check("clear MCP call journal", c.delete("/api/v1/mcp/calls", headers=h).status_code == 200)
        check("bootstrap exposes all registries", all(k in c.get(
            "/api/v1/meta/bootstrap", headers=h).json() for k in ("mcp", "skills", "ai")))

    print(f"\nResult: {PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
