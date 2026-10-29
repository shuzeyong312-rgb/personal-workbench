"""Validated relational details; callers own the single write transaction."""
import json
import re
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models import LibraryProduct, LibraryProductVariant, LibraryProductSource, LibraryProductPrice
from app.product_library_service import begin_write, database_error, error, now, price, product_or_404, require_identity_schema, utc

MODELS = {"variants": LibraryProductVariant, "sources": LibraryProductSource, "prices": LibraryProductPrice}
FIELDS = {
    "variants": ("variant_code", "variant_name", "color", "structured_attributes", "notes"),
    "sources": ("source_company", "claimed_manufacturer_name", "source_file_name", "source_page", "source_date", "source_type", "source_excerpt", "notes"),
    "prices": ("variant_id", "source_id", "price_type", "price_channel", "amount_text", "currency_code", "price_unit", "min_order_quantity", "min_order_unit", "tax_mode", "freight_mode", "freight_amount_cents", "customization_terms", "terms_text", "notes", "source_excerpt", "quote_date", "is_default_wholesale"),
}
SOURCE_KEY = ("source_company", "source_file_name", "source_page", "source_date", "source_type", "source_excerpt")
PRICE_KEY = ("variant_id", "price_type", "price_channel", "currency_code", "price_unit", "source_id", "quote_date", "min_order_quantity", "min_order_unit", "customization_terms")
PRICE_TYPES = ("出厂价", "批发价", "一件代发价", "定制价", "平台控价", "建议零售价", "零售价", "其他")
PURCHASE_TYPES = PRICE_TYPES[:3]
TAX_MODES = ("unknown", "included", "excluded")
FREIGHT_MODES = (*TAX_MODES, "extra", "negotiable")
SOURCE_TYPES = ("quote", "catalog", "specification", "other")
# ISO 4217 active currencies, including fund and precious-metal codes; no conversion.
CURRENCIES = set("AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU XTS XUA XXX YER ZAR ZMW ZWG".split())
ATTACHMENT_WARNING = "未保存图片及原始文件，请自行保留原件。文件名和页码仅为来源元数据。"


def detail_view(record, kind):
    return {"id": record.id, "product_id": record.product_id, "version": record.version,
            **{field: getattr(record, field) for field in FIELDS[kind]},
            "created_at": utc(record.created_at).isoformat(), "updated_at": utc(record.updated_at).isoformat()}


def records(db, product_id, kind):
    return db.scalars(select(MODELS[kind]).where(MODELS[kind].product_id == product_id).order_by(MODELS[kind].id)).all()


def product_details(db, product):
    return {"structured_attributes": product.structured_attributes, **{kind: [detail_view(record, kind) for record in records(db, product.id, kind)] for kind in MODELS}}


def text_value(value, field, limit=200, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须为文本")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if field == "source_company":
        value = " ".join(value.split())
    if len(value) > limit or required and not value:
        raise ValueError(f"{field} 必填或超过 {limit} 字符")
    return value or None


def decimal_text(value, *, currency=None, quantity=False):
    value = text_value(value, "数量" if quantity else "金额", 44)
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("金额/数量必须为非负普通十进制文本")
    number = Decimal(value)
    if quantity:
        if number <= 0 or len(value.split('.')[0].lstrip('0')) > 12 or number.as_tuple().exponent < -6:
            raise ValueError("起订量必须为正数，最多12位整数和6位小数")
    elif currency == "CNY":
        price(value)
    elif len(number.as_tuple().digits) > 30 or number.as_tuple().exponent < -12:
        raise ValueError("金额最多30位有效数字、12位小数")
    return format(number, "f").rstrip('0').rstrip('.') if '.' in format(number, "f") else str(int(number))


def date_value(value, field):
    value = text_value(value, field, 10)
    if value is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError(f"{field} 使用 YYYY-MM-DD")
        date.fromisoformat(value)
    return value


def attributes(value, db, product_id):
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("参数明细必须为数组")
    allowed = {"group", "name", "value", "unit", "condition", "source_id", "source_excerpt", "review_status"}
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) - allowed:
            raise ValueError("参数明细含未知字段")
        source_id = item.get("source_id")
        if source_id is not None:
            related(db, LibraryProductSource, source_id, product_id)
        data = {field: text_value(item.get(field), field, 10000 if field in ("value", "source_excerpt") else 200, field == "name") for field in allowed - {"source_id", "review_status"}}
        state = item.get("review_status", "confirmed")
        if state not in ("confirmed", "needs_review") or data['value'] is None and data['source_excerpt'] is None:
            raise ValueError("参数缺少值/摘录或核对状态无效")
        result.append({**data, "source_id": source_id, "review_status": "needs_review" if data['value'] is None else state})
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 100 * 1024:
        raise ValueError("参数明细超过100 KiB")
    return result


def related(db, model, record_id, product_id):
    if type(record_id) is not int or record_id < 1:
        raise ValueError("关联ID必须为正整数")
    record = db.get(model, record_id)
    if record is None or record.product_id != product_id:
        raise ValueError("关联记录不存在或属于其他产品")
    return record


def validate_detail(kind, raw, db, product_id, *, synthetic=False, defer_references=False):
    if set(raw) - set(FIELDS[kind]):
        raise ValueError("含未知字段")
    data = {}
    for field in FIELDS[kind]:
        value = raw.get(field)
        if field in ("variant_id", "source_id"):
            if value is not None and not defer_references:
                related(db, LibraryProductVariant if field == "variant_id" else LibraryProductSource, value, product_id)
            elif field == "source_id" and not defer_references:
                raise ValueError("价格必须关联来源")
            data[field] = value
        elif field == "structured_attributes":
            data[field] = attributes(value, db, product_id)
        elif field == "is_default_wholesale":
            if value is not None and type(value) is not bool:
                raise ValueError("默认标记必须为布尔值")
            data[field] = value or False
        elif field == "freight_amount_cents":
            if value is not None and (type(value) is not int or not 0 <= value <= 99999999999):
                raise ValueError("人民币运费分必须为非负整数")
            data[field] = value
        elif field in ("source_date", "quote_date"):
            data[field] = date_value(value, field)
        else:
            limit = 30000 if synthetic and field == "source_excerpt" and kind == "sources" else 10000 if field in ("notes", "terms_text", "source_excerpt", "customization_terms") else 500 if field in ("source_file_name", "source_page") else 200
            data[field] = text_value(value, field, limit, field in ("variant_name", "price_type"))
    if kind == "sources":
        data['source_type'] = data['source_type'] or 'other'
        if data['source_type'] not in SOURCE_TYPES:
            raise ValueError("资料类型无效")
    if kind == "prices":
        data['tax_mode'] = data['tax_mode'] or 'unknown'
        data['freight_mode'] = data['freight_mode'] or 'unknown'
        if data['price_type'] not in PRICE_TYPES or data['tax_mode'] not in TAX_MODES or data['freight_mode'] not in FREIGHT_MODES:
            raise ValueError("价格类型/税运费口径无效")
        if data['currency_code'] is not None and data['currency_code'] not in CURRENCIES:
            raise ValueError("币种必须为大写 ISO 4217 代码")
        data['amount_text'] = decimal_text(data['amount_text'], currency=data['currency_code'])
        data['min_order_quantity'] = decimal_text(data['min_order_quantity'], quantity=True)
        if data['min_order_quantity'] is not None and not data['min_order_unit']:
            raise ValueError("起订量必须有单位")
        if data['freight_amount_cents'] is not None and data['currency_code'] != 'CNY':
            raise ValueError("结构化运费只允许人民币")
        source = None if defer_references else related(db, LibraryProductSource, data['source_id'], product_id)
        if source and data['quote_date'] and source.source_date and data['quote_date'] != source.source_date:
            raise ValueError("报价日期与来源日期冲突")
        data['quote_date'] = data['quote_date'] or (source.source_date if source else None)
        if data['price_type'] == '其他' and not (data['source_excerpt'] or data['terms_text']):
            raise ValueError("其他价格类型必须保留原文说明")
        if data['is_default_wholesale'] and not default_eligible(data):
            raise ValueError("默认价必须为金额已知、人民币/件的批发价")
    return data


def default_eligible(data):
    return data['price_type'] == '批发价' and data['currency_code'] == 'CNY' and data['price_unit'] == '件' and data['amount_text'] is not None


def touch(product):
    product.version += 1
    product.updated_at = now()


def project_price(db, product):
    defaults = [row for row in records(db, product.id, 'prices') if row.is_default_wholesale]
    if any(row.variant_id is None for row in defaults) and any(row.variant_id is not None for row in defaults):
        error(409, 'default_price_selection_required', '产品级与规格级默认价不能共存，请明确取消旧默认项')
    default = next((row for row in defaults if row.variant_id is None), None)
    product.wholesale_price_cents = None if default is None else int(Decimal(default.amount_text) * 100)


def legacy_source(db, product, excerpt=None):
    data = dict(source_company=product.manufacturer_name, source_type='other', source_excerpt=excerpt, notes='legacy_input')
    existing = next((row for row in records(db, product.id, 'sources') if all(getattr(row, key) == data.get(key) for key in SOURCE_KEY)), None)
    if existing:
        return existing
    source = LibraryProductSource(product_id=product.id, **data, created_at=now(), updated_at=now(), version=1)
    db.add(source)
    db.flush()
    return source


def legacy_price(db, product, amount, *, creating=False):
    rows = records(db, product.id, 'prices')
    if creating and amount is not None:
        source = legacy_source(db, product)
        db.add(LibraryProductPrice(product_id=product.id, source_id=source.id, price_type='批发价', currency_code='CNY', price_unit='件', amount_text=decimal_text(amount, currency='CNY'), tax_mode='unknown', freight_mode='unknown', is_default_wholesale=True, created_at=now(), updated_at=now(), version=1))
    elif not creating:
        current = None if product.wholesale_price_cents is None else f"{Decimal(product.wholesale_price_cents)/100:.2f}"
        if current == amount:
            return
        defaults = [row for row in rows if row.is_default_wholesale]
        if any(row.variant_id is not None for row in defaults):
            error(409, 'default_price_selection_required', '存在规格默认价，请在价格明细操作')
        if amount is None:
            for row in defaults:
                row.is_default_wholesale = False
                row.version += 1
                row.updated_at = now()
        elif len(defaults) == 1:
            if sum(row.variant_id is None and row.price_type == '批发价' and row.currency_code == 'CNY' and row.price_unit == '件' and row.amount_text is not None for row in rows) > 1:
                error(409, 'default_price_selection_required', '存在多个批发价候选，请在价格明细明确操作')
            defaults[0].amount_text = decimal_text(amount, currency='CNY')
            defaults[0].version += 1
            defaults[0].updated_at = now()
        else:
            error(409, 'default_price_selection_required', '请明确选择默认价格记录')
    db.flush()
    project_price(db, product)


def mutate_detail(product_id, kind, record_id, payload, method, db):
    if kind not in MODELS:
        error(404, 'record_not_found', '关联资料不存在')
    try:
        begin_write(db)
        require_identity_schema(db)
        product = product_or_404(db, product_id)
        if type(payload.get('product_version')) is not int or payload['product_version'] != product.version:
            error(409, 'product_stale', '产品已变化，请重新读取')
        allowed = set(FIELDS[kind]) | {'product_version', 'version', 'set_default'}
        if set(payload) - allowed or method == 'DELETE' and set(payload) != {'product_version', 'version'}:
            raise ValueError('含未知字段')
        record = None if record_id is None else related(db, MODELS[kind], record_id, product_id)
        if record is not None and (type(payload.get('version')) is not int or payload['version'] != record.version):
            error(409, 'product_stale', '关联记录已变化')
        changed = False
        if method == 'DELETE':
            if kind in ('variants', 'sources'):
                field = 'variant_id' if kind == 'variants' else 'source_id'
                used = any(getattr(row, field) == record.id for row in records(db, product_id, 'prices'))
                if kind == 'variants':
                    used |= bool(record.structured_attributes)
                if kind == 'sources':
                    containers = [product, *records(db, product_id, 'variants')]
                    used |= any(item.get('source_id') == record.id for container in containers for item in container.structured_attributes or [])
                if used:
                    error(409, 'related_record_in_use', '仍被价格或参数引用，请先处理依赖')
            db.delete(record)
            changed = True
        else:
            raw = {**({field: getattr(record, field) for field in FIELDS[kind]} if record else {}), **{key: value for key, value in payload.items() if key in FIELDS[kind]}}
            if 'set_default' in payload:
                if kind != 'prices' or type(payload['set_default']) is not bool:
                    raise ValueError('set_default 仅用于价格且必须为布尔值')
                raw['is_default_wholesale'] = payload['set_default']
            if kind == 'prices' and payload.get('set_default') is True:
                for other in records(db, product_id, 'prices'):
                    if other.id != record_id and other.is_default_wholesale and other.variant_id == raw.get('variant_id'):
                        other.is_default_wholesale = False
                        other.version += 1
                        other.updated_at = now()
                db.flush()
            data = validate_detail(kind, raw, db, product_id, synthetic=kind == 'sources' and record is not None and len(record.source_excerpt or '') > 10000)
            if record is None:
                record = MODELS[kind](product_id=product_id, **data, created_at=now(), updated_at=now(), version=1)
                db.add(record)
                changed = True
            elif any(getattr(record, key) != value for key, value in data.items()):
                for key, value in data.items():
                    setattr(record, key, value)
                record.version += 1
                record.updated_at = now()
                changed = True
        db.flush()
        project_price(db, product)
        if changed:
            touch(product)
        result = None if method == 'DELETE' else {**detail_view(record, kind), 'product_version': product.version}
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        error(422, 'invalid_product', str(exc))
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        database_error(db, exc, 'product_save_failed')
