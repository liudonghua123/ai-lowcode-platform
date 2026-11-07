"""Built-in installable MCP skill catalog and default skill file templates.

A skill is a registered MCP server plus a set of editable files (manifest,
config, tool declarations and documentation). The catalog below ships five
ready-to-install examples; installing one materializes its files both in the
database and as an on-disk mirror under ``data/skills/<code>/``.
"""
from __future__ import annotations

import json

CATALOG_SPECS: list[dict] = [
    {
        "code": "web-search", "name": "Web Search / 联网搜索", "type": "http",
        "version": "1.2.0", "description": "Search the public web and return grounded excerpts.",
        "endpoint": "http://127.0.0.1:9201/mcp",
        "capabilities": ["search", "fetch", "citation"],
        "tools": [{"name": "search_web", "description": "Search the web for a query"},
                  {"name": "fetch_page", "description": "Fetch and extract a web page"}],
    },
    {
        "code": "filesystem", "name": "Filesystem / 文件系统", "type": "stdio",
        "version": "1.0.0", "description": "Read and list files inside a sandboxed workspace directory.",
        "command": "npx -y @modelcontextprotocol/server-filesystem ./data",
        "capabilities": ["read", "list", "stat"],
        "tools": [{"name": "read_file", "description": "Read a text file"},
                  {"name": "list_directory", "description": "List directory entries"}],
    },
    {
        "code": "sqlite-query", "name": "SQLite Query / 数据库查询", "type": "stdio",
        "version": "0.9.1", "description": "Run read-only SQL queries against a local SQLite database.",
        "command": "uvx mcp-server-sqlite --db-path ./data/platform.db",
        "capabilities": ["query", "schema"],
        "tools": [{"name": "read_query", "description": "Execute a SELECT query"},
                  {"name": "list_tables", "description": "List database tables"}],
    },
    {
        "code": "weather", "name": "Weather / 天气服务", "type": "http",
        "version": "2.0.0", "description": "Current conditions and short-term forecasts by city.",
        "endpoint": "http://127.0.0.1:9202/mcp",
        "capabilities": ["forecast", "current"],
        "tools": [{"name": "get_weather", "description": "Current weather for a city"},
                  {"name": "get_forecast", "description": "Multi-day forecast"}],
    },
    {
        "code": "github-issues", "name": "GitHub Issues / 工单查询", "type": "http",
        "version": "1.1.0", "description": "Search and read GitHub issues through a remote MCP server.",
        "endpoint": "http://127.0.0.1:9203/mcp",
        "capabilities": ["search", "read"],
        "tools": [{"name": "search_issues", "description": "Search issues in a repository"},
                  {"name": "get_issue", "description": "Read one issue"}],
    },
]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def build_files(*, code: str, name: str, skill_type: str, version: str,
                description: str, endpoint: str | None = None,
                command: str | None = None, capabilities: list[str] | None = None,
                tools: list[dict] | None = None) -> list[dict]:
    """Return the default editable file set for a skill."""
    capabilities = capabilities or []
    tools = tools or []
    manifest = {
        "schema": "ailp.mcp.skill/1",
        "code": code, "name": name, "version": version,
        "description": description, "transport": skill_type,
        "capabilities": capabilities,
        "entrypoint": endpoint or command or "",
        "license": "MIT",
    }
    config = {
        "enabled": True, "transport": skill_type,
        "endpoint": endpoint, "command": command,
        "timeout_seconds": 30, "retry": 2,
        "auth": {"type": "bearer", "token": ""},
        "log_level": "info",
    }
    skill_md = (
        f"# {name}\n\n"
        f"{description}\n\n"
        "## Transport\n\n"
        f"- Type: `{skill_type}`\n"
        f"- Entrypoint: `{endpoint or command or 'n/a'}`\n"
        f"- Version: `{version}`\n\n"
        "## Capabilities\n\n"
        + "".join(f"- `{c}`\n" for c in capabilities)
        + "\n## Files\n\n"
        "- `manifest.json` — skill identity and capabilities\n"
        "- `config.json` — runtime connection settings\n"
        "- `tools.json` — declared tool catalog\n"
        "- `README.md` — operating notes\n\n"
        "Edit these files from the MCP Skills page. Changes are mirrored to\n"
        f"`data/skills/{code}/` on the host.\n"
    )
    readme = (
        f"# {code} — operating notes\n\n"
        "1. Install or enable the skill from the MCP Skills page.\n"
        "2. Run **Sync tools** to probe the remote server / refresh the tool list.\n"
        "3. Use **Invoke tool** or connect an MCP client to `/mcp` to call the tools.\n\n"
        "Disabling a skill keeps its files; uninstalling removes the installation\n"
        "but keeps the registry entry so it can be reinstalled.\n"
    )
    return [
        {"path": "SKILL.md", "language": "markdown", "content": skill_md},
        {"path": "manifest.json", "language": "json", "content": _json(manifest)},
        {"path": "config.json", "language": "json", "content": _json(config)},
        {"path": "tools.json", "language": "json",
         "content": _json({"tools": [{"name": t["name"], "description": t.get("description", ""),
                                      "inputSchema": {"type": "object", "properties": {}}}
                                     for t in tools]})},
        {"path": "README.md", "language": "markdown", "content": readme},
    ]


def _files_for_spec(spec: dict) -> list[dict]:
    return build_files(
        code=spec["code"], name=spec["name"], skill_type=spec["type"],
        version=spec["version"], description=spec["description"],
        endpoint=spec.get("endpoint"), command=spec.get("command"),
        capabilities=spec["capabilities"], tools=spec["tools"])


def catalog() -> list[dict]:
    out = []
    for spec in CATALOG_SPECS:
        files = _files_for_spec(spec)
        out.append({
            "code": spec["code"], "name": spec["name"], "type": spec["type"],
            "version": spec["version"], "description": spec["description"],
            "endpoint": spec.get("endpoint"), "command": spec.get("command"),
            "capabilities": spec["capabilities"], "tool_count": len(spec["tools"]),
            "file_count": len(files), "files": [f["path"] for f in files],
        })
    return out


def find(code: str) -> dict | None:
    return next((s for s in CATALOG_SPECS if s["code"] == code), None)


def files_for_code(code: str) -> list[dict]:
    spec = find(code)
    return _files_for_spec(spec) if spec else []
