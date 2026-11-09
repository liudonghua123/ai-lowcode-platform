"""Audit log queries."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db, deps
from ..services import data_scope

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/logs", summary="Query audit logs")
def logs(actor: str | None = None, action: str | None = None, level: str | None = None,
         q: str | None = None, limit: int = 100,
         user: dict = Depends(deps.require("audit:read"))):
    frag, scope_args = data_scope.owner_clause(user, "audit_logs")
    sql = "SELECT * FROM audit_logs WHERE 1=1" + (f" AND {frag}" if frag else "")
    args: list = list(scope_args)
    for field, value in (("actor", actor), ("action", action), ("level", level)):
        if value:
            sql += f" AND {field}=?"
            args.append(value)
    if q:
        sql += " AND (action LIKE ? OR resource LIKE ? OR detail LIKE ?)"
        args += [f"%{q}%"] * 3
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", tuple(args) + (min(limit, 500),))
    return {"logs": [db.loads(r, "detail") for r in rows], "total": len(rows)}


@router.get("/actions", summary="Distinct audit actions")
def actions(_user: dict = Depends(deps.require("audit:read"))):
    rows = db.q("SELECT DISTINCT action FROM audit_logs ORDER BY action")
    return {"actions": [r["action"] for r in rows]}
