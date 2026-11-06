"""Environment driven configuration (python-dotenv + os.environ).

All settings can be overridden at runtime by the ``settings`` table through
``app.services.settings_store``; this module holds the bootstrap defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env", override=False)
load_dotenv(ROOT_DIR / ".env", override=False)


def _bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(key: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(key, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI Low-Code Platform")
    app_env: str = os.getenv("APP_ENV", "development")
    api_prefix: str = os.getenv("API_PREFIX", "/api/v1")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    cors_origins: list[str] = field(default_factory=lambda: _list(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))
    db_path: str = os.getenv("DB_PATH", "./data/platform.db")
    secret_key: str = os.getenv("SECRET_KEY", "dev-only-secret-change-me")
    access_token_ttl: int = int(os.getenv("ACCESS_TOKEN_TTL", "7200"))
    mfa_token_ttl: int = int(os.getenv("MFA_TOKEN_TTL", "300"))
    bootstrap_admin: str = os.getenv("BOOTSTRAP_ADMIN", "admin")
    bootstrap_admin_password: str = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "admin123")
    bootstrap_admin_email: str = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "admin@platform.local")

    mfa_required: bool = _bool("MFA_REQUIRED", False)
    mfa_methods: list[str] = field(default_factory=lambda: _list("MFA_METHODS", "otp,passkey"))
    mfa_enforced_roles: list[str] = field(default_factory=lambda: _list("MFA_ENFORCED_ROLES", ""))
    mfa_enforced_users: list[str] = field(default_factory=lambda: _list("MFA_ENFORCED_USERS", ""))
    passkey_rp_id: str = os.getenv("PASSKEY_RP_ID", "localhost")
    passkey_rp_name: str = os.getenv("PASSKEY_RP_NAME", "AI Low-Code Platform")
    passkey_origin: str = os.getenv("PASSKEY_ORIGIN", "http://localhost:5173")

    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    agentscope_enabled: bool = _bool("AGENTSCOPE_ENABLED", True)
    rag_top_k: int = int(os.getenv("RAG_TOP_K", "4"))

    mcp_enabled: bool = _bool("MCP_ENABLED", True)
    mcp_stateless: bool = _bool("MCP_STATELESS", True)
    mcp_json_response: bool = _bool("MCP_JSON_RESPONSE", True)
    mcp_external_servers: list[str] = field(default_factory=lambda: _list("MCP_EXTERNAL_SERVERS", ""))

    cas_server_url: str = os.getenv("CAS_SERVER_URL", "")
    cas_version: str = os.getenv("CAS_VERSION", "3")
    oauth2_client_id: str = os.getenv("OAUTH2_CLIENT_ID", "")
    oauth2_client_secret: str = os.getenv("OAUTH2_CLIENT_SECRET", "")
    oauth2_authorize_url: str = os.getenv("OAUTH2_AUTHORIZE_URL", "")
    oauth2_token_url: str = os.getenv("OAUTH2_TOKEN_URL", "")
    oauth2_userinfo_url: str = os.getenv("OAUTH2_USERINFO_URL", "")
    oidc_issuer: str = os.getenv("OIDC_ISSUER", "")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")
    oidc_discovery_url: str = os.getenv("OIDC_DISCOVERY_URL", "")
    wecom_corp_id: str = os.getenv("WECOM_CORP_ID", "")
    wecom_agent_id: str = os.getenv("WECOM_AGENT_ID", "")
    wecom_secret: str = os.getenv("WECOM_SECRET", "")
    dingtalk_app_key: str = os.getenv("DINGTALK_APP_KEY", "")
    dingtalk_app_secret: str = os.getenv("DINGTALK_APP_SECRET", "")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    @property
    def resolved_db_path(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = BACKEND_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def frontend_dist(self) -> Path:
        return ROOT_DIR / "frontend" / "dist"


settings = Settings()
