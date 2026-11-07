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
]


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
        "total": int(db.scalar("SELECT COUNT(*) FROM ai_providers") or 0),
        "effective_llm": {k: v for k, v in effective_llm().items() if k != "api_key"}
        | {"has_api_key": bool(effective_llm()["api_key"])},
    }
