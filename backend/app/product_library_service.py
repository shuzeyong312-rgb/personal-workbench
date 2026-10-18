"""Product library: bounded Excel previews and atomic, durable confirmations."""

import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from fastapi import HTTPException
from fastapi.responses import Response
from openpyxl import load_workbook
from sqlalchemy import or_, select, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.models import LibraryImport, LibraryProduct

FIELDS = (
    "model",
    "name",
    "parameters",
    "selling_points",
    "wholesale_price",
    "price_note",
)
HEADERS = ("产品型号", "产品名称", "产品参数", "产品卖点", "批发价", "价格备注")
LIMITS = {
    "manufacturer_name": 200,
    "model": 200,
    "name": 200,
    "parameters": 10000,
    "selling_points": 10000,
    "price_note": 2000,
}
MIB = 1024 * 1024


def error(status, code, message, **extra):
    raise HTTPException(status, {"code": code, "message": message, **extra})


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def normalized_text(value, field):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("必须是文本，不能使用数字、布尔或日期")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if field == "manufacturer_name":
        value = " ".join(value.split())
    if not value and field in ("manufacturer_name", "name"):
        raise ValueError("必填字段不能为空")
    if len(value) > LIMITS[field]:
        raise ValueError(f"最多 {LIMITS[field]} 个字符")
    return value or None


def price(value, *, excel=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, int, float, Decimal))
        or (not excel and not isinstance(value, str))
    ):
        raise ValueError("批发价必须是十进制金额文本")
    raw = str(value).strip()
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw):
        raise ValueError("批发价须为非负十进制金额，不含符号或范围")
    try:
        amount = Decimal(raw)
        if (
            not amount.is_finite()
            or amount < 0
            or amount > Decimal("999999999.99")
            or amount.as_tuple().exponent < -2
        ):
            raise ValueError("批发价范围为 0～999999999.99，最多两位小数")
        return f"{amount:.2f}"
    except InvalidOperation:
        raise ValueError("批发价格式错误")


def validate(data, *, excel=False):
    values, errors = {}, []
    for field in ("manufacturer_name", *FIELDS):
        try:
            values[field] = (
                price(data.get(field), excel=excel)
                if field == "wholesale_price"
                else normalized_text(data.get(field), field)
            )
        except ValueError as exc:
            values[field] = None
            errors.append(
                {"field": field, "code": "invalid_field", "message": str(exc)}
            )
    return values, errors


def product_view(product):
    return {
        "id": product.id,
        "manufacturer_name": product.manufacturer_name,
        **{
            field: getattr(product, field)
            for field in FIELDS
            if field != "wholesale_price"
        },
        "wholesale_price": (
            None
            if product.wholesale_price_cents is None
            else f"{Decimal(product.wholesale_price_cents) / 100:.2f}"
        ),
        "version": product.version,
        "created_at": utc(product.created_at).isoformat(),
        "updated_at": utc(product.updated_at).isoformat(),
    }


def assign(product, data):
    for field, value in data.items():
        if field == "wholesale_price":
            product.wholesale_price_cents = (
                None if value is None else int(Decimal(value) * 100)
            )
        else:
            setattr(product, field, value)


def begin_write(db):
    db.execute(text("BEGIN IMMEDIATE"))


def database_error(db, exc, code):
    db.rollback()
    if isinstance(exc, OperationalError) and (
        "locked" in str(exc).lower() or "busy" in str(exc).lower()
    ):
        error(503, "database_busy", "数据库忙，请按原请求重试")
    error(500, code, "本次未保存，全部回滚")


def product_or_404(db, product_id):
    if product_id < 1:
        error(404, "product_not_found", "产品不存在")
    product = db.get(LibraryProduct, product_id)
    if product is None:
        error(404, "product_not_found", "产品不存在")
    return product


def candidates_for(db, values, exclude=None):
    products = db.scalars(
        select(LibraryProduct)
        .where(LibraryProduct.manufacturer_name == values["manufacturer_name"])
        .order_by(LibraryProduct.id)
    ).all()
    products = [p for p in products if p.id != exclude]
    same_model = [
        p
        for p in products
        if values["model"] is not None and p.model == values["model"]
    ]
    return same_model, [p for p in products if p.name == values["name"]]


def manual_payload(payload, editing=False):
    required = (
        {"manufacturer_name", *FIELDS} if editing else {"manufacturer_name", "name"}
    )
    allowed = {"manufacturer_name", *FIELDS, "allow_suspected_duplicate"} | (
        {"version"} if editing else set()
    )
    if set(payload) - allowed or not required.issubset(payload):
        error(422, "invalid_product", "字段缺失或含未知字段")
    if "allow_suspected_duplicate" in payload and not isinstance(
        payload["allow_suspected_duplicate"], bool
    ):
        error(422, "invalid_product", "重复确认必须是布尔值")
    values, errors = validate(payload)
    if errors:
        error(422, "invalid_product", "产品字段校验失败", errors=errors)
    return values


def version_value(payload):
    version = payload.get("version")
    if type(version) is not int or version < 1:
        error(422, "invalid_product", "version 必须为正整数")
    return version


def check_duplicates(db, values, payload, exclude=None):
    exact, suspected = candidates_for(db, values, exclude)
    if exact:
        error(
            409,
            "product_exists",
            "同厂家同型号产品已存在",
            candidates=[product_view(p) for p in exact],
        )
    if suspected and not payload.get("allow_suspected_duplicate", False):
        error(
            409,
            "suspected_duplicate",
            "存在同名产品，请明确确认仍新增或保存",
            candidates=[product_view(p) for p in suspected],
        )


def read_excel(content):
    if len(content) > 5 * MIB:
        error(413, "file_too_large", "文件不能超过 5 MiB")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 1000
                or sum(entry.file_size for entry in entries) > 50 * MIB
            ):
                error(413, "workbook_limit_exceeded", "工作簿解压大小或条目超限")
            seen, total = set(), 0
            for entry in entries:
                name = entry.filename.lower()
                if name in seen:
                    error(400, "invalid_workbook", "工作簿含重复包条目")
                seen.add(name)
                if any(
                    token in name
                    for token in ("vbaproject", "embeddings/", "externallinks/")
                ):
                    error(400, "invalid_workbook", "不允许宏、嵌入对象或外链")
                with archive.open(entry) as member:
                    chunks = []
                    while True:
                        chunk = member.read(min(MIB, 50 * MIB - total + 1))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 50 * MIB:
                            error(413, "workbook_limit_exceeded", "工作簿解压超限")
                        chunks.append(chunk)
                data = b"".join(chunks)
                # XML parts may use other suffixes and NUL-containing encodings.
                probe = data.replace(b"\x00", b"").lower()
                if b"<!doctype" in probe or b"<!entity" in probe:
                    error(400, "invalid_workbook", "不允许 DTD 或实体声明")
                if name.endswith((".xml", ".rels")):
                    for _, element in ET.iterparse(io.BytesIO(data), events=("end",)):
                        tag = element.tag.rsplit("}", 1)[-1]
                        relation = (
                            element.attrib.get("Type", "").rsplit("/", 1)[-1].lower()
                        )
                        if name.endswith(".rels") and (
                            element.attrib.get("TargetMode", "").lower() == "external"
                            or relation in ("package", "oleobject")
                        ):
                            error(400, "invalid_workbook", "不允许外部关系或嵌入对象")
                        if tag in ("oleObjects", "oleObject"):
                            error(400, "invalid_workbook", "不允许嵌入对象")
                        element.clear()
                    if name == "[content_types].xml" and (
                        b"macroenabled" in probe
                        or b"vba" in probe
                        or b"oleobject" in probe
                    ):
                        error(415, "unsupported_excel_format", "仅支持无宏 .xlsx")
        wb = load_workbook(
            io.BytesIO(content),
            read_only=True,
            data_only=False,
            keep_links=False,
            keep_vba=False,
        )
        try:
            if "产品数据" not in wb.sheetnames:
                error(400, "invalid_structure", "缺少产品数据工作表")
            ws = wb["产品数据"]
            if ws.sheet_state != "visible":
                error(400, "invalid_structure", "产品数据工作表不能隐藏")
            # Inspect actual XML before reading cells; dimensions and styled tails are not data.
            from openpyxl.utils.cell import (
                coordinate_from_string,
                column_index_from_string,
            )

            last = 1
            with zipfile.ZipFile(io.BytesIO(content)) as archive, archive.open(
                ws._worksheet_path
            ) as source:
                sheet_data = None
                for event, element in ET.iterparse(source, events=("start", "end")):
                    tag = element.tag.rsplit("}", 1)[-1]
                    if event == "start":
                        if tag == "sheetData":
                            sheet_data = element
                        continue
                    if tag == "mergeCell" or (
                        tag in ("row", "col")
                        and element.attrib.get("hidden") in ("1", "true", "True")
                    ):
                        error(
                            400,
                            "invalid_structure",
                            "产品数据不能含合并单元格或隐藏行列",
                        )
                    if tag == "c":
                        nonempty = element.attrib.get("t") == "e" or any(
                            child.tag.rsplit("}", 1)[-1] == "f"
                            or (
                                child.tag.rsplit("}", 1)[-1] in ("v", "t")
                                and child.text is not None
                            )
                            for child in element.iter()
                        )
                        if nonempty:
                            column, number = coordinate_from_string(element.attrib["r"])
                            if column_index_from_string(column) > 6:
                                error(400, "invalid_structure", "六列以外存在非空内容")
                            if number > 1001:
                                error(
                                    413,
                                    "workbook_limit_exceeded",
                                    "最多1000个物理数据行",
                                )
                            last = max(last, number)
                        element.clear()
                    elif tag == "row":
                        element.clear()
                        if sheet_data is not None:
                            sheet_data.clear()
            ws.reset_dimensions()
            data_rows = ws.iter_rows(min_row=1, max_row=last, max_col=6)
            if tuple(cell.value for cell in next(data_rows)) != HEADERS:
                error(400, "invalid_structure", "表头必须严格匹配模板六列")
            rows, blank = [], 0
            for number, row_cells in enumerate(data_rows, 2):
                raw = {field: cell.value for field, cell in zip(FIELDS, row_cells)}
                if not any(cell.data_type in ("f", "e") for cell in row_cells) and all(
                    value is None or (isinstance(value, str) and not value.strip())
                    for value in raw.values()
                ):
                    blank += 1
                    continue
                values, errors = validate(
                    {"manufacturer_name": "placeholder", **raw}, excel=True
                )
                values.pop("manufacturer_name")
                for field, cell in zip(FIELDS, row_cells):
                    if cell.data_type in ("f", "e"):
                        errors.append(
                            {
                                "field": field,
                                "code": "formula_or_error",
                                "message": "公式或错误单元格不可导入",
                            }
                        )
                rows.append({"row_number": number, **values, "errors": errors})
            if not rows:
                error(400, "no_product_rows", "没有可导入的非空产品行")
            return rows, blank
        finally:
            wb.close()
    except HTTPException:
        raise
    except Exception:
        error(400, "invalid_workbook", "工作簿损坏、加密或格式无效")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def manufacturer_products(db, manufacturer):
    return db.scalars(
        select(LibraryProduct)
        .where(LibraryProduct.manufacturer_name == manufacturer)
        .order_by(LibraryProduct.id)
    ).all()


def baseline(products):
    return digest([product_view(product) for product in products])


def preview_rows(rows, products):
    valid = [row for row in rows if not row["errors"]]
    model_groups, no_model_names = defaultdict(list), defaultdict(list)
    for row in valid:
        (
            model_groups[row["model"]] if row["model"] else no_model_names[row["name"]]
        ).append(row)
    for group in [*model_groups.values(), *no_model_names.values()]:
        if len(group) > 1:
            for row in group:
                others = [item["row_number"] for item in group if item is not row]
                row["errors"].append(
                    {
                        "field": "model" if row["model"] else "name",
                        "code": "duplicate_in_file",
                        "message": f"文件内重复，相关行：{others}",
                        "row_numbers": others,
                    }
                )
    for row in rows:
        row.update(
            candidate=[],
            file_candidates=[],
            existing_id=None,
            version=None,
            diff={},
            allowed_actions=["skip"],
            default_action="skip",
        )
        if row["errors"]:
            row["category"] = "invalid"
            continue
        exact = [
            p for p in products if row["model"] is not None and p.model == row["model"]
        ]
        named = [p for p in products if p.name == row["name"]]
        file_named = (
            [
                r
                for r in valid
                if r is not row and not r["errors"] and r["name"] == row["name"]
            ]
            if row["model"] is None
            else []
        )
        row["file_candidates"] = [
            {field: r[field] for field in ("row_number", "name", "model")}
            for r in file_named
        ]
        if exact:
            product = exact[0]
            old = product_view(product)
            row.update(
                category="existing" if product.name == row["name"] else "conflict",
                existing_id=product.id,
                version=product.version,
            )
            row["candidate"] = [
                {"id": p.id, "name": p.name, "model": p.model} for p in exact
            ]
            for field in FIELDS:
                effective = row[field] if row[field] is not None else old[field]
                row["diff"][field] = {
                    "old": old[field],
                    "incoming": row[field],
                    "effective": effective,
                    "changed": effective != old[field],
                    "preserved": row[field] is None,
                }
            if any(value["changed"] for value in row["diff"].values()):
                row["allowed_actions"].append("update")
        elif named or file_named:
            row["category"] = "suspected"
            row["candidate"] = [
                {"id": p.id, "name": p.name, "model": p.model} for p in named
            ]
            row["allowed_actions"].append("insert")
        else:
            row.update(
                category="new",
                allowed_actions=["insert", "skip"],
                default_action="insert",
            )
    return rows


def receipt(db, import_id):
    try:
        UUID(import_id)
    except ValueError:
        error(404, "import_not_found", "导入预览不存在")
    item = db.get(LibraryImport, import_id)
    if item is None:
        error(404, "import_not_found", "导入预览不存在")
    if item.status == "ready" and utc(item.expires_at) <= now():
        error(410, "preview_expired", "预览已过期，请重新上传")
    return item


def decisions(payload):
    if set(payload) != {"decisions"} or not isinstance(payload["decisions"], list):
        error(422, "invalid_decisions", "必须提供逐行决策")
    result = {}
    for decision in payload["decisions"]:
        if (
            not isinstance(decision, dict)
            or set(decision) != {"row_number", "action"}
            or type(decision["row_number"]) is not int
            or not isinstance(decision["action"], str)
            or decision["action"] not in ("insert", "update", "skip")
            or decision["row_number"] in result
        ):
            error(422, "invalid_decisions", "决策行号或动作无效/重复")
        result[decision["row_number"]] = decision["action"]
    return result


def list_products_service(q, manufacturer, sort, page, page_size, db):
    if sort not in ("updated_desc", "price_asc", "price_desc"):
        error(422, "invalid_product", "排序无效")
    query = select(LibraryProduct)
    if q.strip():
        literal = (
            q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        query = query.where(
            or_(
                *(
                    getattr(LibraryProduct, field).like(f"%{literal}%", escape="\\")
                    for field in (
                        "model",
                        "name",
                        "parameters",
                        "selling_points",
                        "manufacturer_name",
                    )
                )
            )
        )
    if manufacturer is not None:
        try:
            manufacturer = normalized_text(manufacturer, "manufacturer_name")
        except ValueError as exc:
            error(422, "invalid_product", str(exc))
        query = query.where(LibraryProduct.manufacturer_name == manufacturer)
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    ordering = (
        [LibraryProduct.updated_at.desc(), LibraryProduct.id.desc()]
        if sort == "updated_desc"
        else [
            LibraryProduct.wholesale_price_cents.is_(None),
            (
                LibraryProduct.wholesale_price_cents.asc()
                if sort == "price_asc"
                else LibraryProduct.wholesale_price_cents.desc()
            ),
            LibraryProduct.id.desc(),
        ]
    )
    items = db.scalars(
        query.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [product_view(p) for p in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def manufacturers_service(db):
    return {
        "items": db.scalars(
            select(LibraryProduct.manufacturer_name)
            .distinct()
            .order_by(LibraryProduct.manufacturer_name)
        ).all()
    }


def get_product_service(product_id, db):
    return product_view(product_or_404(db, product_id))


def create_product_service(payload, db):
    values = manual_payload(payload)
    try:
        begin_write(db)
        check_duplicates(db, values, payload)
        product = LibraryProduct(created_at=now(), updated_at=now(), version=1)
        assign(product, values)
        db.add(product)
        db.flush()
        result = product_view(product)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        database_error(db, exc, "product_save_failed")


def update_product_service(product_id, payload, db):
    values = manual_payload(payload, editing=True)
    version = version_value(payload)
    try:
        begin_write(db)
        product = product_or_404(db, product_id)
        if product.version != version:
            error(409, "product_stale", "产品已变化，请重新读取")
        check_duplicates(db, values, payload, product_id)
        old = product_view(product)
        if any((old[field] != value for field, value in values.items())):
            assign(product, values)
            product.version += 1
            product.updated_at = now()
        db.flush()
        result = product_view(product)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        database_error(db, exc, "product_save_failed")


def delete_product_service(product_id, payload, db):
    if set(payload) != {"version"}:
        error(422, "invalid_product", "必须仅提供 version")
    version = version_value(payload)
    try:
        begin_write(db)
        product = product_or_404(db, product_id)
        if product.version != version:
            error(409, "product_stale", "产品已变化，请重新读取")
        db.delete(product)
        db.commit()
        return Response(status_code=204)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        database_error(db, exc, "product_save_failed")


def preview_import_service(content, manufacturer_name, db):
    try:
        manufacturer = normalized_text(manufacturer_name, "manufacturer_name")
    except ValueError as exc:
        error(422, "invalid_product", str(exc), field="manufacturer_name")
    rows, blank = read_excel(bytes(content))
    try:
        db.execute(text("BEGIN"))
        products = manufacturer_products(db, manufacturer)
        stamp = baseline(products)
        rows = preview_rows(rows, products)
        db.rollback()
        created = now()
        import_id = str(uuid4())
        counts = {
            key: sum((row["category"] == key for row in rows))
            for key in ("new", "existing", "conflict", "suspected", "invalid")
        }
        counts.update(
            total_rows=len(rows),
            ignored_blank_rows=blank,
            planned_insert=counts["new"],
            planned_update=0,
        )
        result = {
            "import_id": import_id,
            "status": "ready",
            "expires_at": (created + timedelta(minutes=30)).isoformat(),
            "manufacturer_name": manufacturer,
            "counts": counts,
            "rows": rows,
        }
        begin_write(db)
        db.add(
            LibraryImport(
                import_id=import_id,
                manufacturer_name=manufacturer,
                created_at=created,
                expires_at=created + timedelta(minutes=30),
                status="ready",
                preview=result,
                baseline_digest=stamp,
            )
        )
        db.commit()
        return result
    except SQLAlchemyError as exc:
        database_error(db, exc, "import_save_failed")


def get_import_service(import_id, db):
    item = receipt(db, import_id)
    return item.result if item.status == "committed" else item.preview


def confirm_import_service(import_id, payload, db):
    selected = decisions(payload)
    decision_hash = digest(sorted(selected.items()))
    try:
        begin_write(db)
        item = receipt(db, import_id)
        if item.status == "committed":
            if item.decision_digest != decision_hash:
                error(409, "idempotency_conflict", "同一导入已按不同决策提交")
            result = item.result
            db.rollback()
            return result
        rows = item.preview["rows"]
        if set(selected) != {row["row_number"] for row in rows} or any(
            (selected[row["row_number"]] not in row["allowed_actions"] for row in rows)
        ):
            error(422, "invalid_decisions", "必须对全部行提供合法决策")
        if not any((action != "skip" for action in selected.values())):
            error(422, "no_changes_selected", "没有选择新增或更新")
        if (
            baseline(manufacturer_products(db, item.manufacturer_name))
            != item.baseline_digest
        ):
            error(409, "preview_stale", "该厂家产品已变化，请重新上传并确认")
        result = {
            "import_id": import_id,
            "status": "committed",
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "invalid": 0,
            "rows": [],
        }
        for row in rows:
            action = selected[row["row_number"]]
            product_id = None
            if row["category"] == "invalid":
                outcome, reason = ("invalid", "invalid_row")
            elif action == "skip":
                outcome, reason = ("skipped", "user_skipped")
            else:
                values = {field: row[field] for field in FIELDS}
                if action == "insert":
                    product = LibraryProduct(
                        manufacturer_name=item.manufacturer_name,
                        created_at=now(),
                        updated_at=now(),
                        version=1,
                    )
                    assign(product, values)
                    db.add(product)
                    outcome = "inserted"
                else:
                    product = db.get(LibraryProduct, row["existing_id"])
                    assign(
                        product,
                        {
                            field: value
                            for field, value in values.items()
                            if value is not None
                        },
                    )
                    product.version += 1
                    product.updated_at = now()
                    outcome = "updated"
                db.flush()
                product_id, reason = (product.id, outcome)
            result[outcome] += 1
            result["rows"].append(
                {
                    "row_number": row["row_number"],
                    "outcome": outcome,
                    "product_id": product_id,
                    "reason_code": reason,
                }
            )
        item.status = "committed"
        item.decision_digest = decision_hash
        item.result = result
        item.preview = None
        item.baseline_digest = None
        db.flush()
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        database_error(db, exc, "import_save_failed")
