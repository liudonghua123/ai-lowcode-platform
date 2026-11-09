"""AI Low-Code Platform — FastAPI application entry point.

* REST API           -> /api/v1/*
* MCP streamable HTTP -> /mcp  (fastmcp SDK, with builtin JSON-RPC fallback)
* SPA (built frontend) -> /    (served when frontend/dist exists)

Run:  uv run uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from . import __version__, db, deps, security, seed
from .config import settings
from .mcp_server import build_mcp
from .routers import (
    agents,
    ai_providers,
    audit,
    auth,
    forms,
    knowledge,
    mcp,
    mcp_servers,
    meta,
    notifications,
    rbac,
    skill_hubs,
    skills,
    workflows,
)
from .services import mcp_journal, mcp_tools, skill_files

mcp_routes, mcp_http_app, mcp_mode = build_mcp()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seeded = seed.seed_if_empty()
    registries = seed.ensure_registries()
    files = skill_files.bootstrap()
    mcp_journal.ensure_demo()
    if seeded:
        print(f"[boot] database initialized: {settings.resolved_db_path}")
    if any(registries.values()):
        print(f"[boot] registries provisioned: {registries}")
    if files["files_created"]:
        print(f"[boot] skill files materialized: {files['files_created']}")
    print(f"[boot] MCP transport: {mcp_mode} at /mcp ({len(mcp_tools.TOOL_SPECS)} tools)")
    if mcp_http_app is not None:
        async with mcp_http_app.lifespan(mcp_http_app):
            yield
    else:
        yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "AI-native low-code platform: visual form designer, DAG workflow orchestration, "
        "RBAC, SSO (CAS/OAuth2/OIDC/WeCom/DingTalk), MFA (OTP/Passkey), knowledge base (RAG), "
        "AI query & action agents, and MCP streamable HTTP with third-party skills."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.state.mcp_mode = mcp_mode

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


# These methods execute a platform tool, which is journaled by
# mcp_tools.call_tool with arguments / result / duration. Everything else is
# journaled here at the transport level.
_TOOL_METHODS = {"tools/call", "resources/read"}


class MCPAuthASGIMiddleware:
    """Bind auth + journal context for MCP POST requests (pure ASGI, streaming safe).

    The JSON-RPC body is buffered once so the method name can be logged; a
    replaying ``receive`` hands the identical body back to the MCP transport.
    Responses (including SSE) are never buffered.
    """

    def __init__(self, wrapped_app):
        self.wrapped_app = wrapped_app

    async def __call__(self, scope, receive, send):
        is_mcp_post = (scope["type"] == "http"
                       and scope.get("path", "").startswith("/mcp")
                       and scope.get("method") == "POST")
        if not is_mcp_post:
            await self.wrapped_app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        token = headers.get("authorization", "")
        user = None
        if token.lower().startswith("bearer "):
            try:
                payload = security.jwt_decode(token.split(" ", 1)[1].strip(), "access")
                user = deps._load_user(payload.get("sub"))
            except ValueError:
                user = None
        if user:
            mcp_tools.bind_user(user)

        chunks, disconnected = [], False
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                disconnected = True
                break
            if message["type"] == "http.request":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
        body = b"".join(chunks)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        try:
            rpc = json.loads(body or b"{}")
        except (ValueError, TypeError):
            rpc = {}
        method = (rpc.get("method") or "unknown") if isinstance(rpc, dict) else "unknown"
        actor = (user or {}).get("username") or "anonymous"
        request_id = db.uid()[:12]
        mcp_tools.bind_context(source="mcp", transport="streamable-http",
                               request_id=request_id, method=method, actor=actor)
        started = time.perf_counter()
        status, error = "success", None
        try:
            if not disconnected:
                await self.wrapped_app(scope, replay, send)
        except Exception as exc:
            status, error = "error", str(exc)
            raise
        finally:
            if (method not in _TOOL_METHODS
                    and not method.startswith("notifications/")):
                params = rpc.get("params") if isinstance(rpc, dict) else None
                mcp_journal.record(
                    method=method, source="mcp", transport="streamable-http",
                    actor=actor, arguments=params if isinstance(params, dict) else {},
                    status=status, error=error, result=None,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    request_id=request_id)


app.add_middleware(MCPAuthASGIMiddleware)

for r in (auth.router, rbac.router, forms.router, workflows.router, knowledge.router,
          agents.router, mcp.router, mcp_servers.router, skills.router, skill_hubs.router,
          ai_providers.router, audit.router, meta.router, meta.settings_router,
          notifications.router):
    app.include_router(r, prefix=settings.api_prefix)

app.router.routes.extend(mcp_routes)


@app.get("/", include_in_schema=False)
def root():
    dist = settings.frontend_dist
    if (dist / "index.html").is_file():
        return FileResponse(dist / "index.html")
    return {
        "name": settings.app_name, "version": __version__,
        "rest": settings.api_prefix, "mcp": "/mcp", "docs": "/docs",
        "frontend": "run `pnpm dev` in frontend/ or `pnpm build` to serve the SPA here",
    }


# SPA fallback — registered last so API and MCP routes always win.
# The dist directory is resolved per request, so the backend can start before
# the frontend has been built.
dist = settings.frontend_dist
if (dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    index = dist / "index.html"
    if not index.is_file():
        return JSONResponse({"detail": "Frontend build not found. Run `pnpm build` in frontend/."}, status_code=404)
    if full_path.startswith(("api/", "mcp", "docs", "redoc", "openapi.json")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    candidate = dist / full_path
    if full_path and ".." not in full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(index)


@app.exception_handler(404)
async def not_found(request: Request, exc):  # pragma: no cover
    if request.url.path.startswith(settings.api_prefix) or request.url.path.startswith("/mcp"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return JSONResponse({"detail": "Not Found"}, status_code=404)
