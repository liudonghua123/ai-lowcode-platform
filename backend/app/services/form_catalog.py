"""Chinese-market form field catalog and form-level metadata.

The platform historically exposed 14 field types and a single `required` flag.
Domestic form scenarios need organization pickers, statutory identifiers,
amount-in-words, detail tables, conditional logic and per-node field
permissions. This module is the single source of truth shared by the designer
palette, the server-side validator and the runtime renderer.
"""
from __future__ import annotations

GROUPS = [
    {"code": "basic", "en": "Basic", "zh": "基础字段"},
    {"code": "china", "en": "China-local", "zh": "中国本地化"},
    {"code": "org", "en": "Organization", "zh": "组织架构"},
    {"code": "business", "en": "Business", "zh": "业务组件"},
    {"code": "layout", "en": "Layout", "zh": "布局容器"},
    {"code": "advanced", "en": "Advanced / extensible", "zh": "高级/可扩展"},
]

# type, group, English label, Chinese label, default width, extra capabilities
_CATALOG: list[tuple[str, str, str, str, int, tuple[str, ...]]] = [
    ("text", "basic", "Single line", "单行文本", 50, ()),
    ("textarea", "basic", "Multi line", "多行文本", 100, ()),
    ("number", "basic", "Number", "数字", 50, ()),
    ("select", "basic", "Dropdown", "下拉选择", 50, ("options",)),
    ("multiselect", "basic", "Multi select", "下拉多选", 50, ("options",)),
    ("radio", "basic", "Radio", "单选框", 50, ("options",)),
    ("checkbox", "basic", "Checkbox", "多选框", 50, ("options",)),
    ("switch", "basic", "Switch", "开关", 50, ()),
    ("date", "basic", "Date", "日期", 50, ()),
    ("datetime", "basic", "Date time", "日期时间", 50, ()),
    ("time", "basic", "Time", "时间", 50, ()),
    ("slider", "basic", "Slider", "滑块", 50, ()),
    ("rate", "basic", "Rating", "评分", 50, ()),
    ("color", "basic", "Color", "颜色", 50, ()),
    ("email", "basic", "Email", "邮箱", 50, ()),
    ("url", "basic", "URL", "网址", 50, ()),

    ("idcard", "china", "ID card", "身份证", 50, ("cn_id",)),
    ("mobile", "china", "Mobile", "手机号", 50, ("cn_mobile",)),
    ("tel", "china", "Landline", "固定电话", 50, ("cn_tel",)),
    ("bankcard", "china", "Bank card", "银行卡", 50, ("luhn",)),
    ("uscc", "china", "Unified social credit code", "统一社会信用代码", 100, ("uscc",)),
    ("amount", "china", "Amount (CNY)", "金额（人民币大写）", 50, ("cny",)),
    ("region", "china", "Region cascader", "省市区联动", 100, ("region",)),
    ("cascader", "china", "Cascader", "级联选择", 100, ("options",)),
    ("signature", "china", "Handwritten signature", "手写签名", 100, ("signature",)),
    ("qrcode", "china", "QR / barcode", "二维码/条形码", 50, ()),

    ("user", "org", "Member picker", "成员选择", 50, ("org",)),
    ("multi_user", "org", "Member multi-picker", "成员多选", 50, ("org",)),
    ("department", "org", "Department picker", "部门选择", 50, ("org",)),
    ("role", "org", "Role picker", "角色选择", 50, ("org",)),

    ("table", "business", "Detail table", "明细表/子表单", 100, ("detail",)),
    ("formula", "business", "Formula", "计算公式", 50, ("formula",)),
    ("serial", "business", "Serial number", "流水号", 50, ("serial",)),
    ("relation", "business", "Linked record", "关联表单数据", 50, ("relation",)),
    ("attachment", "business", "Attachment", "附件", 100, ("file",)),
    ("image", "business", "Image / photo", "图片/拍照", 100, ("file",)),
    ("location", "business", "Location", "定位", 50, ("location",)),
    ("richtext", "business", "Rich text", "富文本", 100, ()),
    ("ocr", "business", "OCR field", "OCR 识别", 100, ("file",)),

    ("divider", "layout", "Divider", "分割线", 100, ("layout",)),
    ("description", "layout", "Description", "说明文字", 100, ("layout",)),
    ("grid", "layout", "Grid row", "栅格容器", 100, ("layout",)),
    ("tabs", "layout", "Tabs", "标签页", 100, ("layout",)),
    ("collapse", "layout", "Collapse", "折叠面板", 100, ("layout",)),

    # --- v5 extensibility wave ------------------------------------------- #
    # Extra input primitives (all render through the generic schema renderer).
    ("password", "basic", "Password", "密码框", 50, ()),
    ("daterange", "basic", "Date range", "日期区间", 50, ("range",)),
    ("timerange", "basic", "Time range", "时间区间", 50, ("range",)),
    ("nps", "basic", "NPS score", "NPS 评分", 50, ("nps",)),
    ("segmented", "basic", "Segmented control", "分段选择", 100, ("options",)),
    ("tags", "basic", "Tag input", "标签输入", 100, ("tags",)),
    ("percent", "basic", "Percentage", "百分比", 50, ("number",)),
    ("slider_range", "basic", "Range slider", "区间滑块", 100, ("range",)),
    ("hidden", "basic", "Hidden value", "隐藏字段", 50, ()),
    ("currency", "business", "Currency", "货币金额", 50, ("cny", "options")),
    ("markdown", "business", "Markdown editor", "Markdown 编辑器", 100, ("richtext",)),
    ("html", "layout", "HTML block", "HTML 内容块", 100, ("layout", "richtext")),
    ("code", "business", "Code editor", "代码编辑器", 100, ("richtext",)),
    ("steps", "layout", "Steps / wizard", "步骤条", 100, ("layout", "options")),
    ("button", "layout", "Action button", "动作按钮", 50, ("layout",)),
    ("ai_autofill", "advanced", "AI autofill", "AI 智能填充", 100, ("ai",)),
    ("qrscan", "advanced", "QR / barcode scan", "扫码识别", 50, ("capture",)),
    ("camera", "advanced", "Camera capture", "拍照采集", 100, ("capture", "file")),
    ("gis", "advanced", "Map coordinate", "地图坐标", 100, ("location",)),
    ("cron", "advanced", "Schedule expression", "定时表达式", 50, ("code",)),
    ("iframe", "advanced", "Embedded page", "嵌入页面", 100, ("layout",)),
    ("custom", "advanced", "Custom component", "自定义组件", 100, ("custom",)),
]

VALIDATORS = [
    {"code": "required", "en": "Required", "zh": "必填"},
    {"code": "regex", "en": "Regex", "zh": "正则校验"},
    {"code": "min", "en": "Minimum", "zh": "最小值"},
    {"code": "max", "en": "Maximum", "zh": "最大值"},
    {"code": "min_length", "en": "Min length", "zh": "最小长度"},
    {"code": "max_length", "en": "Max length", "zh": "最大长度"},
    {"code": "precision", "en": "Decimal places", "zh": "小数位数"},
    {"code": "idcard", "en": "PRC ID card", "zh": "身份证号"},
    {"code": "mobile", "en": "PRC mobile", "zh": "手机号"},
    {"code": "tel", "en": "Landline", "zh": "固定电话"},
    {"code": "bankcard", "en": "Bank card (Luhn)", "zh": "银行卡（Luhn）"},
    {"code": "uscc", "en": "Social credit code", "zh": "统一社会信用代码"},
    {"code": "email", "en": "Email", "zh": "邮箱"},
    {"code": "url", "en": "URL", "zh": "网址"},
    {"code": "unique", "en": "Unique among submissions", "zh": "提交值唯一"},
    {"code": "date_range", "en": "Date range", "zh": "日期区间"},
    {"code": "options", "en": "Option list", "zh": "选项范围"},
]

OPERATORS = [
    {"code": "eq", "en": "equals", "zh": "等于"},
    {"code": "ne", "en": "not equals", "zh": "不等于"},
    {"code": "gt", "en": "greater than", "zh": "大于"},
    {"code": "gte", "en": "greater or equal", "zh": "大于等于"},
    {"code": "lt", "en": "less than", "zh": "小于"},
    {"code": "lte", "en": "less or equal", "zh": "小于等于"},
    {"code": "contains", "en": "contains", "zh": "包含"},
    {"code": "not_contains", "en": "does not contain", "zh": "不包含"},
    {"code": "in", "en": "in list", "zh": "属于列表"},
    {"code": "not_in", "en": "not in list", "zh": "不属于列表"},
    {"code": "empty", "en": "is empty", "zh": "为空"},
    {"code": "not_empty", "en": "is not empty", "zh": "不为空"},
]

FUNCTIONS = [
    {"code": "SUM", "args": "numbers", "en": "Sum", "zh": "求和"},
    {"code": "AVG", "args": "numbers", "en": "Average", "zh": "平均值"},
    {"code": "MIN", "args": "numbers", "en": "Minimum", "zh": "最小值"},
    {"code": "MAX", "args": "numbers", "en": "Maximum", "zh": "最大值"},
    {"code": "ROUND", "args": "number, digits", "en": "Round", "zh": "四舍五入"},
    {"code": "ABS", "args": "number", "en": "Absolute", "zh": "绝对值"},
    {"code": "IF", "args": "condition, a, b", "en": "Conditional", "zh": "条件取值"},
    {"code": "CONCAT", "args": "values", "en": "Concatenate", "zh": "拼接"},
    {"code": "LEN", "args": "value", "en": "Length", "zh": "长度"},
    {"code": "CNY_UPPER", "args": "number", "en": "RMB in words", "zh": "人民币大写"},
    {"code": "TABLE_SUM", "args": "table, column", "en": "Detail column sum", "zh": "明细列合计"},
    {"code": "COUNT", "args": "table", "en": "Detail row count", "zh": "明细行数"},
    {"code": "DATEDIFF", "args": "date1, date2", "en": "Days between", "zh": "日期差（天）"},
    {"code": "TODAY", "args": "", "en": "Today", "zh": "今天"},
    {"code": "NOW", "args": "", "en": "Now", "zh": "当前时间"},
    {"code": "NUMBER", "args": "value", "en": "To number", "zh": "转数字"},
    {"code": "INT", "args": "value", "en": "To integer", "zh": "转整数"},
    {"code": "FLOAT", "args": "value", "en": "To float", "zh": "转浮点数"},
    {"code": "STR", "args": "value", "en": "To text", "zh": "转文本"},
]

PERMISSION_MODES = [
    {"code": "editable", "en": "Editable", "zh": "可编辑"},
    {"code": "readonly", "en": "Read only", "zh": "只读"},
    {"code": "hidden", "en": "Hidden", "zh": "隐藏"},
]

PRIVATE_FIELD_TYPES = {"divider", "description", "grid", "tabs", "collapse",
                       "html", "steps", "button", "iframe"}
COMPUTED_FIELD_TYPES = {"formula", "serial"}
LAYOUT_TYPES = PRIVATE_FIELD_TYPES
FORMULA_TYPES = {"formula", "number", "amount", "percent", "currency"}
# Types whose value is a composite object rather than a scalar.
COMPOSITE_TYPES = {"daterange", "timerange", "slider_range", "gis", "tags",
                   "table", "attachment", "image", "camera", "region", "cascader"}


def entries() -> list[dict]:
    return [{"type": t, "group": g, "label": {"en": en, "zh": zh},
             "width": w, "caps": list(caps)} for t, g, en, zh, w, caps in _CATALOG]


FIELD_TYPES: list[str] = [e["type"] for e in entries()]


def catalog(lang: str = "en") -> dict:
    def lbl(item: dict) -> str:
        return item[lang] if lang in item else item["en"]
    return {
        "groups": [{"code": g["code"], "label": lbl(g)} for g in GROUPS],
        "fields": [{"type": e["type"], "group": e["group"], "label": lbl(e["label"]),
                    "width": e["width"], "caps": e["caps"]} for e in entries()],
        "field_types": FIELD_TYPES,
        "validators": [{"code": v["code"], "label": lbl(v)} for v in VALIDATORS],
        "operators": [{"code": o["code"], "label": lbl(o)} for o in OPERATORS],
        "functions": [{"code": f["code"], "args": f["args"], "label": lbl(f)} for f in FUNCTIONS],
        "permission_modes": [{"code": m["code"], "label": lbl(m)} for m in PERMISSION_MODES],
        "layout_types": sorted(LAYOUT_TYPES),
        "computed_types": sorted(COMPUTED_FIELD_TYPES),
    }


# A compact, real administrative-division sample. Full GB/T 2260 data can be
# loaded into `settings` without touching the renderer contract.
REGIONS = [
    {"code": "11", "name": "北京市", "children": [
        {"code": "1101", "name": "市辖区", "children": [
            {"code": "110101", "name": "东城区"}, {"code": "110102", "name": "西城区"},
            {"code": "110105", "name": "朝阳区"}, {"code": "110108", "name": "海淀区"}]}]},
    {"code": "31", "name": "上海市", "children": [
        {"code": "3101", "name": "市辖区", "children": [
            {"code": "310101", "name": "黄浦区"}, {"code": "310104", "name": "徐汇区"},
            {"code": "310115", "name": "浦东新区"}]}]},
    {"code": "44", "name": "广东省", "children": [
        {"code": "4401", "name": "广州市", "children": [
            {"code": "440103", "name": "荔湾区"}, {"code": "440106", "name": "天河区"}]},
        {"code": "4403", "name": "深圳市", "children": [
            {"code": "440303", "name": "罗湖区"}, {"code": "440305", "name": "南山区"},
            {"code": "440306", "name": "宝安区"}]}]},
    {"code": "33", "name": "浙江省", "children": [
        {"code": "3301", "name": "杭州市", "children": [
            {"code": "330102", "name": "上城区"}, {"code": "330106", "name": "西湖区"},
            {"code": "330108", "name": "滨江区"}]}]},
]


def default_field(ftype: str, index: int, lang: str = "en") -> dict:
    entry = next((e for e in entries() if e["type"] == ftype), None)
    label = entry["label"][lang] if entry else ftype.capitalize()
    field: dict = {
        "id": f"f_{index}_{ftype}", "key": f"field_{index + 1}", "type": ftype,
        "label": label, "required": False, "width": entry["width"] if entry else 50,
        "placeholder": "", "description": "",
    }
    caps = set(entry["caps"]) if entry else set()
    if "options" in caps or ftype in {"select", "multiselect", "radio", "checkbox", "cascader"}:
        field["options"] = ["选项一", "选项二"] if lang == "zh" else ["Option A", "Option B"]
    if ftype in {"number", "amount", "percent", "currency", "slider", "rate"}:
        field["validation"] = {"min": 0}
    if ftype == "nps":
        field["validation"] = {"min": 0, "max": 10}
    if ftype in {"daterange", "timerange", "slider_range"}:
        field["range"] = {"start": "", "end": ""}
    if ftype == "tags":
        field["tags"] = []
    if ftype == "currency":
        field["options"] = ["CNY", "USD", "EUR"]
        field["currency"] = "CNY"
    if ftype in {"markdown", "html", "code"}:
        field["content"] = ""
        field["language"] = "python" if ftype == "code" else "markdown"
    if ftype == "steps":
        field["options"] = ["Step 1", "Step 2", "Step 3"]
    if ftype == "button":
        field["action"] = "submit"
    if ftype == "custom":
        field["component"] = ""
        field["props"] = {}
    if ftype == "ai_autofill":
        field["prompt"] = ""
        field["source_fields"] = []
    if ftype == "gis":
        field["range"] = {"lng": "", "lat": ""}
    if ftype == "table":
        field["columns"] = [
            {"key": "item", "label": "名称", "type": "text"},
            {"key": "qty", "label": "数量", "type": "number"},
            {"key": "price", "label": "单价", "type": "number"},
            {"key": "subtotal", "label": "小计", "type": "formula", "formula": "qty * price"},
        ]
        field["summary"] = [{"key": "total", "label": "合计", "column": "subtotal", "op": "sum"}]
    if ftype == "formula":
        field["formula"] = "0"
    if ftype == "serial":
        field["serial"] = {"prefix": "BX", "date": True, "digits": 4}
    if ftype == "amount":
        field["show_upper"] = True
    if ftype == "region":
        field["region_level"] = 3
    return field
