"""Form designer API: definitions, rules engine, versions, submissions, print/export.

Beyond basic CRUD this now covers the domestic form feature set: a rich field
catalog, server-side statutory validation (PRC ID / mobile / USCC / bank card),
RMB amount-in-words, safe formulas, detail-table summaries, conditional display
and conditional-required rules, per-node field permissions, version snapshots,
mobile rendering, document numbers, CSV export and a print view.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import db, deps
from ..services import data_scope, form_catalog, form_rules

router = APIRouter(prefix="/forms", tags=["Forms"])

FIELD_TYPES = form_catalog.FIELD_TYPES


class FormIn(BaseModel):
    code: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str
    description: str | None = None
    status: str = "draft"
    schema_: list[dict] = Field(default_factory=list, alias="schema")
    layout: dict = Field(default_factory=dict)
    print_template: dict = Field(default_factory=dict)
    settings: dict = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class FormPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    schema_: list[dict] | None = Field(default=None, alias="schema")
    layout: dict | None = None
    print_template: dict | None = None
    settings: dict | None = None

    model_config = {"populate_by_name": True}


class SubmissionIn(BaseModel):
    data: dict = Field(default_factory=dict)
    node_config: dict | None = None
    flow_instance_id: int | None = None


class EvaluateIn(BaseModel):
    data: dict = Field(default_factory=dict)
    node_config: dict | None = None
    check_unique: bool = False


class VersionIn(BaseModel):
    note: str | None = None
    version: int | None = None  # when present, restore this snapshot


class SubmissionPatch(BaseModel):
    status: str


def _out(row: dict) -> dict:
    out = db.loads(row, "schema", "layout", "print_template", "settings") or {}
    out["schema"] = out.get("schema") or []
    out["layout"] = out.get("layout") or {}
    out["print_template"] = out.get("print_template") or {}
    out["settings"] = out.get("settings") or {}
    out["field_count"] = len(out["schema"])
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
        if f.get("type") == "formula":
            try:
                form_rules.safe_eval(f.get("formula") or "0", {})
            except Exception as exc:
                raise HTTPException(status_code=400,
                                    detail=f"Invalid formula on {f.get('key')}: {exc}") from exc


def _snapshot(form: dict, actor: str, note: str | None = None) -> int:
    return db.insert("form_versions", {
        "form_id": form["id"], "version": form["version"],
        "schema": form["schema"] if isinstance(form["schema"], str) else db.dumps(form["schema"]),
        "layout": form["layout"] if isinstance(form["layout"], str) else db.dumps(form["layout"]),
        "print_template": form.get("print_template") or "{}",
        "settings": form.get("settings") or "{}",
        "note": note, "created_by": actor, "created_at": db.now()})


def _form_or_404(form_id: int) -> dict:
    row = db.q1("SELECT * FROM forms WHERE id=?", (form_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    return dict(row)


# --------------------------------------------------------------------------- #
# Metadata (all static paths must precede /{form_id})
# --------------------------------------------------------------------------- #
@router.get("/meta", summary="Form field catalog, validators, operators and functions")
def form_meta(lang: str = Query("en", pattern="^(en|zh)$"),
              _user: dict = Depends(deps.require("form:read"))):
    data = form_catalog.catalog(lang)
    data["groups"] = [{"code": g["code"], "label": g["label"],
                       "fields": [f["type"] for f in data["fields"] if f["group"] == g["code"]]}
                      for g in data["groups"]]
    data["field_count"] = len(data["fields"])
    data["region_levels"] = 3
    return data


@router.get("/field-types", summary="Supported form field types")
def field_types(_user: dict = Depends(deps.require("form:read"))):
    return {"field_types": FIELD_TYPES, "total": len(FIELD_TYPES)}


@router.get("/regions", summary="Administrative division sample for region fields")
def regions(_user: dict = Depends(deps.require("form:read"))):
    return {"regions": form_catalog.REGIONS, "levels": 3,
            "note": "Sample GB/T 2260 subset; full data can be supplied through form settings."}


@router.get("", summary="List forms")
def list_forms(status: str | None = None, q: str | None = None,
               _user: dict = Depends(deps.require("form:read"))):
    sql, args = "SELECT * FROM forms WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        sql += " AND (name LIKE ? OR code LIKE ? OR description LIKE ?)"
        args += [f"%{q}%"] * 3
    rows = db.q(sql + " ORDER BY id DESC", tuple(args))
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
                              "print_template": body.print_template, "settings": body.settings,
                              "version": 1, "created_by": user["username"],
                              "created_at": db.now(), "updated_at": db.now()})
    _snapshot(_form_or_404(fid), user["username"], "initial")
    deps.audit(user["username"], "form.create", f"form:{body.code}",
               {"fields": len(body.schema_)}, request=request)
    return _out(_form_or_404(fid))


@router.get("/code/{code}", summary="Get a form by code")
def get_by_code(code: str, _user: dict = Depends(deps.require("form:read"))):
    row = db.q1("SELECT * FROM forms WHERE code=?", (code,))
    if not row:
        raise HTTPException(status_code=404, detail="Form not found")
    return _out(row)


# --------------------------------------------------------------------------- #
# Definition rules / versions / render
# --------------------------------------------------------------------------- #
@router.post("/{form_id}/evaluate", summary="Evaluate formulas, visibility and validation live")
def evaluate(form_id: int, body: EvaluateIn,
             _user: dict = Depends(deps.require("form:read"))):
    row = _form_or_404(form_id)
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    result = form_rules.validate_data(schema, body.data, form_id=form_id,
                                      node_config=body.node_config,
                                      check_unique=body.check_unique)
    return {"ok": not result["errors"], **result}


@router.post("/{form_id}/validate", summary="Validate a payload without storing it")
def validate(form_id: int, body: EvaluateIn,
             _user: dict = Depends(deps.require("form:read"))):
    row = _form_or_404(form_id)
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    result = form_rules.validate_data(schema, body.data, form_id=form_id,
                                      node_config=body.node_config,
                                      check_unique=body.check_unique)
    return {"valid": not result["errors"], "errors": result["errors"],
            "computed": result["computed"], "hidden": result["hidden"]}


@router.get("/{form_id}/versions", summary="List form definition snapshots")
def versions(form_id: int, _user: dict = Depends(deps.require("form:read"))):
    _form_or_404(form_id)
    rows = db.q("SELECT * FROM form_versions WHERE form_id=? ORDER BY version DESC", (form_id,))
    return {"versions": [db.loads(r, "schema", "layout", "print_template", "settings") for r in rows],
            "total": len(rows)}


@router.post("/{form_id}/versions", status_code=201, summary="Snapshot or restore a form version")
def save_version(form_id: int, body: VersionIn,
                 user: dict = Depends(deps.require("form:write")), request: Request = None):
    row = _form_or_404(form_id)
    if body.version is not None:
        snap = db.q1("SELECT * FROM form_versions WHERE form_id=? AND version=?",
                     (form_id, body.version))
        if not snap:
            raise HTTPException(status_code=404, detail="Version not found")
        snap = db.loads(snap, "schema", "layout", "print_template", "settings")
        version = row["version"] + 1
        db.update("forms", form_id, {"schema": snap.get("schema") or [],
                                     "layout": snap.get("layout") or {},
                                     "print_template": snap.get("print_template") or {},
                                     "settings": snap.get("settings") or {},
                                     "version": version, "updated_at": db.now()})
        _snapshot(_form_or_404(form_id), user["username"],
                  f"restored from v{body.version}")
        deps.audit(user["username"], "form.restore", f"form:{row['code']}",
                   {"version": version, "from": body.version}, request=request)
        return _out(_form_or_404(form_id))
    _snapshot(row, user["username"], body.note)
    return {"ok": True, "version": row["version"]}


@router.get("/{form_id}/render", summary="Rendered schema for desktop/mobile with node permissions")
def render(form_id: int, platform: str = Query("desktop", pattern="^(desktop|mobile)$"),
           node_config: str | None = None,
           _user: dict = Depends(deps.require("form:read"))):
    row = _form_or_404(form_id)
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    cfg: dict | None = None
    if node_config:
        try:
            cfg = json.loads(node_config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid node_config JSON") from exc
    return {"form": {"code": row["code"], "name": row["name"], "version": row["version"]},
            **form_rules.render_schema(schema, platform=platform, node_config=cfg)}


@router.get("/{form_id}/print/{submission_id}", summary="Structured print view with RMB in words")
def print_view(form_id: int, submission_id: int,
               user: dict = Depends(deps.require("form:read"))):
    row = _form_or_404(form_id)
    sub = db.q1("SELECT * FROM form_submissions WHERE id=? AND form_id=?",
                (submission_id, form_id))
    if not sub or not data_scope.row_visible(user, "form_submissions", sub):
        raise HTTPException(status_code=404, detail="Submission not found")
    sub = db.loads(sub, "data", "computed") or {}
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    data = sub.get("data") or {}
    computed = sub.get("computed") or {}
    if not computed:
        computed = form_rules.validate_data(schema, data, check_unique=False)["computed"]
    fields = [{"key": f.get("key"), "label": f.get("label") or f.get("key"),
               "value": data.get(f.get("key")), "type": f.get("type"),
               "upper": computed.get(f"{f.get('key')}_upper"),
               "info": computed.get(f"{f.get('key')}_info")}
              for f in schema if f.get("type") not in form_catalog.LAYOUT_TYPES]
    return {"form": {"code": row["code"], "name": row["name"], "version": row["version"]},
            "template": (db.loads(row, "print_template") or {}).get("print_template") or {},
            "serial_no": sub.get("serial_no"), "submitted_by": sub.get("submitted_by"),
            "created_at": sub.get("created_at"), "fields": fields,
            "summaries": form_rules.compute_details(schema, data)[1],
            "computed": computed}


# --------------------------------------------------------------------------- #
# Definition CRUD
# --------------------------------------------------------------------------- #
@router.get("/{form_id}", summary="Get a form by id")
def get_form(form_id: int, _user: dict = Depends(deps.require("form:read"))):
    return _out(_form_or_404(form_id))


@router.put("/{form_id}", summary="Update a form definition (auto version snapshot)")
def update_form(form_id: int, body: FormPatch,
                user: dict = Depends(deps.require("form:write")), request: Request = None):
    row = _form_or_404(form_id)
    patch = {k: v for k, v in body.model_dump(by_alias=True, exclude_none=True).items()}
    if "schema" in patch:
        _validate_schema(patch["schema"])
    patch["version"] = row["version"] + 1
    patch["updated_at"] = db.now()
    db.update("forms", form_id, patch)
    _snapshot(_form_or_404(form_id), user["username"], "before update v" + str(row["version"]))
    deps.audit(user["username"], "form.update", f"form:{row['code']}",
               {"version": patch["version"]}, request=request)
    return _out(_form_or_404(form_id))


@router.post("/{form_id}/publish", summary="Publish a form so it accepts submissions")
def publish_form(form_id: int, user: dict = Depends(deps.require("form:publish")),
                 request: Request = None):
    row = _form_or_404(form_id)
    db.update("forms", form_id, {"status": "published", "updated_at": db.now()})
    _snapshot(_form_or_404(form_id), user["username"], "published")
    deps.audit(user["username"], "form.publish", f"form:{row['code']}", {}, request=request)
    return _out(_form_or_404(form_id))


@router.delete("/{form_id}", summary="Delete a form, versions and submissions")
def delete_form(form_id: int, user: dict = Depends(deps.require("form:write")),
                request: Request = None):
    row = _form_or_404(form_id)
    db.run("DELETE FROM form_submissions WHERE form_id=?", (form_id,))
    db.run("DELETE FROM form_versions WHERE form_id=?", (form_id,))
    db.delete("forms", form_id)
    deps.audit(user["username"], "form.delete", f"form:{row['code']}", {}, request=request)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Submissions
# --------------------------------------------------------------------------- #
def _sub_out(row: dict) -> dict:
    out = db.loads(row, "data", "computed") or {}
    out["data"] = out.get("data") or {}
    out["computed"] = out.get("computed") or {}
    return out


@router.get("/{form_id}/submissions", summary="List submissions of a form")
def submissions(form_id: int, limit: int = 50, status: str | None = None,
                q: str | None = None, user: dict = Depends(deps.require("form:read"))):
    _form_or_404(form_id)
    frag, scope_args = data_scope.owner_clause(user, "form_submissions", "s")
    sql = "SELECT s.* FROM form_submissions s WHERE s.form_id=?" + (f" AND {frag}" if frag else "")
    args: list = [form_id, *scope_args]
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        sql += " AND (data LIKE ? OR serial_no LIKE ? OR submitted_by LIKE ?)"
        args += [f"%{q}%"] * 3
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, min(limit, 200)))
    return {"submissions": [_sub_out(r) for r in rows], "total": len(rows)}


@router.get("/{form_id}/submissions/export", summary="Export submissions as CSV")
def export_submissions(form_id: int, user: dict = Depends(deps.require("form:read"))):
    row = _form_or_404(form_id)
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    keys = [f.get("key") for f in schema
            if f.get("key") and f.get("type") not in form_catalog.LAYOUT_TYPES]
    frag, scope_args = data_scope.owner_clause(user, "form_submissions")
    rows = db.q("SELECT * FROM form_submissions WHERE form_id=?" +
                (f" AND {frag}" if frag else "") + " ORDER BY id", (form_id, *scope_args))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["#", "serial_no", "status", "submitted_by", "created_at", *keys])
    for r in rows:
        d = db.loads(r, "data") or {}
        data = d.get("data") or {}
        writer.writerow([r["id"], r["serial_no"] or "", r["status"], r["submitted_by"] or "",
                         r["created_at"], *(json.dumps(data.get(k), ensure_ascii=False)
                                            if isinstance(data.get(k), (list, dict))
                                            else (data.get(k) if data.get(k) is not None else "")
                                            for k in keys)])
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{row["code"]}.csv"'})


@router.post("/{form_id}/submissions", status_code=201,
             summary="Validate, compute and store a submission")
def submit(form_id: int, body: SubmissionIn,
           user: dict = Depends(deps.require("form:submit")), request: Request = None):
    row = _form_or_404(form_id)
    if row["status"] != "published":
        raise HTTPException(status_code=400, detail="Only published forms accept submissions")
    schema = (db.loads(row, "schema") or {}).get("schema") or []
    serial_fields = [f for f in schema if f.get("type") == "serial"]
    serial_no = form_rules.serial_number(row["code"], serial_fields[0].get("serial")
                                         if serial_fields else None) if serial_fields else None
    result = form_rules.validate_data(schema, body.data, form_id=form_id,
                                      node_config=body.node_config, serial_no=serial_no)
    if result["errors"]:
        raise HTTPException(status_code=400,
                            detail="; ".join(f"{e['key']}: {e['message']}" for e in result["errors"]))
    sid = db.insert("form_submissions", {
        "form_id": form_id, "data": result["data"], "computed": result["computed"],
        "status": "submitted", "submitted_by": user["username"],
        "form_version": row["version"], "serial_no": serial_no,
        "flow_instance_id": body.flow_instance_id,
        "updated_at": db.now(), "created_at": db.now()})
    deps.audit(user["username"], "form.submit", f"form:{row['code']}",
               {"submission_id": sid, "serial_no": serial_no}, request=request)
    return {"submission_id": sid, "status": "submitted", "serial_no": serial_no,
            "data": result["data"], "computed": result["computed"],
            "summaries": result["summaries"], "hidden": result["hidden"]}


@router.patch("/{form_id}/submissions/{submission_id}", summary="Update a submission status")
def patch_submission(form_id: int, submission_id: int, body: SubmissionPatch,
                     user: dict = Depends(deps.require("form:write")), request: Request = None):
    if body.status not in {"submitted", "approved", "rejected", "archived", "draft"}:
        raise HTTPException(status_code=400, detail="Invalid submission status")
    row = db.q1("SELECT id FROM form_submissions WHERE id=? AND form_id=?",
                (submission_id, form_id))
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found")
    db.update("form_submissions", submission_id,
              {"status": body.status, "updated_at": db.now()})
    deps.audit(user["username"], "form.submission.status", f"form:{form_id}",
               {"submission_id": submission_id, "status": body.status}, request=request)
    return _sub_out(db.q1("SELECT * FROM form_submissions WHERE id=?", (submission_id,)))


def submission_by_instance(instance_id: int) -> dict[str, Any] | None:
    row = db.q1("SELECT * FROM form_submissions WHERE flow_instance_id=?", (instance_id,))
    return _sub_out(row) if row else None
