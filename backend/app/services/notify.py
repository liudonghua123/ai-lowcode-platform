"""Notification hub: in-app inbox plus best-effort webhook / email channels.

Every flow event (task created, decision, urge, cc, timeout, completion,
withdrawal) funnels through :func:`emit`. Delivery never raises — a broken
channel must not break a running approval. Channel credentials are stored in
the ``settings`` table under ``notify_channels`` (ADR-0011).
"""
from __future__ import annotations

import json
import smtplib
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from typing import Any

from .. import db

CHANNEL_META = [
    {"code": "inapp", "en": "In-app inbox", "zh": "站内通知", "editable": False},
    {"code": "webhook", "en": "Webhook (HTTP POST)", "zh": "Webhook 推送", "editable": True},
    {"code": "email", "en": "Email (SMTP)", "zh": "邮件（SMTP）", "editable": True},
]

EVENT_META = [
    {"code": "task_created", "en": "An approval task is assigned to me", "zh": "收到待办审批任务"},
    {"code": "task_result", "en": "An instance I started reached a decision", "zh": "我发起的流程产生审批结果"},
    {"code": "urged", "en": "I am urged to review a pending task", "zh": "收到催办提醒"},
    {"code": "cc", "en": "I am cc-ed on an instance", "zh": "被抄送流程"},
    {"code": "timeout", "en": "One of my tasks timed out", "zh": "我的任务超时提醒"},
    {"code": "instance_completed", "en": "An instance I started finished", "zh": "我发起的流程已完结"},
    {"code": "withdrawn", "en": "An instance I should review was withdrawn", "zh": "待办流程被发起人撤回"},
]

DEFAULT_CHANNELS: dict[str, dict[str, Any]] = {
    "webhook": {"enabled": False, "url": "", "secret": ""},
    "email": {"enabled": False, "smtp_host": "", "smtp_port": 587,
              "username": "", "password": "", "from_addr": "",
              "recipients_override": ""},
}

EVENT_CODES = [e["code"] for e in EVENT_META]
CHANNEL_CODES = [c["code"] for c in CHANNEL_META]


def _settings_row() -> dict:
    row = db.q1("SELECT value FROM settings WHERE key='notify_channels'")
    if not row:
        return {}
    try:
        return json.loads(row["value"]) or {}
    except ValueError:
        return {}


def channels() -> dict:
    """Effective channel config = defaults merged with saved values."""
    saved = _settings_row()
    out: dict[str, dict[str, Any]] = {}
    for code in CHANNEL_CODES:
        cfg = dict(DEFAULT_CHANNELS.get(code) or {})
        cfg.update(saved.get(code) or {})
        meta = next(c for c in CHANNEL_META if c["code"] == code)
        out[code] = {**meta, "config": cfg, "ready": _ready(code, cfg)}
    return out


def _ready(code: str, cfg: dict) -> bool:
    if code == "inapp":
        return True
    if code == "webhook":
        return bool(cfg.get("enabled") and cfg.get("url"))
    if code == "email":
        return bool(cfg.get("enabled") and cfg.get("smtp_host") and cfg.get("from_addr"))
    return False


def save_channels(patch: dict) -> dict:
    saved = _settings_row()
    for code, cfg in (patch or {}).items():
        if code not in CHANNEL_CODES or code == "inapp":
            continue
        merged = dict(DEFAULT_CHANNELS.get(code) or {})
        merged.update(saved.get(code) or {})
        merged.update({k: v for k, v in (cfg or {}).items() if k != "code"})
        saved[code] = merged
    db.run("INSERT INTO settings(key,value,updated_at) VALUES('notify_channels',?,?) "
           "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
           (db.dumps(saved), db.now()))
    return channels()


def default_prefs() -> dict:
    return {code: ["inapp"] for code in EVENT_CODES}


def prefs(username: str) -> dict:
    row = db.q1("SELECT events FROM notify_prefs WHERE username=?", (username,))
    saved = (db.loads(row, "events") or {}).get("events") or {} if row else {}
    out = default_prefs()
    for code, chans in (saved or {}).items():
        if code in out and isinstance(chans, list):
            out[code] = [c for c in chans if c in CHANNEL_CODES]
    return out


def save_prefs(username: str, events: dict) -> dict:
    clean: dict[str, list[str]] = {}
    for code, chans in (events or {}).items():
        if code in EVENT_CODES and isinstance(chans, list):
            clean[code] = [c for c in chans if c in CHANNEL_CODES]
    db.run("INSERT INTO notify_prefs(username,events,updated_at) VALUES(?,?,?) "
           "ON CONFLICT(username) DO UPDATE SET events=excluded.events, "
           "updated_at=excluded.updated_at", (username, db.dumps(clean), db.now()))
    return prefs(username)


def _wants(username: str, event: str, channel: str) -> bool:
    return channel in (prefs(username).get(event) or [])


def _deliver_webhook(payload: dict) -> dict:
    cfg = (channels().get("webhook") or {}).get("config") or {}
    if not _ready("webhook", cfg):
        return {"sent": 0, "reason": "not configured"}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        cfg["url"], data=body, method="POST",
        headers={"Content-Type": "application/json",
                 **({"X-AILP-Secret": cfg["secret"]} if cfg.get("secret") else {})})
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return {"sent": 1, "status": resp.status}
    except Exception as exc:  # never break the flow
        return {"sent": 0, "error": str(exc)[:200]}


def _deliver_email(title: str, body: str, recipients: list[str]) -> dict:
    cfg = (channels().get("email") or {}).get("config") or {}
    if not _ready("email", cfg):
        return {"sent": 0, "reason": "not configured"}
    to = [r for r in (cfg.get("recipients_override") or "").split(",") if r.strip()] \
        or recipients
    rows = db.q(f"SELECT email FROM users WHERE username IN "
                f"({','.join('?' for _ in to)})", to)
    emails = [r["email"] for r in rows if r["email"]]
    if not emails:
        return {"sent": 0, "reason": "no email addresses"}
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = cfg["from_addr"]
        msg["To"] = ",".join(emails)
        with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port") or 587),
                          timeout=6) as smtp:
            smtp.starttls()
            if cfg.get("username"):
                smtp.login(cfg["username"], cfg.get("password") or "")
            smtp.send_message(msg)
        return {"sent": len(emails)}
    except Exception as exc:
        return {"sent": 0, "error": str(exc)[:200]}


def emit(event: str, recipients: list[str], title: str, body: str = "",
         ref_type: str = "", ref_id: str = "") -> dict:
    """Record in-app inbox rows and push through enabled extra channels."""
    if event not in EVENT_CODES:
        event = "task_result"
    names, seen = [], set()
    for name in recipients or []:
        if name and name != "system" and name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        return {"event": event, "inapp": 0, "webhook": None, "email": None}
    now = db.now()
    rows = 0
    for name in names:
        db.insert("notifications", {"recipient": name, "event": event, "title": title,
                                    "body": body, "ref_type": ref_type,
                                    "ref_id": ref_id, "created_at": now})
        rows += 1
    payload = {"event": event, "recipients": names, "title": title, "body": body,
               "ref_type": ref_type, "ref_id": ref_id, "at": now}
    webhook = _deliver_webhook(payload) if any(
        _wants(n, event, "webhook") for n in names) else None
    email = _deliver_email(title, body, names) if any(
        _wants(n, event, "email") for n in names) else None
    return {"event": event, "inapp": rows, "webhook": webhook, "email": email}


def unread_count(username: str) -> int:
    return int(db.scalar(
        "SELECT COUNT(*) FROM notifications WHERE recipient=? AND read_at IS NULL",
        (username,)) or 0)
