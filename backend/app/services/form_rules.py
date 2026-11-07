"""Validation, formula, linkage, visibility and field-permission engine for forms.

Everything here is standard-library only and deliberately avoids ``eval``:
formulas are parsed into a restricted AST and evaluated against a whitelist of
functions. That keeps user-authored expressions runnable but sandbox-safe.
"""
from __future__ import annotations

import ast
import math
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from .. import db

_IDCARD_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_IDCARD_CHECK = "10X98765432"
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

_MOBILE = re.compile(r"^1[3-9]\d{9}$")
_TEL = re.compile(r"^(?:0\d{2,3}-?)?\d{7,8}(?:-\d{1,5})?$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_URL = re.compile(r"^https?://[^\s]+$", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Chinese amount-in-words and statutory identifier helpers
# --------------------------------------------------------------------------- #
def cny_upper(value: Any) -> str:
    """Convert a number to RMB uppercase, e.g. 1234.56 -> 壹仟贰佰叁拾肆元伍角陆分."""
    try:
        num = round(float(value), 2)
    except (TypeError, ValueError):
        return ""
    if num < 0:
        return "负" + cny_upper(-num)
    if num >= 1_000_000_000_000:
        return "金额超出范围"
    digits = "零壹贰叁肆伍陆柒捌玖"
    int_units = ["", "拾", "佰", "仟", "万", "拾", "佰", "仟", "亿", "拾", "佰", "仟"]
    yuan = int(num)
    cents = int(round((num - yuan) * 100))
    jiao, fen = divmod(cents, 10)

    def section(n: int) -> str:
        out, zero = "", False
        for i in range(4):
            d = n % 10
            if d:
                out = digits[d] + int_units[i] + ("零" if zero else "") + out
                zero = False
            elif out:
                zero = True
            n //= 10
        return out

    if yuan == 0:
        head = "零元"
    else:
        groups, rest = [], yuan
        while rest > 0:
            groups.append(rest % 10000)
            rest //= 10000
        parts = []
        for idx in range(len(groups) - 1, -1, -1):
            g = groups[idx]
            if g:
                parts.append(section(g) + ["", "万", "亿", "兆"][idx])
            elif parts:
                parts.append("零")
        head = "".join(parts).rstrip("零") + "元"
        if not parts:
            head = "零元"
    if jiao == 0 and fen == 0:
        return head + "整"
    tail = (digits[jiao] + "角" if jiao else ("零" if fen else "")) + (digits[fen] + "分" if fen else "")
    return head + tail


def idcard_check(value: Any) -> tuple[bool, dict]:
    s = str(value or "").strip().upper()
    if len(s) != 18 or not s[:17].isdigit() or s[17] not in "0123456789X":
        return False, {}
    total = sum(int(s[i]) * _IDCARD_WEIGHTS[i] for i in range(17))
    if _IDCARD_CHECK[total % 11] != s[17]:
        return False, {}
    try:
        birthday = date(int(s[6:10]), int(s[10:12]), int(s[12:14]))
    except ValueError:
        return False, {}
    today = date.today()
    age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
    return True, {"birthday": birthday.isoformat(), "gender": "男" if int(s[16]) % 2 else "女", "age": age}


def uscc_check(value: Any) -> bool:
    s = str(value or "").strip().upper()
    if len(s) != 18 or any(c not in _USCC_CHARS for c in s):
        return False
    total = sum(_USCC_CHARS.index(s[i]) * _USCC_WEIGHTS[i] for i in range(17))
    check = (31 - total % 31) % 31
    return _USCC_CHARS[check] == s[17]


def luhn_check(value: Any) -> bool:
    s = re.sub(r"\D", "", str(value or ""))
    if not 12 <= len(s) <= 19:
        return False
    total, alt = 0, False
    for ch in reversed(s):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


# --------------------------------------------------------------------------- #
# Restricted expression evaluator
# --------------------------------------------------------------------------- #
_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b if b else 0,
           ast.Mod: lambda a, b: a % b if b else 0, ast.Pow: lambda a, b: a ** b}
_CMPOPS = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
           ast.Gt: lambda a, b: _num(a) > _num(b), ast.GtE: lambda a, b: _num(a) >= _num(b),
           ast.Lt: lambda a, b: _num(a) < _num(b), ast.LtE: lambda a, b: _num(a) <= _num(b),
           ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _flatten(args: Any) -> list:
    out: list = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(_flatten(a))
        else:
            out.append(a)
    return out


def _functions(variables: dict) -> dict[str, Callable[..., Any]]:
    def table_sum(table: Any, column: str = "") -> float:
        rows = variables.get(str(table)) or []
        if isinstance(rows, dict):
            rows = rows.get("rows") or []
        return sum(_num(r.get(column)) for r in rows if isinstance(r, dict))

    def datediff(a: Any, b: Any) -> int:
        def parse(v: Any) -> date | None:
            try:
                return datetime.fromisoformat(str(v)[:10]).date()
            except ValueError:
                return None
        da, dbb = parse(a), parse(b)
        return (da - dbb).days if da and dbb else 0

    return {
        "SUM": lambda *a: sum(_num(x) for x in _flatten(a)),
        "AVG": lambda *a: (lambda v: sum(_num(x) for x in v) / len(v) if v else 0)(_flatten(a)),
        "MIN": lambda *a: min((_num(x) for x in _flatten(a)), default=0),
        "MAX": lambda *a: max((_num(x) for x in _flatten(a)), default=0),
        "ROUND": lambda x, n=2: round(_num(x), int(_num(n))),
        "ABS": lambda x: abs(_num(x)),
        "IF": lambda cond, a, b: a if cond else b,
        "CONCAT": lambda *a: "".join(str(x) for x in _flatten(a)),
        "LEN": lambda x: len(x) if x is not None else 0,
        "CNY_UPPER": lambda x: cny_upper(x),
        "TABLE_SUM": table_sum,
        "COUNT": lambda t: len((variables.get(str(t)) or {}).get("rows", [])
                               if isinstance(variables.get(str(t)), dict)
                               else (variables.get(str(t)) or [])),
        "DATEDIFF": datediff,
        "TODAY": lambda: date.today().isoformat(),
        "NOW": lambda: datetime.now().isoformat(timespec="seconds"),
        "NUMBER": lambda x: _num(x),
        "INT": lambda x: int(_num(x)),
        "FLOAT": lambda x: _num(x),
        "STR": lambda x: str(x),
    }


def safe_eval(expr: str | None, variables: dict) -> Any:
    """Evaluate a formula against a whitelist AST; return None on any error."""
    if not expr or not str(expr).strip():
        return None
    funcs = _functions(variables)

    def walk(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return variables.get(node.id, 0)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp):
            v = walk(node.operand)
            if isinstance(node.op, ast.USub):
                return -_num(v)
            if isinstance(node.op, ast.UAdd):
                return _num(v)
            if isinstance(node.op, ast.Not):
                return not v
        if isinstance(node, ast.BoolOp):
            vals = [walk(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.Compare):
            left = walk(node.left)
            for op, comp in zip(node.ops, node.comparators, strict=False):
                right = walk(comp)
                if type(op) not in _CMPOPS or not _CMPOPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return walk(node.body) if walk(node.test) else walk(node.orelse)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
            args = [walk(a) for a in node.args]
            kwargs = {kw.arg: walk(kw.value) for kw in node.keywords if kw.arg}
            return funcs[node.func.id](*args, **kwargs)
        if isinstance(node, (ast.List, ast.Tuple)):
            return [walk(e) for e in node.elts]
        if isinstance(node, ast.Dict):
            return {walk(k): walk(v) for k, v in zip(node.keys, node.values, strict=False)}
        if isinstance(node, ast.Subscript):
            container, idx = walk(node.value), walk(node.slice)
            try:
                return container[idx]
            except (KeyError, IndexError, TypeError):
                return 0
        raise ValueError("unsupported expression element")

    try:
        tree = ast.parse(str(expr), mode="eval")
        value = walk(tree)
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return 0
        return value
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Condition / visibility rules
# --------------------------------------------------------------------------- #
def _compare(actual: Any, operator: str, expected: Any) -> bool:
    a = actual if actual is not None else ""
    try:
        if operator in {"gt", "gte", "lt", "lte"}:
            x, y = _num(a), _num(expected)
            return {"gt": x > y, "gte": x >= y, "lt": x < y, "lte": x <= y}[operator]
        if operator == "eq":
            return str(a) == str(expected)
        if operator == "ne":
            return str(a) != str(expected)
        if operator == "contains":
            return str(expected) in str(a)
        if operator == "not_contains":
            return str(expected) not in str(a)
        if operator == "in":
            items = expected if isinstance(expected, list) else [expected]
            return str(a) in [str(x) for x in items]
        if operator == "not_in":
            items = expected if isinstance(expected, list) else [expected]
            return str(a) not in [str(x) for x in items]
        if operator == "empty":
            return a in (None, "", [], {})
        if operator == "not_empty":
            return a not in (None, "", [], {})
    except (TypeError, ValueError):
        return False
    return False


def check_rule(rule: dict | None, data: dict) -> bool:
    """A rule is {logic: and|or, conditions: [{field, operator, value}]}."""
    if not rule:
        return True
    conds = rule.get("conditions")
    if not conds and rule.get("field"):  # backward-compatible single condition
        conds = [rule]
    if not conds:
        return True
    results = [_compare(data.get(c.get("field")), c.get("operator") or "eq", c.get("value"))
               for c in conds]
    return all(results) if (rule.get("logic") or "and").lower() != "or" else any(results)


def visible_keys(schema: list[dict], data: dict) -> tuple[set[str], set[str]]:
    """Return (visible, hidden) field keys after applying display rules."""
    hidden: set[str] = set()
    for field in schema:
        key = field.get("key")
        if not key:
            continue
        rule = field.get("visible_when") or field.get("display_rule")
        if rule and not check_rule(rule, data):
            hidden.add(key)
    return {f.get("key") for f in schema if f.get("key")} - hidden, hidden


def applied_permissions(schema: list[dict], node_config: dict | None = None,
                        data: dict | None = None) -> dict[str, str]:
    """Field permissions for an approval node: editable / readonly / hidden."""
    cfg = node_config or {}
    perms: dict[str, str] = {}
    declared = cfg.get("field_permissions") or {}
    for field in schema:
        key = field.get("key")
        if not key:
            continue
        mode = declared.get(key)
        if not mode and data is not None:
            # A field-level default may be overridden per node.
            candidate = field.get("permission")
            mode = candidate if candidate in {"editable", "readonly", "hidden"} else None
        perms[key] = mode or "editable"
    return perms


# --------------------------------------------------------------------------- #
# Detail table computation
# --------------------------------------------------------------------------- #
def compute_details(schema: list[dict], data: dict) -> tuple[dict, dict]:
    """Compute row formulas and column summaries for every detail table."""
    out = dict(data)
    summaries: dict[str, Any] = {}
    for field in schema:
        if field.get("type") != "table":
            continue
        key = field.get("key")
        rows = data.get(key)
        if isinstance(rows, dict):
            rows = rows.get("rows")
        if not isinstance(rows, list):
            continue
        columns = field.get("columns") or []
        computed_rows = []
        for raw in rows:
            row = dict(raw) if isinstance(raw, dict) else {}
            for col in columns:
                if col.get("type") == "formula" and col.get("formula"):
                    value = safe_eval(col["formula"], {**row, **data, **out})
                    row[col.get("key")] = round(value, 2) if isinstance(value, float) else value
            computed_rows.append(row)
        out[key] = computed_rows
        for item in field.get("summary") or []:
            col_key, op = item.get("column"), (item.get("op") or "sum").lower()
            values = [_num(r.get(col_key)) for r in computed_rows]
            total = {"sum": sum(values), "avg": sum(values) / len(values) if values else 0,
                     "count": len(values), "max": max(values, default=0),
                     "min": min(values, default=0)}.get(op, sum(values))
            out[f"{key}_{item.get('key') or 'total'}"] = round(total, 2)
            summaries[f"{key}_{item.get('key') or 'total'}"] = round(total, 2)
    return out, summaries


# --------------------------------------------------------------------------- #
# Main validation + computation pipeline
# --------------------------------------------------------------------------- #
def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _builtin_error(ftype: str, value: Any) -> str | None:
    s = str(value or "").strip()
    checks = {
        "idcard": (lambda: idcard_check(value)[0], "身份证号校验失败"),
        "mobile": (lambda: bool(_MOBILE.match(s)), "手机号格式不正确"),
        "tel": (lambda: bool(_TEL.match(s)), "固定电话格式不正确"),
        "email": (lambda: bool(_EMAIL.match(s)), "邮箱格式不正确"),
        "url": (lambda: bool(_URL.match(s)), "网址格式不正确"),
        "bankcard": (lambda: luhn_check(value), "银行卡号校验失败"),
        "uscc": (lambda: uscc_check(value), "统一社会信用代码校验失败"),
    }
    if ftype in checks:
        ok, msg = checks[ftype]
        return None if ok() else msg
    return None


def validate_data(schema: list[dict], data: dict, *, form_id: int | None = None,
                  exclude_submission: int | None = None, node_config: dict | None = None,
                  check_unique: bool = True, serial_no: str | None = None) -> dict:
    """Validate + compute a form payload.

    Returns ``{data, errors, visible, hidden, permissions, summaries, computed}``.
    Hidden fields are stripped from the stored payload; readonly fields cannot be
    modified while an approval node is active.
    """
    payload = dict(data or {})
    _, hidden = visible_keys(schema, payload)
    perms = applied_permissions(schema, node_config, payload)
    errors: list[dict] = []
    computed: dict[str, Any] = {}

    clean: dict = {k: v for k, v in payload.items() if k not in hidden}
    for key in hidden:
        clean.pop(key, None)

    # 1) detail tables first, so formulas can reference their summaries
    clean, summaries = compute_details(schema, clean)

    # 2) computed / derived fields
    for field in schema:
        key, ftype = field.get("key"), field.get("type")
        if not key or key in hidden or ftype in {"divider", "description", "grid", "tabs", "collapse"}:
            continue
        if ftype == "serial":
            clean[key] = serial_no or clean.get(key) or ""
            computed[key] = clean[key]
        elif ftype == "formula" or field.get("formula"):
            if perms.get(key) == "readonly" and payload.get(key) not in (None, ""):
                clean[key] = payload[key]
            else:
                value = safe_eval(field.get("formula"), {**clean, "data": clean})
                clean[key] = round(value, 2) if isinstance(value, float) else value
                computed[key] = clean[key]
        if ftype == "amount" and not _is_empty(clean.get(key)):
            computed[f"{key}_upper"] = cny_upper(clean[key])
        elif ftype == "idcard" and not _is_empty(clean.get(key)):
            ok, info = idcard_check(clean[key])
            if ok:
                computed[f"{key}_info"] = info

    # 3) per-field validation
    for field in schema:
        key, ftype = field.get("key"), field.get("type")
        if not key or key in hidden or ftype in {"divider", "description", "grid", "tabs", "collapse"}:
            continue
        value = clean.get(key)
        required = bool(field.get("required"))
        if field.get("required_when"):
            required = required or check_rule(field["required_when"], clean)
        if required and _is_empty(value) and ftype not in {"formula", "serial"}:
            errors.append({"key": key, "rule": "required",
                           "message": f"{field.get('label') or key} 为必填项"})
            continue
        if _is_empty(value):
            continue
        err = _builtin_error(ftype, value)
        if err:
            errors.append({"key": key, "rule": ftype, "message": err})
            continue
        rules = field.get("validation") or {}
        if ftype in {"number", "amount", "slider", "rate"}:
            try:
                n = float(value)
                if "min" in rules and n < float(rules["min"]):
                    errors.append({"key": key, "rule": "min", "message": f"不能小于 {rules['min']}"})
                if "max" in rules and n > float(rules["max"]):
                    errors.append({"key": key, "rule": "max", "message": f"不能大于 {rules['max']}"})
                if "precision" in rules and round(n, int(rules["precision"])) != n:
                    errors.append({"key": key, "rule": "precision",
                                   "message": f"最多 {rules['precision']} 位小数"})
            except (TypeError, ValueError):
                errors.append({"key": key, "rule": "number", "message": "必须为数字"})
        if isinstance(value, str):
            if "min_length" in rules and len(value) < int(rules["min_length"]):
                errors.append({"key": key, "rule": "min_length", "message": "长度不足"})
            if "max_length" in rules and len(value) > int(rules["max_length"]):
                errors.append({"key": key, "rule": "max_length", "message": "长度超限"})
            if "regex" in rules:
                try:
                    if not re.search(str(rules["regex"]), value):
                        errors.append({"key": key, "rule": "regex", "message": "格式不匹配"})
                except re.error:
                    errors.append({"key": key, "rule": "regex", "message": "正则表达式无效"})
        if field.get("options") and ftype in {"select", "radio", "checkbox", "multiselect", "cascader"}:
            allowed = {str(o.get("value")) if isinstance(o, dict) else str(o)
                       for o in field["options"]}
            vals = value if isinstance(value, list) else [value]
            if any(str(v) not in allowed for v in vals):
                errors.append({"key": key, "rule": "options", "message": "取值不在允许范围内"})
        if ftype in {"date", "datetime"} and not _DATE.match(str(value)[:10]):
            errors.append({"key": key, "rule": "date", "message": "日期格式应为 YYYY-MM-DD"})
        if "date_range" in rules:
            rng = rules["date_range"]
            if isinstance(rng, list) and len(rng) == 2 and not (str(rng[0]) <= str(value)[:10] <= str(rng[1])):
                errors.append({"key": key, "rule": "date_range", "message": "日期超出允许区间"})
        if check_unique and rules.get("unique") and form_id:
            existing = db.q("SELECT id, data FROM form_submissions WHERE form_id=?", (form_id,))
            for row in existing:
                if row["id"] == exclude_submission:
                    continue
                try:
                    import json
                    stored = json.loads(row["data"]) if isinstance(row["data"], str) else dict(row["data"])
                except (ValueError, TypeError):
                    continue
                if stored.get(key) == value:
                    errors.append({"key": key, "rule": "unique", "message": "该值已被使用"})
                    break
        if perms.get(key) == "readonly" and payload.get(key) != value:
            errors.append({"key": key, "rule": "readonly", "message": "该字段在当前节点只读"})

    return {"data": clean, "errors": errors, "visible": sorted(
                {f.get("key") for f in schema if f.get("key")} - hidden),
            "hidden": sorted(hidden), "permissions": perms,
            "summaries": summaries, "computed": computed}


def serial_number(form_code: str, config: dict | None = None) -> str:
    """Generate the next domestic-style document number, e.g. BX-20261108-0007."""
    cfg = config or {}
    prefix = str(cfg.get("prefix") or form_code.upper()[:4])
    digits = int(cfg.get("digits") or 4)
    parts = [prefix]
    if cfg.get("date", True):
        parts.append(date.today().strftime("%Y%m%d"))
    pattern = prefix + "%"
    row = db.q1("SELECT serial_no FROM form_submissions WHERE form_id IN "
                "(SELECT id FROM forms WHERE code=?) AND serial_no LIKE ? "
                "ORDER BY id DESC LIMIT 1", (form_code, pattern))
    seq = 0
    if row and row["serial_no"]:
        tail = row["serial_no"].rsplit("-", 1)[-1]
        if tail.isdigit():
            seq = int(tail)
    parts.append(str(seq + 1).zfill(digits))
    return "-".join(parts)


def render_schema(schema: list[dict], *, platform: str = "desktop",
                  node_config: dict | None = None, data: dict | None = None) -> dict:
    """Rendered schema for a client, applying mobile layout and node permissions."""
    perms = applied_permissions(schema, node_config, data or {})
    fields = []
    for field in schema:
        f = dict(field)
        f["permission"] = perms.get(f.get("key"), "editable")
        if platform == "mobile":
            f["width"] = 100
            f["mobile_hidden"] = bool(f.get("mobile_hidden"))
        fields.append(f)
    return {"fields": fields, "platform": platform,
            "columns": 1 if platform == "mobile" else 2,
            "permissions": perms}
