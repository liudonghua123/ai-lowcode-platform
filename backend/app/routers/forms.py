"""Form designer API: definitions, publishing and submissions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db, deps

router = APIRouter(prefix="/forms", tags=["Forms"])

FIELD_TYPES = ["text", "textarea", "number", "select", "multiselect", "date", "datetime",
               "switch", "radio", "user", "department", "table", "attachment", "divider"]


class FormIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str
    description: str | None = None
    status: str = "draft"
    schema_: list[dict] = Field(default_factory=list, alias="schema")
    layout: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class FormPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    schema_: list[dict] | None = Field(default=None, alias="schema")
    layout: dict | None = None

    model_config = {"populate_by_name": True}


class SubmissionIn(BaseModel):
    data: dict


def _out(row: dict) -> dict:
    out = db.loads(row, "schema", "layout") or {}
    out["schema"] = out.get("schema") or []
    out["layout"] = out.get("layout") or {}
    return out


def _validate_schema(schema: list[dict]) -> None:
    keys = [f.get("key") for f in schema]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=400, detail="Field keys must be unique")
    for f in schema:
        if not f.get("key"):
            raise HTTPException(status_code=400, detail="Every field needs a key")
        if f.get("type") not in FIELD_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported field type: {f.get('type')}")


@router.get("/field-types", summary="Supported form field types")
def field_types(_user: dict = Depends(deps.require("form:read"))):
    return {"field_types": FIELD_TYPES}


@router.get("", summary="List forms")
def list_forms(status: str | None = None, q: str | None = None,
               _user: dict = Depends(deps.require("form:read"))):
    sql = "SELECT * FROM forms WHERE 1=1"
    args: list = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        sql += " AND (name LIKE ? OR code LIKE ? OR description LIKE ?)"
        args += [f"%{q}%"] * 3
    sql += " ORDER BY id DESC"
    rows = db.q(sql, tuple(args))
    return {"forms": [_out(r) for r in rows], "total": len(rows)}


@router.post("", status_code=201, summary="Create a form definition")
def create_form(body: FormIn, user: dict = Depends(deps.require("form:write")),
                request: Request = None):
    if db.q1("SELECT id FROM forms WHERE code=?", (body.code,)):
        raise HTTPException(status_code=409, detail="Form code already exists")
    _validate_schema(body.schema_)
    fid = db.insert("forms", {"code": body.code, "name": body.name,
                              "description": body.description, "status": body.status,
                              "schema": body.schema_, "layout": body.layout,
                              "version": 1, "created_by": user["username"],
                              "created_at": db.now(), "updated_at": db.now()})
    deps.audit(user["username"], "form.create", f"form:{body.code}",
               {"fields": len(body.schema_)}, request=request)
    return _out(db.q1("SELECT * FROM forms WHERE id=?", (fid,)))


@router.get("/code/{code}", summary="Get a form by code")
def get_by_code(code: str, _user: dict = Depends(deps.require("form:read"))):
    row = db.q1("SELECT * FROM forms WHERE code=?", (code,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    return _out(row)


@router.get("/{form_id}", summary="Get a form by id")
def get_form(form_id: int, _user: dict = Depends(deps.require("form:read"))):
    row = db.q1("SELECT * FROM forms WHERE id=?", (form_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    return _out(row)


@router.put("/{form_id}", summary="Update a form definition")
def update_form(form_id: int, body: FormPatch,
                user: dict = Depends(deps.require("form:write")), request: Request = None):
    row = db.q1("SELECT * FROM forms WHERE id=?", (form_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    patch = {k: v for k, v in body.model_dump(by_alias=True, exclude_none=True).items()}
    if "schema" in patch:
        _validate_schema(patch["schema"])
    patch["version"] = row["version"] + 1
    patch["updated_at"] = db.now()
    db.update("forms", form_id, patch)
    deps.audit(user["username"], "form.update", f"form:{row['code']}",
               {"version": patch["version"]}, request=request)
    return _out(db.q1("SELECT * FROM forms WHERE id=?", (form_id,)))


@router.post("/{form_id}/publish", summary="Publish a form so it accepts submissions")
def publish_form(form_id: int, user: dict = Depends(deps.require("form:publish")),
                 request: Request = None):
    row = db.q1("SELECT * FROM forms WHERE id=?", (form_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    db.update("forms", form_id, {"status": "published", "updated_at": db.now()})
    deps.audit(user["username"], "form.publish", f"form:{row['code']}", {}, request=request)
    return _out(db.q1("SELECT * FROM forms WHERE id=?", (form_id,)))


@router.delete("/{form_id}", summary="Delete a form and its submissions")
def delete_form(form_id: int, user: dict = Depends(deps.require("form:write")),
                request: Request = None):
    row = db.q1("SELECT code FROM forms WHERE id=?", (form_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    db.run("DELETE FROM form_submissions WHERE form_id=?", (form_id,))
    db.delete("forms", form_id)
    deps.audit(user["username"], "form.delete", f"form:{row['code']}", {}, request=request)
    return {"ok": True}


@router.get("/{form_id}/submissions", summary="List submissions of a form")
def submissions(form_id: int, limit: int = 50,
                _user: dict = Depends(deps.require("form:read"))):
    rows = db.q("SELECT * FROM form_submissions WHERE form_id=? ORDER BY id DESC LIMIT ?",
                (form_id, min(limit, 200)))
    return {"submissions": [db.loads(r, "data") for r in rows], "total": len(rows)}


@router.post("/{form_id}/submissions", status_code=201, summary="Submit data to a published form")
def submit(form_id: int, body: SubmissionIn, user: dict = Depends(deps.require("form:submit")),
           request: Request = None):
    row = db.q1("SELECT * FROM forms WHERE id=?", (form_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    if row["status"] != "published":
        raise HTTPException(status_code=400, detail="Only published forms accept submissions")
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    missing = [str(f.get("label") or f.get("key")) for f in schema
               if f.get("required") and not body.data.get(f.get("key"))]
    if missing:
        raise HTTPException(status_code=400, detail="Missing required fields: " + ", ".join(missing))
    sid = db.insert("form_submissions", {"form_id": form_id, "data": body.data,
                                         "status": "submitted", "submitted_by": user["username"],
                                         "created_at": db.now()})
    deps.audit(user["username"], "form.submit", f"form:{row['code']}",
               {"submission_id": sid}, request=request)
    return {"submission_id": sid, "status": "submitted", "data": body.data}
