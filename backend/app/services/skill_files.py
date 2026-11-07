"""Editable files attached to an MCP skill.

The SQLite table is authoritative; ``data/skills/<code>/`` is a best-effort
on-disk mirror so the files can also be inspected or edited by the host.
Paths are validated to prevent traversal outside a skill directory.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .. import db
from ..config import settings
from . import skill_catalog

_SAFE_PATH = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
MAX_CONTENT = 200_000

_LANGUAGES = {
    "md": "markdown", "json": "json", "yaml": "yaml", "yml": "yaml",
    "py": "python", "js": "javascript", "ts": "typescript",
    "sh": "bash", "txt": "text", "toml": "toml", "env": "text",
}


def validate_path(path: str) -> str:
    clean = (path or "").strip().replace("\\", "/").lstrip("/")
    if (not clean or not _SAFE_PATH.fullmatch(clean)
            or ".." in clean.split("/") or "//" in clean):
        raise ValueError("Invalid skill file path")
    return clean


def language_for(path: str) -> str:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _LANGUAGES.get(suffix, "text")


def root() -> Path:
    return Path(settings.resolved_db_path).parent / "skills"


def skill_dir(code: str) -> Path:
    return root() / code


def _target(code: str, path: str) -> Path:
    base = skill_dir(code).resolve()
    target = (base / validate_path(path)).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Path escapes skill directory")
    return target


def _write_disk(code: str, path: str, content: str) -> None:
    try:
        target = _target(code, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except (OSError, ValueError):
        pass  # disk mirror is optional


def _delete_disk(code: str, path: str) -> None:
    try:
        _target(code, path).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def list_files(skill_id: int) -> list[dict]:
    return db.q("SELECT id, path, language, size, updated_at "
                "FROM mcp_skill_files WHERE skill_id=? ORDER BY path", (skill_id,))


def get_file(skill_id: int, path: str) -> dict | None:
    return db.q1("SELECT * FROM mcp_skill_files WHERE skill_id=? AND path=?",
                 (skill_id, validate_path(path)))


def put_file(skill_id: int, code: str, path: str, content: str) -> dict:
    path = validate_path(path)
    content = content or ""
    if len(content) > MAX_CONTENT:
        raise ValueError(f"File exceeds {MAX_CONTENT} characters")
    fields = {"content": content, "language": language_for(path),
              "size": len(content.encode("utf-8")), "updated_at": db.now()}
    existing = get_file(skill_id, path)
    if existing:
        db.update("mcp_skill_files", existing["id"], fields)
        file_id = existing["id"]
    else:
        file_id = db.insert("mcp_skill_files", {"skill_id": skill_id, "path": path, **fields})
    _write_disk(code, path, content)
    return db.q1("SELECT * FROM mcp_skill_files WHERE id=?", (file_id,)) or {}


def delete_file(skill_id: int, code: str, path: str) -> bool:
    path = validate_path(path)
    cur = db.run("DELETE FROM mcp_skill_files WHERE skill_id=? AND path=?", (skill_id, path))
    _delete_disk(code, path)
    return cur.rowcount > 0


def clear_files(skill_id: int, code: str) -> int:
    count = int(db.scalar("SELECT COUNT(*) FROM mcp_skill_files WHERE skill_id=?", (skill_id,)) or 0)
    db.run("DELETE FROM mcp_skill_files WHERE skill_id=?", (skill_id,))
    try:
        shutil.rmtree(skill_dir(code), ignore_errors=True)
    except OSError:
        pass
    return count


def install_files(skill: dict) -> int:
    """(Re)create the default editable file set for a skill."""
    sid, code = skill["id"], skill["code"]
    clear_files(sid, code)
    files = skill_catalog.files_for_code(code) or skill_catalog.build_files(
        code=code, name=skill.get("name") or code,
        skill_type=skill.get("type") or "http",
        version=skill.get("version") or "1.0.0",
        description=skill.get("description") or "",
        endpoint=skill.get("endpoint"), command=skill.get("command"))
    for item in files:
        put_file(sid, code, item["path"], item["content"])
    return len(files)


def ensure_files(skill: dict) -> int:
    """Create default files only when the skill has none (idempotent bootstrap)."""
    sid = skill["id"]
    if int(db.scalar("SELECT COUNT(*) FROM mcp_skill_files WHERE skill_id=?", (sid,)) or 0):
        return 0
    files = skill_catalog.files_for_code(skill["code"]) or skill_catalog.build_files(
        code=skill["code"], name=skill.get("name") or skill["code"],
        skill_type=skill.get("type") or "http",
        version=skill.get("version") or "1.0.0",
        description=skill.get("description") or "",
        endpoint=skill.get("endpoint"), command=skill.get("command"))
    for item in files:
        put_file(sid, skill["code"], item["path"], item["content"])
    return len(files)


def bootstrap() -> dict:
    """Ensure every installed skill has an editable file set. Called at startup."""
    rows = db.q("SELECT * FROM mcp_skills WHERE status IS NULL OR status!='uninstalled'")
    created = sum(ensure_files(row) for row in rows)
    return {"skills": len(rows), "files_created": created}


def reload_from_disk(skill: dict) -> int:
    """Re-read mirrored files back into the database."""
    sid, code = skill["id"], skill["code"]
    base = skill_dir(code).resolve()
    if not base.is_dir():
        return 0
    loaded = 0
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        try:
            relative = validate_path(relative)
            put_file(sid, code, relative, path.read_text(encoding="utf-8"))
            loaded += 1
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    return loaded
