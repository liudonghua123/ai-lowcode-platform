"""Personal notification inbox, preferences and channel administration."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db, deps
from ..services import notify

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class ReadIn(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class PrefsIn(BaseModel):
    events: dict[str, list[str]] = Field(default_factory=dict,
                                         examples=[{"task_created": ["inapp", "webhook"]}])


@router.get("", summary="My notification inbox")
def inbox(unread: bool = False, event: str | None = None, limit: int = 50,
          user: dict = Depends(deps.get_current_user)):
    sql = "SELECT * FROM notifications WHERE recipient=?"
    params: list = [user["username"]]
    if unread:
        sql += " AND read_at IS NULL"
    if event:
        sql += " AND event=?"
        params.append(event)
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", (*params, min(max(limit, 1), 200)))
    return {"notifications": [dict(r) for r in rows],
            "total": len(rows), "unread": notify.unread_count(user["username"])}


@router.get("/unread-count", summary="Unread notification counter")
def unread(user: dict = Depends(deps.get_current_user)):
    return {"unread": notify.unread_count(user["username"])}


@router.post("/read", summary="Mark notifications as read")
def mark_read(body: ReadIn, user: dict = Depends(deps.get_current_user)):
    if body.all:
        db.run("UPDATE notifications SET read_at=? WHERE recipient=? AND read_at IS NULL",
               (db.now(), user["username"]))
        return {"ok": True, "unread": 0}
    if body.ids:
        marks = ",".join("?" for _ in body.ids)
        db.run(f"UPDATE notifications SET read_at=? WHERE recipient=? AND id IN ({marks})",
               (db.now(), user["username"], *body.ids))
    return {"ok": True, "unread": notify.unread_count(user["username"])}


@router.get("/prefs", summary="My notification preferences (event -> channels)")
def get_prefs(user: dict = Depends(deps.get_current_user)):
    return {"events": notify.prefs(user["username"]),
            "catalog": {"events": notify.EVENT_META, "channels": notify.CHANNEL_META}}


@router.put("/prefs", summary="Update my notification preferences")
def put_prefs(body: PrefsIn, user: dict = Depends(deps.get_current_user)):
    saved = notify.save_prefs(user["username"], body.events)
    deps.audit(user["username"], "notifications.prefs.update", "profile", saved)
    return {"events": saved}


@router.get("/channels", summary="Delivery channels (config visible to admins)")
def get_channels(user: dict = Depends(deps.get_current_user)):
    chs = notify.channels()
    if not user.get("is_admin"):
        # Non-admins see availability flags only, never credentials.
        return {"channels": [{"code": c["code"], "en": c["en"], "zh": c["zh"],
                              "editable": c["editable"], "ready": c["ready"]}
                             for c in chs.values()]}
    return {"channels": list(chs.values())}


@router.put("/channels", summary="Configure webhook / email delivery (admin)")
def put_channels(body: dict, user: dict = Depends(deps.require("settings:write"))):
    result = notify.save_channels(body)
    deps.audit(user["username"], "notifications.channels.update", "settings",
               {k: {kk: ("***" if "password" in kk or "secret" in kk else vv)
                    for kk, vv in (v or {}).items()} for k, v in body.items()})
    return {"channels": list(result.values())}
