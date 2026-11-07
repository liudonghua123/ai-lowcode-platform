"""End-to-end smoke test for the AI Low-Code Platform API.

Run from backend/:  uv run python tests/smoke.py
Requires the app dependencies; no external services or API keys are needed.
"""
from __future__ import annotations

import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

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
        check("condition routing", any(l.get("node") == "n3" for l in run.json()["logs"]))
        run2 = c.post(f"/api/v1/workflows/{wid}/run", headers=h, json={"context": {"days": 1}})
        check("run workflow (false branch)", any(l.get("node") == "n4" for l in run2.json()["logs"]))
        check("instance log", c.get(f"/api/v1/workflows/{wid}/instances", headers=h).json()["total"] >= 2)

        print("\n== Knowledge / RAG ==")
        search = c.post("/api/v1/knowledge/search", headers=h, json={"query": "请假制度 leave policy"})
        check("BM25 RAG search", search.status_code == 200 and search.json()["count"] > 0)
        doc = c.post("/api/v1/knowledge/documents", headers=h, json={"collection_id": 1,
            "title": f"Smoke doc {suffix}", "content": "Passkey and OTP enrollment guide for the platform."})
        check("create + index document", doc.status_code == 201 and len(doc.json().get("chunks", [])) > 0)
        check("reindex", c.post(f"/api/v1/knowledge/documents/{doc.json()['id']}/reindex", headers=h).json()["ok"])

        print("\n== AI Agents ==")
        chat1 = c.post("/api/v1/agents/1/chat", headers=h, json={"message": "What is the leave policy?"})
        check("query agent grounded answer", chat1.status_code == 200 and len(chat1.json()["sources"]) > 0)
        chat2 = c.post("/api/v1/agents/3/chat", headers=h, json={"message": "List all forms and show platform statistics"})
        check("act agent tool loop", chat2.status_code == 200 and len(chat2.json()["steps"]) >= 2,
              str(chat2.json().get("steps"))[:200])
        check("agent runtime metadata", c.get("/api/v1/agents/meta/runtime", headers=h).json()["runtime"]["agentscope"]["available"])

        print("\n== MCP ==")
        check("MCP initialize", c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "1"}}}).status_code == 200)
        tl = c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        check("MCP tools/list", tl.status_code == 200 and len(tl.json()["result"]["tools"]) == 12)
        call = c.post("/mcp", headers=mh, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_stats", "arguments": {}}})
        check("MCP tools/call", call.status_code == 200 and not call.json()["result"]["isError"])
        check("REST tool invoke", c.post("/api/v1/mcp/invoke", headers=h,
            json={"tool": "get_stats", "arguments": {}}).status_code == 200)
        skills = c.get("/api/v1/mcp/skills", headers=h).json()
        builtin = next((s for s in skills["skills"] if s["type"] == "builtin"), None)
        check("third-party MCP registry", builtin is not None)
        synced = c.post(f"/api/v1/mcp/skills/{builtin['id']}/sync", headers=h, json={})
        check("MCP skill sync", synced.json()["health"] == "healthy")

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

        print("\n== MCP skill lifecycle & files ==")
        cat = c.get("/api/v1/mcp/skills/catalog", headers=h).json()
        check("installable skill catalog", cat["total"] >= 5 and "files" in cat["catalog"][0])
        import app.services.skill_files as sf
        try:
            sf.validate_path("../escape")
            safe = False
        except ValueError:
            safe = True
        check("skill file path traversal rejected", safe)
        target = "sqlite-query"
        existing_skill = next((s for s in c.get("/api/v1/mcp/skills", headers=h).json()["skills"]
                               if s["code"] == target), None)
        if existing_skill:
            c.post(f"/api/v1/mcp/skills/{existing_skill['id']}/uninstall", headers=h, json={})
        installed = c.post("/api/v1/mcp/skills/install", headers=h, json={"code": target})
        check("install skill from catalog", installed.status_code == 201
              and installed.json()["status"] == "installed")
        sid = installed.json().get("id", 0)
        check("install creates editable files", installed.json()["files_created"] >= 4)
        fl = c.get(f"/api/v1/mcp/skills/{sid}/files", headers=h).json()
        check("skill file list + disk path", fl["total"] >= 4 and bool(fl["disk_path"]))
        mf = c.get(f"/api/v1/mcp/skills/{sid}/files/manifest.json", headers=h)
        check("read skill file", mf.status_code == 200 and "content" in mf.json())
        upd = c.put(f"/api/v1/mcp/skills/{sid}/files/notes/smoke.md", headers=h,
                    json={"content": "# smoke\n"})
        check("create / update skill file", upd.status_code == 200
              and upd.json()["path"] == "notes/smoke.md")
        check("file list reflects new file", c.get(
            f"/api/v1/mcp/skills/{sid}/files", headers=h).json()["total"] == fl["total"] + 1)
        check("disable skill", c.post(f"/api/v1/mcp/skills/{sid}/disable", headers=h,
              json={}).json()["status"] == "disabled")
        check("enable skill", c.post(f"/api/v1/mcp/skills/{sid}/enable", headers=h,
              json={}).json()["status"] == "installed")
        un = c.post(f"/api/v1/mcp/skills/{sid}/uninstall", headers=h, json={}).json()
        check("uninstall removes installed files", un["status"] == "uninstalled"
              and c.get(f"/api/v1/mcp/skills/{sid}/files", headers=h).json()["total"] == 0)
        re = c.post(f"/api/v1/mcp/skills/{sid}/reinstall", headers=h, json={}).json()
        check("reinstall restores default files", re["status"] == "installed"
              and re["files_affected"] >= 4)
        check("delete skill file", c.delete(
            f"/api/v1/mcp/skills/{sid}/files/README.md", headers=h).status_code == 200)
        check("delete skill", c.delete(f"/api/v1/mcp/skills/{sid}", headers=h).status_code == 200)

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

        print("\n== Cleanup ==")
        check("delete smoke workflow", c.delete(f"/api/v1/workflows/{wid}", headers=h).status_code == 200)
        check("delete smoke form", c.delete(f"/api/v1/forms/{fid}", headers=h).status_code == 200)
        check("clear MCP call journal", c.delete("/api/v1/mcp/calls", headers=h).status_code == 200)

    print(f"\nResult: {PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
