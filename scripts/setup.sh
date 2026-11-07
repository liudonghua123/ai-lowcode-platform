#!/usr/bin/env bash
# Install backend (uv) and frontend (pnpm) dependencies.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Backend dependencies"
if command -v uv >/dev/null 2>&1; then
  (cd backend && uv sync --quiet || echo "[warn] uv sync failed; the system Python can be used instead")
else
  echo "[warn] uv not found; install from https://docs.astral.sh/uv/ or use pip3 install -e '.[dev]'"
fi

echo "==> Frontend dependencies"
if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm install --no-frozen-lockfile)
else
  echo "[warn] pnpm not found; use npm install instead"
  (cd frontend && npm install)
fi

echo "==> Configuration"
[ -f backend/.env ] || cp backend/.env.example backend/.env
[ -f frontend/.env ] || cp frontend/.env.example frontend/.env
echo "Done. Next: scripts/dev.sh (development) or scripts/start.sh (single-port production)."
