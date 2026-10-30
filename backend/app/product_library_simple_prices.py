"""Parse only unambiguous prices in the single-sheet wholesale template."""
import re
from decimal import Decimal


_AMOUNT = re.compile(r"(\d+(?:\.\d{1,2})?)(?:元/(?:件|个))?\Z")
_MAX_CENTS = 99999999999
_AMBIGUOUS_LABEL = re.compile(r"定制|供货|出货|批发|出厂|零售|代发|控价|价格|报价|单价|含税|未税|税费|运费|包邮|起订|起批|起购|起售|含运|不含|以上|以下|面议|约|起价")


def has_non_wholesale_semantics(value: str | None) -> bool:
    return bool(value and any(word in value for word in ("一件代发", "代发", "零售", "控价", "出货价", "供货价", "定制价")))


def parse_wholesale_prices(value: str | None) -> list[tuple[str | None, int]] | None:
    """Return (variant, cents) pairs; None means the whole cell needs review."""
    if value is None or not value.strip():
        return []
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if has_non_wholesale_semantics(value):
        return None
    parts = [part.strip() for part in re.split(r"[\n;；]", value) if part.strip()]
    if not parts:
        return None
    result = []
    seen = set()
    for part in parts:
        fields = re.split(r"[:：]", part)
        if len(fields) == 1 and len(parts) == 1:
            variant, amount = None, fields[0].strip()
        elif len(fields) == 2 and fields[0].strip():
            variant, amount = fields[0].strip(), fields[1].strip()
            if _AMBIGUOUS_LABEL.search(variant):
                return None
        else:
            return None
        match = _AMOUNT.fullmatch(amount)
        if not match or variant in seen:
            return None
        amount_decimal = Decimal(match.group(1))
        if amount_decimal > Decimal(_MAX_CENTS) / 100:
            return None
        cents = int(amount_decimal * 100)
        seen.add(variant)
        result.append((variant, cents))
    return result
