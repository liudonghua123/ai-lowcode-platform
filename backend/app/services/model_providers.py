"""Registry of AI model service configurations (LLM / ASR / TTS / Embedding / Rerank).

Configurations live in the ``ai_providers`` table so they can be created, updated
and switched at runtime from the UI. ``LLM_*`` environment variables remain the
bootstrap fallback: a default ``llm`` provider overrides them when present.
API keys are never returned in full — only a masked hint and a boolean flag.
"""
from __future__ import annotations

from typing import Any

from .. import db
from ..config import settings

# Category metadata drives both the backend validation and the UI tabs.
CATEGORIES: dict[str, dict[str, Any]] = {
    "llm": {
        "label": "Chat / LLM", "label_zh": "对话大模型", "icon": "sparkles",
        "description": "Chat completion models used by query / action agents and the ReAct loop.",
        "default_model": "gpt-4o-mini", "api_path": "/chat/completions",
    },
    "asr": {
        "label": "ASR / Speech-to-Text", "label_zh": "语音识别", "icon": "mic",
        "description": "Automatic speech recognition for voice input and meeting transcription.",
        "default_model": "whisper-1", "api_path": "/audio/transcriptions",
    },
    "tts": {
        "label": "TTS / Text-to-Speech", "label_zh": "语音合成", "icon": "volume",
        "description": "Text-to-speech models for spoken answers and notifications.",
        "default_model": "tts-1", "api_path": "/audio/speech",
    },
    "embedding": {
        "label": "Embedding", "label_zh": "向量嵌入", "icon": "layers",
        "description": "Embedding models for knowledge-base vectorization and semantic retrieval.",
        "default_model": "text-embedding-3-small", "api_path": "/embeddings",
    },
    "rerank": {
        "label": "Rerank", "label_zh": "重排序", "icon": "list-filter",
        "description": "Reranking models applied on top of BM25 / vector candidate retrieval.",
        "default_model": "bge-reranker-v2-m3", "api_path": "/rerank",
    },
    "vision": {
        "label": "Vision", "label_zh": "视觉理解", "icon": "eye",
        "description": "Multimodal models for image / scanned document understanding.",
        "default_model": "gpt-4o-mini", "api_path": "/chat/completions",
    },
}

CATEGORY_CODES = tuple(CATEGORIES)

VENDORS: list[dict[str, Any]] = [
    {"code": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1",
     "models": {"llm": "gpt-4o-mini", "asr": "whisper-1", "tts": "tts-1",
                "embedding": "text-embedding-3-small", "rerank": "", "vision": "gpt-4o-mini"}},
    {"code": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
     "models": {"llm": "deepseek-chat", "embedding": "", "rerank": "", "vision": ""}},
    {"code": "qwen", "name": "Alibaba Qwen / 通义千问",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "models": {"llm": "qwen-plus", "embedding": "text-embedding-v3",
                "rerank": "gte-rerank-v2", "asr": "paraformer-v2", "tts": "cosyvoice-v1"}},
    {"code": "zhipu", "name": "Zhipu GLM / 智谱",
     "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "models": {"llm": "glm-4-flash", "embedding": "embedding-3", "rerank": "", "vision": "glm-4v-flash"}},
    {"code": "moonshot", "name": "Moonshot / 月之暗面", "base_url": "https://api.moonshot.cn/v1",
     "models": {"llm": "moonshot-v1-8k", "embedding": "", "rerank": "", "vision": ""}},
    {"code": "ollama", "name": "Ollama (local)", "base_url": "http://127.0.0.1:11434/v1",
     "models": {"llm": "qwen2.5:7b", "embedding": "nomic-embed-text", "rerank": "", "vision": "llava"}},
    {"code": "siliconflow", "name": "SiliconFlow / 硅基流动",
     "base_url": "https://api.siliconflow.cn/v1",
     "models": {"llm": "Qwen/Qwen2.5-7B-Instruct", "embedding": "BAAI/bge-m3",
                "rerank": "BAAI/bge-reranker-v2-m3", "asr": "FunAudioLLM/SenseVoiceSmall",
                "tts": "fishaudio/fish-speech-1.5"}},
    {"code": "azure", "name": "Azure OpenAI", "base_url": "",
     "models": {"llm": "gpt-4o-mini", "embedding": "text-embedding-3-small", "tts": "tts-1"}},
    {"code": "custom", "name": "Custom / OpenAI-compatible", "base_url": "",
     "models": {}},
]

SEED_ROWS = [
    {"code": "default-llm", "name": "Platform LLM (env)", "category": "llm",
     "vendor": "custom", "base_url": "", "api_key": "", "model": "",
     "is_default": 1, "enabled": 1,
     "description": "Bootstrap LLM from LLM_* environment variables; configure a provider to override."},
    {"code": "default-asr", "name": "Whisper-compatible ASR", "category": "asr",
     "vendor": "openai", "base_url": "https://api.openai.com/v1", "model": "whisper-1",
     "is_default": 1, "enabled": 0,
     "description": "Speech-to-text endpoint (disabled until an API key is provided)."},
    {"code": "default-tts", "name": "OpenAI-compatible TTS", "category": "tts",
     "vendor": "openai", "base_url": "https://api.openai.com/v1", "model": "tts-1",
     "is_default": 1, "enabled": 0,
     "description": "Text-to-speech endpoint (disabled until an API key is provided)."},
    {"code": "default-embedding", "name": "Local BM25 (no embedding)", "category": "embedding",
     "vendor": "local", "base_url": "", "model": "bm25-local",
     "is_default": 1, "enabled": 1,
     "description": "Offline lexical retriever shipped with the platform."},
    {"code": "default-rerank", "name": "No reranker", "category": "rerank",
     "vendor": "local", "base_url": "", "model": "none",
     "is_default": 1, "enabled": 0,
     "description": "Retrieval results are returned in BM25 / vector score order."},
    {"code": "default-vision", "name": "OpenAI-compatible Vision", "category": "vision",
     "vendor": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
     "is_default": 1, "enabled": 0,
     "description": "Multimodal endpoint for image and scanned-document understanding."},
]

# ``.env`` is the source of the initial value of every category. Attribute
# names on ``config.Settings`` mirror the environment variables, so the mapping
# below is all that is needed to read them back.
ENV_FIELDS: dict[str, tuple[str, str, str]] = {
    "llm": ("llm_base_url", "llm_api_key", "llm_model"),
    "asr": ("asr_base_url", "asr_api_key", "asr_model"),
    "tts": ("tts_base_url", "tts_api_key", "tts_model"),
    "embedding": ("embedding_base_url", "embedding_api_key", "embedding_model"),
    "rerank": ("rerank_base_url", "rerank_api_key", "rerank_model"),
    "vision": ("vision_base_url", "vision_api_key", "vision_model"),
}

_SEED_BY_CATEGORY = {row["category"]: row for row in SEED_ROWS}
_ENV_MANAGED = "env_managed"


def mask(key: str | None) -> str:
    key = key or ""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}{'*' * 6}{key[-4:]}"


def _out(row: dict | None) -> dict | None:
    if row is None:
        return None
    out = db.loads(row, "config") or {}
    secret = out.pop("api_key", "") or ""
    out["has_api_key"] = bool(secret)
    out["api_key_masked"] = mask(secret)
    out["enabled"] = bool(out.get("enabled"))
    out["is_default"] = bool(out.get("is_default"))
    out["config"] = out.get("config") or {}
    out["category_label"] = CATEGORIES.get(out.get("category", ""), {}).get("label", out.get("category"))
    return out


def rows(category: str | None = None, enabled_only: bool = False) -> list[dict]:
    sql, args = "SELECT * FROM ai_providers WHERE 1=1", []
    if category:
        sql += " AND category=?"
        args.append(category)
    if enabled_only:
        sql += " AND enabled=1"
    return [_out(r) or {} for r in db.q(sql + " ORDER BY is_default DESC, id", tuple(args))]


def get(provider_id: int) -> dict | None:
    return _out(db.q1("SELECT * FROM ai_providers WHERE id=?", (provider_id,)))


def get_by_code(code: str) -> dict | None:
    return _out(db.q1("SELECT * FROM ai_providers WHERE code=?", (code,)))


def _raw(provider_id: int) -> dict | None:
    return db.q1("SELECT * FROM ai_providers WHERE id=?", (provider_id,))


def default_for(category: str, *, enabled_only: bool = False) -> dict | None:
    row = db.q1(
        "SELECT * FROM ai_providers WHERE category=? AND is_default=1"
        + (" AND enabled=1" if enabled_only else "") + " LIMIT 1", (category,))
    return _out(row)


def env_values(category: str) -> dict:
    """Raw ``.env`` bootstrap values for one category (internal use only)."""
    base_attr, key_attr, model_attr = ENV_FIELDS[category]
    return {
        "base_url": (getattr(settings, base_attr) or "").strip(),
        "api_key": (getattr(settings, key_attr) or "").strip(),
        "model": (getattr(settings, model_attr) or "").strip(),
    }


def env_defaults() -> dict[str, dict]:
    """Client-safe (masked) view of the ``.env`` bootstrap values."""
    out: dict[str, dict] = {}
    for category in CATEGORY_CODES:
        raw = env_values(category)
        out[category] = {
            "base_url": raw["base_url"],
            "model": raw["model"],
            "has_api_key": bool(raw["api_key"]),
            "api_key_masked": mask(raw["api_key"]),
            "configured": bool(raw["base_url"] and raw["api_key"]),
        }
    return out


def _env_enabled(category: str, env: dict, row: dict) -> int | None:
    """Decide the enabled flag implied by ``.env``.

    ``None`` means "leave the stored flag alone".
    """
    vendor = row.get("vendor") or ""
    base = env["base_url"] or row.get("base_url") or ""
    if env["api_key"] and base:
        return 1
    if vendor == "local":
        return 1 if (row.get("model") or "") not in {"", "none"} else None
    if category == "llm":
        return None  # the mock provider works without credentials
    if category in {"asr", "tts", "vision", "rerank"}:
        return 0
    return None


def _default_row(category: str) -> dict | None:
    row = db.q1("SELECT * FROM ai_providers WHERE category=? AND is_default=1 LIMIT 1",
                (category,))
    if row is None:
        row = db.q1("SELECT * FROM ai_providers WHERE category=? ORDER BY id LIMIT 1",
                    (category,))
    return row


def _fallback_spec(category: str) -> dict:
    meta = CATEGORIES[category]
    return {"code": f"default-{category}", "name": f"Default {meta['label']}",
            "category": category, "vendor": "custom", "base_url": "", "model": "",
            "enabled": 0, "is_default": 1, "description": ""}


def bootstrap_from_env(now: str | None = None) -> dict:
    """Apply ``.env`` as the initial value of every model-service category.

    Runs on every startup. Rows that were edited from the UI are marked
    ``env_managed: false`` and are therefore never overwritten by a restart.
    """
    now = now or db.now()
    created = refreshed = 0
    for category in CATEGORY_CODES:
        env = env_values(category)
        spec = _SEED_BY_CATEGORY.get(category) or _fallback_spec(category)
        row = _default_row(category)
        if row is None:
            db.insert("ai_providers", {
                **spec,
                "base_url": env["base_url"] or spec.get("base_url", ""),
                "model": env["model"] or spec.get("model", ""),
                "api_key": env["api_key"],
                "enabled": _env_enabled(category, env, spec) or 0,
                "config": {_ENV_MANAGED: True, "env_applied_at": now},
                "created_at": now, "updated_at": now,
            })
            created += 1
            continue
        cfg = (db.loads(row, "config") or {}).get("config") or {}
        if cfg.get(_ENV_MANAGED) is False:
            continue
        patch: dict[str, Any] = {}
        if env["base_url"] and env["base_url"] != row["base_url"]:
            patch["base_url"] = env["base_url"]
        if env["model"] and env["model"] != row["model"]:
            patch["model"] = env["model"]
        if env["api_key"] and env["api_key"] != row["api_key"]:
            patch["api_key"] = env["api_key"]
        enabled = _env_enabled(category, env, row)
        if enabled is not None and int(bool(row["enabled"])) != enabled:
            patch["enabled"] = enabled
        # A row that was never edited is environment-managed even when its
        # values already match .env — record the marker so later saves detach it.
        if patch or _ENV_MANAGED not in cfg:
            patch["config"] = {**cfg, _ENV_MANAGED: True, "env_applied_at": now}
            patch["updated_at"] = now
            db.update("ai_providers", row["id"], patch)
            refreshed += 1
    return {"created": created, "refreshed": refreshed}


def settings_view() -> dict:
    """One row per category, prefilled from the stored default or ``.env``."""
    env = env_defaults()
    items: list[dict] = []
    for category in CATEGORY_CODES:
        meta = CATEGORIES[category]
        row = _default_row(category)
        view = _out(row)
        cfg = ((db.loads(row, "config") or {}).get("config") or {}) if row else {}
        env_managed = bool(cfg.get(_ENV_MANAGED))
        base_url = (view or {}).get("base_url") or env[category]["base_url"]
        model = (view or {}).get("model") or env[category]["model"] or meta["default_model"]
        has_key = bool((view or {}).get("has_api_key") or env[category]["has_api_key"])
        vendor = (view or {}).get("vendor") or "custom"
        ready = bool(has_key and base_url) or (
            vendor == "local" and model not in {"", "none"}) or (
            category == "llm" and settings.llm_provider == "mock")
        items.append({
            "category": category, "label": meta["label"], "label_zh": meta["label_zh"],
            "default_model": meta["default_model"],
            "provider_id": (view or {}).get("id"),
            "provider_code": (view or {}).get("code"),
            "provider_name": (view or {}).get("name"),
            "vendor": vendor,
            "enabled": bool((view or {}).get("enabled")),
            "base_url": base_url, "model": model,
            "has_api_key": has_key,
            "api_key_masked": (view or {}).get("api_key_masked", ""),
            "env_managed": env_managed,
            "source": "env" if env_managed else ("manual" if view else "none"),
            "ready": ready,
            "env": env[category],
        })
    runtime = effective_llm()
    return {
        "categories": items,
        "runtime": {"provider": runtime["provider"], "model": runtime["model"],
                    "base_url": runtime["base_url"],
                    "config_source": runtime["source"],
                    "temperature": runtime["temperature"],
                    "has_api_key": bool(runtime["api_key"])},
    }


def save_settings(items: list[dict]) -> dict:
    """Persist the Settings-page edits onto each category's default row."""
    now = db.now()
    saved = 0
    for item in items:
        category = item.get("category")
        if category not in CATEGORIES:
            raise ValueError(f"category must be one of {', '.join(CATEGORY_CODES)}")
        spec = _SEED_BY_CATEGORY.get(category) or _fallback_spec(category)
        row = _default_row(category)
        if row is None:
            db.insert("ai_providers", {
                **spec,
                "base_url": str(item.get("base_url") or "").strip(),
                "model": str(item.get("model") or spec.get("model") or "").strip(),
                "api_key": str(item.get("api_key") or "").strip(),
                "enabled": int(bool(item.get("enabled", True))),
                "config": {_ENV_MANAGED: False},
                "created_at": now, "updated_at": now,
            })
            saved += 1
            continue
        patch: dict[str, Any] = {}
        for field in ("base_url", "model"):
            if field in item:
                value = str(item.get(field) or "").strip()
                if value != (row.get(field) or ""):
                    patch[field] = value
        key = str(item.get("api_key") or "").strip()
        if key and key != mask(row.get("api_key")):
            patch["api_key"] = key
        if item.get("enabled") is not None:
            flag = int(bool(item["enabled"]))
            if flag != int(bool(row.get("enabled"))):
                patch["enabled"] = flag
        if patch:
            cfg = db.loads(row, "config") or {}
            patch["config"] = {**cfg, _ENV_MANAGED: False}
            patch["updated_at"] = now
            db.update("ai_providers", row["id"], patch)
            saved += 1
    return {**settings_view(), "saved": saved}


def effective_llm() -> dict:
    """Runtime LLM settings: default provider overrides the environment defaults."""
    base = {"provider": settings.llm_provider, "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key, "model": settings.llm_model,
            "temperature": settings.llm_temperature, "source": "environment"}
    row = default_for("llm")
    if not row or not row.get("enabled"):
        return base
    raw = _raw(row["id"]) or {}
    if raw.get("base_url"):
        base["base_url"] = raw["base_url"]
    if raw.get("api_key"):
        base["api_key"] = raw["api_key"]
    if raw.get("model"):
        base["model"] = raw["model"]
    if base["api_key"] and base["provider"] == "mock":
        base["provider"] = "openai-compatible"
    if raw.get("config"):
        cfg = (db.loads(dict(raw), "config") or {}).get("config") or {}
        if isinstance(cfg.get("temperature"), (int, float)):
            base["temperature"] = float(cfg["temperature"])
    base["source"] = f"provider:{row['code']}"
    return base


def _normalize(body: dict, existing: dict | None = None) -> dict:
    data = dict(body)
    category = data.get("category") or (existing or {}).get("category")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(CATEGORY_CODES)}")
    data["category"] = category
    if "name" in data and not str(data["name"]).strip():
        raise ValueError("name is required")
    # A masked / empty key means "keep the stored secret".
    key = data.get("api_key")
    if key is None or key == "" or (existing and key == mask(existing.get("api_key"))):
        data.pop("api_key", None)
    for flag in ("enabled", "is_default"):
        if flag in data and data[flag] is not None:
            data[flag] = int(bool(data[flag]))
    if "config" in data and data["config"] is None:
        data["config"] = {}
    return data


def create(body: dict) -> dict:
    data = _normalize(body)
    code = str(data.get("code") or "").strip()
    if not code:
        raise ValueError("code is required")
    if db.q1("SELECT id FROM ai_providers WHERE code=?", (code,)):
        raise ValueError(f"Provider code already exists: {code}")
    now = db.now()
    data.update({"created_at": now, "updated_at": now})
    pid = db.insert("ai_providers", data)
    if data.get("is_default"):
        set_default(pid)
    return get(pid) or {}


def update(provider_id: int, body: dict) -> dict:
    existing = _raw(provider_id)
    if not existing:
        raise ValueError("Provider not found")
    data = _normalize(body, existing)
    data.pop("code", None)  # immutable identity
    # Editing connection details detaches the row from ``.env`` bootstrapping.
    if {"base_url", "api_key", "model", "enabled"} & set(data):
        cfg = (db.loads(existing, "config") or {}).get("config") or {}
        data["config"] = {**cfg, **(data.get("config") or {}), _ENV_MANAGED: False}
    data["updated_at"] = db.now()
    db.update("ai_providers", provider_id, data)
    if data.get("is_default"):
        set_default(provider_id)
    return get(provider_id) or {}


def delete(provider_id: int) -> bool:
    row = _raw(provider_id)
    if not row:
        return False
    db.delete("ai_providers", provider_id)
    if row["is_default"]:
        next_row = db.q1("SELECT id FROM ai_providers WHERE category=? ORDER BY id LIMIT 1",
                         (row["category"],))
        if next_row:
            set_default(next_row["id"])
    return True


def set_default(provider_id: int) -> dict:
    row = _raw(provider_id)
    if not row:
        raise ValueError("Provider not found")
    db.run("UPDATE ai_providers SET is_default=0, updated_at=? WHERE category=? AND id!=?",
           (db.now(), row["category"], provider_id))
    db.update("ai_providers", provider_id, {"is_default": 1, "enabled": 1,
                                             "updated_at": db.now()})
    return get(provider_id) or {}


def test(provider_id: int, *, live: bool = False) -> dict:
    """Validate configuration; optionally probe the endpoint with a short timeout."""
    row = _raw(provider_id)
    if not row:
        raise ValueError("Provider not found")
    checks = [
        {"name": "name", "ok": bool(row["name"])},
        {"name": "category", "ok": row["category"] in CATEGORIES},
        {"name": "model", "ok": bool(row["model"])},
        {"name": "base_url", "ok": bool(row["base_url"]) or row["vendor"] in {"local", "custom"}},
        {"name": "api_key", "ok": bool(row["api_key"]) or row["vendor"] == "local"},
    ]
    result: dict[str, Any] = {
        "ok": all(c["ok"] for c in checks), "checks": checks,
        "provider": row["code"], "category": row["category"],
        "mode": "live" if live else "configuration", "endpoint": row["base_url"] or None,
    }
    if live and row["base_url"] and row["api_key"]:
        try:
            import httpx

            with httpx.Client(timeout=4) as client:
                r = client.get(f"{row['base_url'].rstrip('/')}/models",
                               headers={"Authorization": f"Bearer {row['api_key']}"})
                result["reachable"] = r.status_code < 500
                result["http_status"] = r.status_code
        except Exception as exc:
            result["reachable"] = False
            result["error"] = str(exc)[:160]
    else:
        result["reachable"] = None
        result["note"] = "Static configuration check only; no network request was made."
    return result


def meta() -> dict:
    defaults = {}
    for category in CATEGORY_CODES:
        row = default_for(category)
        defaults[category] = {"code": row["code"], "name": row["name"],
                              "model": row["model"], "enabled": row["enabled"]} if row else None
    counts = {r["category"]: r["count"] for r in db.q(
        "SELECT category, COUNT(*) AS count FROM ai_providers GROUP BY category")}
    return {
        "categories": [{"code": k, **v, "count": counts.get(k, 0)} for k, v in CATEGORIES.items()],
        "vendors": VENDORS, "defaults": defaults,
        "env": env_defaults(),
        "total": int(db.scalar("SELECT COUNT(*) FROM ai_providers") or 0),
        "effective_llm": {k: v for k, v in effective_llm().items() if k != "api_key"}
        | {"has_api_key": bool(effective_llm()["api_key"])},
    }
