"""Supplier evidence, price versions and explicit eligibility review."""
from sqlalchemy import func, select

from app.models import (
    LibraryProduct, LibrarySimpleEligibilityAudit, LibrarySimpleProductEvent, LibrarySimpleQuoteEvidence,
    LibrarySimpleQuoteKey, LibrarySimpleQuoteVersion, LibrarySimpleSource, LibrarySimpleSourceEvent,
)
from app.product_library_service import begin_write, error, now
from app.product_library_simple_prices import has_non_wholesale_semantics, parse_wholesale_prices


def simple_details(product, db):
    sources = db.scalars(select(LibrarySimpleSource).where(LibrarySimpleSource.product_id == product.id).order_by(LibrarySimpleSource.id)).all()
    keys = db.scalars(select(LibrarySimpleQuoteKey).where(LibrarySimpleQuoteKey.product_id == product.id).order_by(LibrarySimpleQuoteKey.id)).all()
    key_ids = [key.id for key in keys]
    quotes = db.scalars(select(LibrarySimpleQuoteVersion).where(LibrarySimpleQuoteVersion.quote_key_id.in_(key_ids)).order_by(LibrarySimpleQuoteVersion.id)).all() if key_ids else []
    links = db.scalars(select(LibrarySimpleQuoteEvidence).where(LibrarySimpleQuoteEvidence.product_id == product.id)).all()
    return {
        'sources': [dict(id=s.id, supplier_name=s.supplier_name, source_type=s.source_type, file_sha256=s.file_sha256, file_name=s.file_name,
                         sheet_name=s.sheet_name, row_number=s.row_number, raw_values=s.raw_values,
                         price_text=s.price_text, notes=s.notes, version=s.version, archived=bool(s.archived_at), created_at=s.created_at.isoformat()) for s in sources],
        'quotes': [dict(id=q.id, key_id=q.quote_key_id, supplier_name=k.supplier_name, variant=k.variant,
                        version_number=q.version_number, amount_cents=q.amount_cents, currency=q.currency,
                        unit=q.unit, eligibility=q.eligibility, is_current=q.is_current,
                        source_ids=[link.source_id for link in links if link.quote_version_id == q.id])
                   for k in keys for q in quotes if q.quote_key_id == k.id],
    }


def manual_quote(product_id, payload, db):
    if set(payload) != {"product_version", "supplier", "variant", "price_text", "conditions", "idempotency_key"}:
        error(422, "invalid_quote", "请完整填写供应商、规格、价格、条件和幂等键")
    supplier = payload["supplier"]
    variant = payload["variant"]
    price_text = payload["price_text"]
    conditions = payload["conditions"]
    request_key = payload["idempotency_key"]
    if not isinstance(supplier, str) or not (supplier := " ".join(supplier.split())) or len(supplier) > 200:
        error(422, "invalid_quote", "供应商名称无效")
    if variant is not None and not isinstance(variant, str):
        error(422, "invalid_quote", "规格无效")
    variant = variant.replace('\r\n', '\n').replace('\r', '\n').strip() or None if variant is not None else None
    if variant and len(variant) > 200:
        error(422, "invalid_quote", "规格无效")
    if not isinstance(price_text, str) or len(price_text) > 10000 or not isinstance(conditions, str) or len(conditions) > 10000 or not conditions.strip():
        error(422, "invalid_quote", "请填写价格原文和来源条件")
    if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 200:
        error(422, "invalid_quote", "幂等键无效")
    parsed = parse_wholesale_prices(price_text)
    if parsed is None or len(parsed) != 1 or parsed[0][0] is not None:
        error(422, "invalid_quote", "请填写明确的单个人民币元/件价格")
    if type(payload["product_version"]) is not int:
        error(422, "invalid_quote", "产品版本无效")
    begin_write(db)
    product = db.get(LibraryProduct, product_id)
    if product is None or product.archived_at is not None:
        error(404, "product_not_found", "产品不存在或已归档")
    existing = db.scalar(select(LibrarySimpleSource).where(LibrarySimpleSource.manual_key == request_key))
    if existing:
        if (existing.product_id, existing.supplier_name, existing.price_text, existing.notes, (existing.raw_values or {}).get('variant')) != (product_id, supplier, price_text, conditions, variant):
            error(409, "idempotency_conflict", "幂等键已用于不同报价")
        return {"source_id": existing.id, "quote_version_id": (existing.raw_values or {}).get('quote_version_id'),
                "requires_source_confirmation": (existing.raw_values or {}).get('requires_source_confirmation', False), "replayed": True}
    if product.version != payload["product_version"]:
        error(409, "product_stale", "产品已变化，请重新读取")
    key = db.scalar(select(LibrarySimpleQuoteKey).where(LibrarySimpleQuoteKey.product_id == product_id, LibrarySimpleQuoteKey.supplier_name == supplier, LibrarySimpleQuoteKey.variant == variant))
    if key is None:
        key = LibrarySimpleQuoteKey(product_id=product_id, supplier_name=supplier, variant=variant)
        db.add(key)
        db.flush()
    current = db.scalar(select(LibrarySimpleQuoteVersion).where(LibrarySimpleQuoteVersion.quote_key_id == key.id, LibrarySimpleQuoteVersion.is_current.is_(True)))
    source = LibrarySimpleSource(product_id=product_id, supplier_name=supplier, source_type="manual", price_text=price_text, notes=conditions, manual_key=request_key, raw_values={"variant": variant}, created_at=now(), version=1)
    db.add(source)
    db.flush()
    needs_source_review = bool(current and current.amount_cents == parsed[0][1] and current.eligibility == 'eligible')
    if needs_source_review:
        quote = current
    elif current and current.amount_cents == parsed[0][1] and current.eligibility == "pending":
        quote = current
    else:
        next_version = (db.scalar(select(func.max(LibrarySimpleQuoteVersion.version_number)).where(LibrarySimpleQuoteVersion.quote_key_id == key.id)) or 0) + 1
        if current:
            current.is_current = False
            db.flush()
        quote = LibrarySimpleQuoteVersion(quote_key_id=key.id, version_number=next_version, amount_cents=parsed[0][1], currency="CNY", unit="件", eligibility="pending", is_current=True, created_at=now())
        db.add(quote)
        db.flush()
    if not needs_source_review:
        db.add(LibrarySimpleQuoteEvidence(quote_version_id=quote.id, quote_key_id=key.id, product_id=product_id, source_id=source.id))
    source.raw_values = {'variant': variant, 'quote_version_id': quote.id, 'requires_source_confirmation': needs_source_review}
    product.version += 1
    product.updated_at = now()
    db.commit()
    return {"source_id": source.id, "quote_version_id": quote.id, "replayed": False, "requires_source_confirmation": needs_source_review}


def confirm_same_price_source(product_id, quote_id, payload, db):
    if set(payload) != {'product_version', 'source_id', 'reason'} or type(payload['source_id']) is not int or type(payload['product_version']) is not int or not isinstance(payload['reason'], str) or not payload['reason'].strip():
        error(422, 'invalid_quote', '请明确选择来源并填写核对依据')
    begin_write(db)
    product = db.get(LibraryProduct, product_id)
    quote = db.get(LibrarySimpleQuoteVersion, quote_id)
    key = db.get(LibrarySimpleQuoteKey, quote.quote_key_id) if quote else None
    source = db.get(LibrarySimpleSource, payload['source_id'])
    if product is None or product.archived_at or product.version != payload['product_version'] or quote is None or key is None or source is None:
        error(409, 'quotation_stale', '产品或报价已变化，请重新读取')
    if key.product_id != product_id or source.product_id != product_id or source.archived_at is not None or source.supplier_name != key.supplier_name or source.source_type != 'manual' or not quote.is_current or quote.eligibility != 'eligible':
        error(422, 'invalid_quote', '来源与当前合格报价不匹配')
    if has_non_wholesale_semantics(source.notes) or (source.raw_values or {}).get('variant') != key.variant or parse_wholesale_prices(source.price_text) != [(None, quote.amount_cents)]:
        error(422, 'invalid_quote', '来源价格语义、金额或规格不匹配')
    if db.get(LibrarySimpleQuoteEvidence, (quote.id, source.id)) is None:
        db.add(LibrarySimpleQuoteEvidence(quote_version_id=quote.id, quote_key_id=key.id, product_id=product_id, source_id=source.id))
        db.add(LibrarySimpleEligibilityAudit(quote_version_id=quote.id, before_status='eligible', after_status='eligible', reason=payload['reason'].strip(), created_at=now()))
        product.version += 1
        product.updated_at = now()
    db.commit()
    return {'quote_version_id': quote.id, 'source_id': source.id, 'product_version': product.version}


def review_quote(product_id, quote_id, payload, db):
    if set(payload) != {"product_version", "status", "reason", "source_id"} or type(payload.get('source_id')) is not int or payload["status"] not in ("pending", "eligible", "ineligible") or not isinstance(payload["reason"], str) or not payload["reason"].strip() or len(payload["reason"]) > 10000:
        error(422, "invalid_quote", "请选择资格状态并填写核对依据")
    begin_write(db)
    product = db.get(LibraryProduct, product_id)
    quote = db.get(LibrarySimpleQuoteVersion, quote_id)
    key = db.get(LibrarySimpleQuoteKey, quote.quote_key_id) if quote else None
    if product is None or product.archived_at is not None or quote is None or key is None or key.product_id != product_id or not quote.is_current:
        error(404, "quote_not_found", "当前报价不存在")
    if type(payload["product_version"]) is not int or product.version != payload["product_version"]:
        error(409, "product_stale", "产品已变化，请重新读取")
    evidence = db.get(LibrarySimpleQuoteEvidence, (quote.id, payload['source_id']))
    source = db.get(LibrarySimpleSource, payload['source_id'])
    if evidence is None or source is None or source.archived_at is not None or source.product_id != product_id or source.supplier_name != key.supplier_name:
        error(422, 'invalid_quote', '必须选择该报价的来源证据')
    if payload["status"] == "eligible" and (quote.currency != "CNY" or quote.unit != "件"):
        error(422, "invalid_quote", "仅可确认人民币元/件的报价")
    if payload['status'] == 'eligible' and source.price_text is not None:
        parsed = parse_wholesale_prices(source.price_text)
        expected = (None, quote.amount_cents) if source.source_type == 'manual' else (key.variant, quote.amount_cents)
        if parsed is None or expected not in parsed or source.source_type == 'manual' and (source.raw_values or {}).get('variant') != key.variant:
            error(422, 'invalid_quote', '来源价格语义、规格或金额不匹配，不能确认合格')
    if payload['status'] == 'eligible' and has_non_wholesale_semantics(source.notes):
        error(422, 'invalid_quote', '来源备注含非出厂价格语义，请先核对')
    evidence_count = len(db.scalars(select(LibrarySimpleQuoteEvidence).where(LibrarySimpleQuoteEvidence.quote_version_id == quote.id)).all())
    if payload['status'] == 'eligible' and quote.eligibility != 'eligible' and evidence_count > 1:
        quote.is_current = False
        db.flush()
        replacement = LibrarySimpleQuoteVersion(quote_key_id=key.id, version_number=quote.version_number + 1, amount_cents=quote.amount_cents,
                                                currency=quote.currency, unit=quote.unit, eligibility='pending', is_current=True, created_at=now())
        db.add(replacement)
        db.flush()
        db.add(LibrarySimpleQuoteEvidence(quote_version_id=replacement.id, quote_key_id=key.id, product_id=product_id, source_id=source.id))
        quote = replacement
    if quote.eligibility != payload["status"]:
        db.add(LibrarySimpleEligibilityAudit(quote_version_id=quote.id, before_status=quote.eligibility, after_status=payload["status"], reason=payload["reason"].strip(), created_at=now()))
        quote.eligibility = payload["status"]
        product.version += 1
        product.updated_at = now()
    db.commit()
    return {"quote_version_id": quote.id, "eligibility": quote.eligibility, "product_version": product.version}


def archive_product(product, db):
    product.archived_at = now()
    product.updated_at = now()
    product.version += 1
    db.add(LibrarySimpleProductEvent(product_id=product.id, action='archive', product_version=product.version, created_at=now()))
    quotes = db.scalars(select(LibrarySimpleQuoteVersion).join(LibrarySimpleQuoteKey).where(
        LibrarySimpleQuoteKey.product_id == product.id,
        LibrarySimpleQuoteVersion.is_current.is_(True),
        LibrarySimpleQuoteVersion.eligibility == "eligible",
    )).all()
    for quote in quotes:
        db.add(LibrarySimpleEligibilityAudit(quote_version_id=quote.id, before_status="eligible", after_status="pending", reason="产品归档后需重新确认", created_at=now()))
        quote.eligibility = "pending"


def restore_product(product_id, payload, db):
    if set(payload) != {"version"} or type(payload["version"]) is not int:
        error(422, "invalid_product", "必须提供产品版本")
    begin_write(db)
    product = db.get(LibraryProduct, product_id)
    if product is None or product.archived_at is None:
        error(404, "product_not_found", "归档产品不存在")
    if product.version != payload["version"]:
        error(409, "product_stale", "产品已变化，请重新读取")
    product.archived_at = None
    product.version += 1
    product.updated_at = now()
    db.add(LibrarySimpleProductEvent(product_id=product.id, action='restore', product_version=product.version, created_at=now()))
    db.commit()
    return {"id": product.id, "version": product.version}


def archive_source(product_id, source_id, payload, db):
    if set(payload) != {'product_version', 'source_version'} or any(type(payload[k]) is not int for k in payload):
        error(422, 'invalid_source', '必须提供产品和来源版本')
    begin_write(db)
    product = db.get(LibraryProduct, product_id)
    source = db.get(LibrarySimpleSource, source_id)
    if product is None or product.archived_at is not None or source is None or source.product_id != product_id or source.archived_at is not None:
        error(404, 'source_not_found', '来源不存在或已停用')
    if product.version != payload['product_version'] or source.version != payload['source_version']:
        error(409, 'source_stale', '产品或来源已变化，请重新读取')
    source.archived_at = now()
    source.version += 1
    product.version += 1
    product.updated_at = now()
    db.add(LibrarySimpleSourceEvent(source_id=source.id, source_version=source.version, created_at=now()))
    db.flush()
    quotes = db.scalars(select(LibrarySimpleQuoteVersion).join(LibrarySimpleQuoteEvidence).where(
        LibrarySimpleQuoteEvidence.source_id == source.id, LibrarySimpleQuoteVersion.is_current.is_(True),
        LibrarySimpleQuoteVersion.eligibility == 'eligible')).all()
    for quote in quotes:
        active = db.scalar(select(LibrarySimpleQuoteEvidence.source_id).join(LibrarySimpleSource).where(
            LibrarySimpleQuoteEvidence.quote_version_id == quote.id, LibrarySimpleSource.archived_at.is_(None)).limit(1))
        if active is None:
            db.add(LibrarySimpleEligibilityAudit(quote_version_id=quote.id, before_status='eligible', after_status='pending', reason='合格报价的来源均已停用', created_at=now()))
            quote.eligibility = 'pending'
    db.commit()


def archive_quote(product_id, quote_id, payload, db):
    if set(payload) != {'product_version'} or type(payload['product_version']) is not int:
        error(422, 'invalid_quote', '必须提供产品版本')
    begin_write(db)
    product = db.get(LibraryProduct, product_id)
    quote = db.get(LibrarySimpleQuoteVersion, quote_id)
    key = db.get(LibrarySimpleQuoteKey, quote.quote_key_id) if quote else None
    if product is None or product.archived_at is not None or quote is None or key is None or key.product_id != product_id or not quote.is_current:
        error(404, 'quote_not_found', '当前报价不存在')
    if product.version != payload['product_version']:
        error(409, 'product_stale', '产品已变化，请重新读取')
    quote.is_current = False
    db.add(LibrarySimpleEligibilityAudit(quote_version_id=quote.id, before_status=quote.eligibility, after_status=quote.eligibility, reason='报价已停用', created_at=now()))
    product.version += 1
    product.updated_at = now()
    db.commit()
