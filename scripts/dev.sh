#!/usr/bin/env bash
# Start backend (:8000) + Vite dev server (:5173) together.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

PY="python3"
# Prefer the project venv, but only when it actually has the runtime deps
# installed; a bare `uv venv` stub would otherwise fail at import time.
if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import uvicorn" 2>/dev/null; then
  PY=".venv/bin/python"
fi

echo "==> Backend API  http://localhost:8000  (docs: /docs, MCP: /mcp)"
"$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACK_PID=$!

cd "$ROOT/frontend"
echo "==> Frontend dev http://localhost:5173"
pnpm dev &
FRONT_PID=$!

cleanup() { kill "$BACK_PID" "$FRONT_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
wait
