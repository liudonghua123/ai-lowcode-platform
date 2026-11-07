"""Lightweight SQLite persistence layer.

A single, dependency-free data access layer keeps the platform runnable with
nothing but the standard library. JSON columns are (de)serialized transparently
through ``insert`` / ``update`` / ``loads`` helpers.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import settings

_local = threading.local()
_write_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  email TEXT,
  display_name TEXT,
  avatar TEXT,
  password_hash TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  dept TEXT,
  role_ids TEXT NOT NULL DEFAULT '[]',
  otp_secret TEXT,
  otp_enabled INTEGER NOT NULL DEFAULT 0,
  passkey_enabled INTEGER NOT NULL DEFAULT 0,
  passkeys TEXT NOT NULL DEFAULT '[]',
  external_id TEXT,
  provider TEXT DEFAULT 'local',
  last_login_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  permission_ids TEXT NOT NULL DEFAULT '[]',
  builtin INTEGER NOT NULL DEFAULT 0,
  mfa_required INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  resource TEXT NOT NULL,
  action TEXT NOT NULL,
  description TEXT
);
CREATE TABLE IF NOT EXISTS auth_providers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  config TEXT NOT NULL DEFAULT '{}',
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  schema TEXT NOT NULL DEFAULT '[]',
  layout TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS form_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  form_id INTEGER NOT NULL,
  data TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'submitted',
  submitted_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  graph TEXT NOT NULL DEFAULT '{"nodes":[],"edges":[]}',
  version INTEGER NOT NULL DEFAULT 1,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_instances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workflow_id INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  context TEXT NOT NULL DEFAULT '{}',
  logs TEXT NOT NULL DEFAULT '[]',
  started_by TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS kb_collections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  embedding_model TEXT DEFAULT 'bm25-local',
  chunk_size INTEGER DEFAULT 480,
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collection_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  source TEXT,
  status TEXT NOT NULL DEFAULT 'indexed',
  chunks TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  mode TEXT NOT NULL DEFAULT 'hybrid',
  model TEXT,
  system_prompt TEXT,
  temperature REAL DEFAULT 0.3,
  kb_ids TEXT NOT NULL DEFAULT '[]',
  skill_ids TEXT NOT NULL DEFAULT '[]',
  workflow_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id INTEGER NOT NULL,
  title TEXT,
  messages TEXT NOT NULL DEFAULT '[]',
  user_id TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_skills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'http',
  endpoint TEXT,
  command TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  auth_config TEXT NOT NULL DEFAULT '{}',
  tools TEXT NOT NULL DEFAULT '[]',
  health TEXT NOT NULL DEFAULT 'unknown',
  last_sync_at TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'installed',
  version TEXT NOT NULL DEFAULT '1.0.0',
  source TEXT NOT NULL DEFAULT 'manual',
  description TEXT NOT NULL DEFAULT '',
  manifest TEXT NOT NULL DEFAULT '{}',
  installed_at TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS mcp_call_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT,
  method TEXT NOT NULL DEFAULT 'tools/call',
  tool TEXT,
  source TEXT NOT NULL DEFAULT 'mcp',
  transport TEXT,
  actor TEXT,
  arguments TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'success',
  error TEXT,
  result_preview TEXT,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_skill_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  skill_id INTEGER NOT NULL,
  path TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT 'text',
  size INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  UNIQUE(skill_id, path)
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT,
  action TEXT NOT NULL,
  resource TEXT,
  detail TEXT NOT NULL DEFAULT '{}',
  ip TEXT,
  level TEXT NOT NULL DEFAULT 'info',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sso_states (
  state TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  redirect_uri TEXT,
  nonce TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mfa_challenges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  kind TEXT NOT NULL,
  challenge TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  expires_at INTEGER NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_submissions_form ON form_submissions(form_id);
CREATE INDEX IF NOT EXISTS idx_instances_wf ON workflow_instances(workflow_id);
CREATE INDEX IF NOT EXISTS idx_kbdocs_collection ON kb_documents(collection_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_calls_created ON mcp_call_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_calls_tool ON mcp_call_logs(tool);
CREATE INDEX IF NOT EXISTS idx_skill_files_skill ON mcp_skill_files(skill_id);
"""

# Columns added after the first release. SQLite cannot add them through
# CREATE TABLE IF NOT EXISTS on an existing database, so we migrate lazily.
MIGRATIONS: dict[str, dict[str, str]] = {
    "mcp_skills": {
        "status": "TEXT NOT NULL DEFAULT 'installed'",
        "version": "TEXT NOT NULL DEFAULT '1.0.0'",
        "source": "TEXT NOT NULL DEFAULT 'manual'",
        "description": "TEXT NOT NULL DEFAULT ''",
        "manifest": "TEXT NOT NULL DEFAULT '{}'",
        "installed_at": "TEXT",
        "updated_at": "TEXT",
    },
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def uid() -> str:
    return uuid.uuid4().hex


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(str(settings.resolved_db_path), check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = _connect()
        _local.conn = c
    return c


def _enc(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def q(sql: str, args: tuple | list = ()) -> list[dict]:
    cur = conn().execute(sql, tuple(args))
    return [dict(r) for r in cur.fetchall()]


def q1(sql: str, args: tuple | list = ()) -> dict | None:
    cur = conn().execute(sql, tuple(args))
    row = cur.fetchone()
    return dict(row) if row else None


def scalar(sql: str, args: tuple | list = ()) -> Any:
    row = conn().execute(sql, tuple(args)).fetchone()
    return row[0] if row else None


def run(sql: str, args: tuple | list = ()) -> sqlite3.Cursor:
    with _write_lock:
        cur = conn().execute(sql, tuple(args))
        conn().commit()
        return cur


def insert(table: str, data: dict) -> int:
    data = {k: _enc(v) for k, v in data.items()}
    cols = ",".join(data.keys())
    marks = ",".join("?" for _ in data)
    cur = run(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
    return int(cur.lastrowid)


def update(table: str, row_id: Any, data: dict, id_col: str = "id") -> int:
    if not data:
        return 0
    data = {k: _enc(v) for k, v in data.items()}
    sets = ",".join(f"{k}=?" for k in data)
    cur = run(f"UPDATE {table} SET {sets} WHERE {id_col}=?", tuple(data.values()) + (row_id,))
    return cur.rowcount


def delete(table: str, row_id: Any, id_col: str = "id") -> int:
    cur = run(f"DELETE FROM {table} WHERE {id_col}=?", (row_id,))
    return cur.rowcount


def loads(row: dict | None, *fields: str) -> dict | None:
    """Deserialize JSON columns in a row (returns a copy)."""
    if row is None:
        return None
    out = dict(row)
    for f in fields:
        v = out.get(f)
        if isinstance(v, str) and v:
            try:
                out[f] = json.loads(v)
            except (ValueError, TypeError):
                pass
        elif v in (None, ""):
            out[f] = [] if f.endswith("_ids") or f in {"schema", "chunks", "tools", "passkeys", "messages", "logs", "nodes", "edges"} else {}
    return out


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _migrate() -> None:
    """Add columns introduced after the initial schema (idempotent)."""
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in q(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in existing:
                run(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    conn().executescript(SCHEMA)
    conn().commit()
    _migrate()


def is_empty() -> bool:
    return int(scalar("SELECT COUNT(*) FROM users") or 0) == 0
