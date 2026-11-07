"""AI Low-Code Platform — FastAPI application entry point.

* REST API           -> /api/v1/*
* MCP streamable HTTP -> /mcp  (fastmcp SDK, with builtin JSON-RPC fallback)
* SPA (built frontend) -> /    (served when frontend/dist exists)

Run:  uv run uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from . import __version__, db, deps, security, seed
from .config import settings
from .mcp_server import build_mcp
from .routers import agents, audit, auth, forms, knowledge, mcp, meta, rbac, workflows
from .services import mcp_tools

mcp_routes, mcp_http_app, mcp_mode = build_mcp()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    seeded = seed.seed_if_empty()
    if seeded:
        print(f"[boot] database initialized: {settings.resolved_db_path}")
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


class MCPAuthASGIMiddleware:
    """Bind an optional bearer token to the MCP tool context (pure ASGI, streaming safe)."""

    def __init__(self, wrapped_app):
        self.wrapped_app = wrapped_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            token = headers.get("authorization", "")
            if token.lower().startswith("bearer "):
                try:
                    payload = security.jwt_decode(token.split(" ", 1)[1].strip(), "access")
                    user = deps._load_user(payload.get("sub"))
                    if user:
                        mcp_tools.bind_user(user)
                except ValueError:
                    pass
        await self.wrapped_app(scope, receive, send)


app.add_middleware(MCPAuthASGIMiddleware)

for r in (auth.router, rbac.router, forms.router, workflows.router, knowledge.router,
          agents.router, mcp.router, audit.router, meta.router, meta.settings_router):
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
