#!/usr/bin/env bash
# Build the SPA and serve everything from a single port (http://localhost:8000).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Building frontend"
(cd "$ROOT/frontend" && pnpm build)

cd "$ROOT/backend"
PY="python3"
# Prefer the project venv, but only when it actually has the runtime deps
# installed; a bare `uv venv` stub would otherwise fail at import time.
if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import uvicorn" 2>/dev/null; then
  PY=".venv/bin/python"
fi
echo "==> Serving http://localhost:8000  (REST /api/v1, MCP /mcp, SPA /)"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
