"""Ephemeral customer quotations; no quotation state or product writes."""

import hashlib
import io
import json
import re
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_HALF_UP, localcontext

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from sqlalchemy import select

from app.models import LibraryProduct
from app.product_library_service import error, list_products_service, price, product_versions, product_view

RISK_WORDS = ("成本", "采购价", "进货价", "拿货价", "供货价", "底价", "批发价", "内部价", "利润", "加价率", "开票调整", "运费成本")
CUSTOMER_FIELDS = ("model", "name", "parameters", "selling_points")
INVALID_EXCEL_TEXT = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
MAX_PRICE = Decimal("999999999.99")
RULE_DEFAULTS = {"markup_mode": "none", "markup_value": "0.00", "tax_mode": "excluded", "tax_value": "0.00", "freight_mode": "separate", "freight_value": "0.00", "rounding": "cents"}
TAX_NOTES = {
    "excluded": "以上报价为未税单价，税费另计。",
    "included": "以上报价为含税单价。",
    "adjust": "以上报价按指定开票报价口径调整，具体开票内容及适用条件以双方确认为准。",
}
FREIGHT_NOTES = {
    "separate": "运费另计，金额以订单确认为准。",
    "included": "以上报价已含运费。",
    "fixed": "以上报价已计入单件运费，整单实际费用以订单确认为准。",
}


def quotation_rules(raw):
    if not isinstance(raw, dict) or set(raw) - set(RULE_DEFAULTS):
        error(422, "invalid_quotation", "报价规则含未知字段")
    rules = RULE_DEFAULTS | raw
    for key, options in (("markup_mode", ("none", "percent", "fixed")), ("tax_mode", tuple(TAX_NOTES)), ("freight_mode", tuple(FREIGHT_NOTES)), ("rounding", ("cents", "integer"))):
        if rules[key] not in options:
            error(422, "invalid_quotation", "报价模式无效", field=key)
    for key in ("markup_value", "tax_value", "freight_value"):
        try:
            raw = rules[key]
            if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", raw):
                raise ValueError("请输入非负十进制金额或比例文本，最多两位小数")
            amount = Decimal(raw)
            if (key == "tax_value" or key == "markup_value" and rules["markup_mode"] == "percent") and amount > 1000:
                raise ValueError("比例必须为0～1000%，最多两位小数")
            rules[key] = f"{amount:.2f}"
        except ValueError as exc:
            error(422, "invalid_quotation", str(exc), field=key)
    return rules


def quotation_digest(items, rules):
    return hashlib.sha256(json.dumps({"items": items, "rules": rules}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def text_risks(product):
    risks = []
    for field in CUSTOMER_FIELDS:
        value = product[field] or ""
        for word in RISK_WORDS:
            for match in re.finditer(re.escape(word), value):
                risks.append({"field": field, "word": word, "snippet": value[max(0, match.start() - 16):match.end() + 24]})
    return risks


def quote_row(product, rules, override=None):
    cost = None if product["wholesale_price"] is None else Decimal(product["wholesale_price"])
    risks, calculation_error = [], None
    final = None
    try:
        with localcontext() as context:
            context.prec = 60
            value = Decimal(override) if override is not None else cost
            if value is not None:
                if override is None:
                    markup = Decimal(rules["markup_value"])
                    if rules["markup_mode"] == "percent":
                        value *= 1 + markup / 100
                    elif rules["markup_mode"] == "fixed":
                        value += markup
                    if rules["tax_mode"] == "adjust":
                        value *= 1 + Decimal(rules["tax_value"]) / 100
                    if rules["freight_mode"] == "fixed":
                        value += Decimal(rules["freight_value"])
                value = value.quantize(Decimal("1") if rules["rounding"] == "integer" else Decimal("0.01"), rounding=ROUND_CEILING if rules["rounding"] == "integer" else ROUND_HALF_UP)
                if not value.is_finite() or value > MAX_PRICE:
                    raise ValueError("最终报价超过999999999.99")
                final = f"{value:.2f}"
                if cost is not None and value < cost:
                    risks.append("低于采购成本")
    except (DecimalException, ValueError):
        calculation_error = "最终报价超限或无法计算，请调整规则、改价或移出范围"
    if cost is None:
        risks.append("无法核对成本")
    if final is None:
        risks.append("待报价")
    invalid_fields = [field for field in CUSTOMER_FIELDS if INVALID_EXCEL_TEXT.search(product[field] or "")]
    if invalid_fields:
        calculation_error = "客户文本含 Excel 不支持的字符，请在产品资料中核查字段：" + "、".join(invalid_fields)
    return {"id": product["id"], "version": product["version"], **{field: product[field] for field in CUSTOMER_FIELDS}, "final_price": final, "risks": risks, "text_risks": text_risks(product), "invalid_text_fields": invalid_fields, "error": calculation_error, "manual": override is not None}


def quotation_overrides(raw, items):
    if not isinstance(raw, dict) or set(raw) - {str(item["id"]) for item in items}:
        error(422, "invalid_quotation", "人工报价必须属于预览产品")
    result = {}
    for key, value in raw.items():
        try:
            result[key] = price(value)
            if result[key] is None:
                raise ValueError("人工报价不能为空")
        except ValueError as exc:
            error(422, "invalid_quotation", str(exc), product_id=int(key))
    return result


def preview_quotation_service(payload, db):
    if set(payload) - {"scope", "items", "filters", "rules", "include_unquoted", "overrides"}:
        error(422, "invalid_quotation", "预览含未知字段")
    scope = payload.get("scope")
    if scope not in ("selected", "filtered", "all") or type(payload.get("include_unquoted", False)) is not bool:
        error(422, "invalid_quotation", "报价范围无效")
    rules = quotation_rules(payload.get("rules", {}))
    if scope == "selected":
        items = product_versions(payload.get("items"))
        products = read_snapshot(items, db)
    else:
        filters = payload.get("filters", {}) if scope == "filtered" else {}
        allowed = {"q", "manufacturer", "sort", "price_status", "price_mode", "price_min", "price_max"}
        if not isinstance(filters, dict) or set(filters) - allowed:
            error(422, "invalid_quotation", "筛选条件无效")
        if any(not isinstance(value, str) for key, value in filters.items() if value is not None or key in ("q", "sort", "price_status")) or len(filters.get("q", "") or "") > 200:
            error(422, "invalid_quotation", "筛选字段必须为文本")
        products = list_products_service(**({"q": "", "manufacturer": None, "sort": "updated_desc"} | filters), page=1, page_size=None, db=db)
        products = products["items"]
    if not payload.get("include_unquoted", False):
        products = [product for product in products if product["wholesale_price"] is not None]
    items = [{"id": product["id"], "version": product["version"]} for product in products]
    # Ignore overrides outside the newly resolved scope; never silently attach them to other rows.
    raw = payload.get("overrides", {})
    if not isinstance(raw, dict):
        error(422, "invalid_quotation", "人工报价格式无效")
    overrides = quotation_overrides({key: value for key, value in raw.items() if key in {str(item["id"]) for item in items}}, items)
    return {"items": items, "rules": rules, "digest": quotation_digest(items, rules), "rows": [quote_row(product, rules, overrides.get(str(product["id"]))) for product in products], "note": TAX_NOTES[rules["tax_mode"]] + FREIGHT_NOTES[rules["freight_mode"]]}


def read_snapshot(items, db):
    products = {product.id: product for product in db.scalars(select(LibraryProduct).where(LibraryProduct.id.in_([item["id"] for item in items]))).all()}
    affected = [{**item, "reason": "missing" if item["id"] not in products else "stale"} for item in items if item["id"] not in products or products[item["id"]].version != item["version"]]
    if affected:
        error(409, "quotation_stale", "产品已变化，请刷新受影响项并重新预览", items=affected)
    return [product_view(products[item["id"]]) for item in items]


def export_quotation_service(payload, db):
    if set(payload) != {"items", "rules", "digest", "overrides", "confirmed_risk_ids", "confirmed_all_text"}:
        error(422, "invalid_quotation", "导出字段缺失或含未知字段")
    items = product_versions(payload["items"])
    rules = quotation_rules(payload["rules"])
    if payload["digest"] != quotation_digest(items, rules):
        error(409, "quotation_preview_mismatch", "产品集合或规则已变化，请重新预览")
    products = read_snapshot(items, db)
    overrides = quotation_overrides(payload["overrides"], items)
    rows = [quote_row(product, rules, overrides.get(str(product["id"]))) for product in products]
    invalid = [{"id": row["id"], "fields": row["invalid_text_fields"]} for row in rows if row["invalid_text_fields"]]
    if invalid:
        error(422, "customer_text_invalid", "客户文本含 Excel 不支持的字符，请核查产品字段后重新预览", errors=invalid)
    confirmations = payload["confirmed_risk_ids"]
    required = {row["id"] for row in rows if row["text_risks"]}
    if (payload["confirmed_all_text"] is not True or not isinstance(confirmations, list)
            or any(type(value) is not int for value in confirmations) or not required.issubset(confirmations)):
        error(422, "customer_text_unconfirmed", "请逐项核查敏感产品，并确认已核对全部客户可见文本")
    if any(row["error"] for row in rows):
        error(422, "quotation_overflow", "存在超限报价，请调整后重新预览")
    wb = Workbook()
    ws = wb.active
    ws.title = "客户报价"
    ws.append(["产品型号", "产品名称", "完整参数", "卖点", "最终报价", "报价说明"])
    note = TAX_NOTES[rules["tax_mode"]] + FREIGHT_NOTES[rules["freight_mode"]]
    for row in rows:
        values = [row[field] or "" for field in CUSTOMER_FIELDS] + [Decimal(row["final_price"]) if row["final_price"] is not None else "待报价", note]
        ws.append(values)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(ws.max_row, 5).number_format = "0.00"
    for column, width in zip("ABCDEF", (20, 28, 55, 45, 18, 65)):
        ws.column_dimensions[column].width = width
        ws[f"{column}1"].font = Font(bold=True)
    ws.freeze_panes = "A2"
    wb.properties.creator = ""
    output = io.BytesIO()
    wb.save(output)
    wb.close()
    return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="customer-quotation.xlsx"'})
