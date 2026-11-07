#!/usr/bin/env bash
# Build the SPA and serve everything from a single port (http://localhost:8000).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Building frontend"
(cd "$ROOT/frontend" && pnpm build)

cd "$ROOT/backend"
PY="python3"
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; fi
echo "==> Serving http://localhost:8000  (REST /api/v1, MCP /mcp, SPA /)"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
