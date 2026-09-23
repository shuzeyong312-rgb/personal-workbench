from dataclasses import dataclass
from decimal import Decimal

from app.collection.types import ProductData
from app.models import ProductSnapshot


@dataclass(frozen=True)
class ChangeDraft:
    change_type: str
    entity_key: str | None
    old_value: str | None
    new_value: str | None
    delta_value: Decimal | None = None
    delta_rate: Decimal | None = None


def _numeric_delta(old: Decimal, new: Decimal) -> tuple[Decimal, Decimal | None]:
    delta = new - old
    return delta, (delta / old * Decimal("100")) if old != 0 else None


def _valid_positive_integer(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _format_price_range(price_min: Decimal, price_max: Decimal) -> str:
    minimum = f"{price_min:.2f}"
    maximum = f"{price_max:.2f}"
    return minimum if price_min == price_max else f"{minimum}~{maximum}"


def detect_changes(
    previous: ProductSnapshot | None,
    current: ProductData,
) -> list[ChangeDraft]:
    if previous is None:
        return []

    changes: list[ChangeDraft] = []
    if (
        previous.price_min is not None
        and previous.price_max is not None
        and current.price_min is not None
        and current.price_max is not None
    ):
        change_type: str | None = None
        if current.price_min > previous.price_min and current.price_max > previous.price_max:
            change_type = "price_increase"
        elif current.price_min < previous.price_min and current.price_max < previous.price_max:
            change_type = "price_decrease"
        if change_type is not None:
            changes.append(
                ChangeDraft(
                    change_type,
                    None,
                    _format_price_range(previous.price_min, previous.price_max),
                    _format_price_range(current.price_min, current.price_max),
                    *_numeric_delta(previous.price_min, current.price_min)
                    if previous.price_min == previous.price_max and current.price_min == current.price_max
                    else (None, None),
                )
            )

    old_skus = {sku.sku_id: sku for sku in previous.skus}
    new_skus = {sku.sku_id: sku for sku in current.skus}
    for sku_id in sorted(old_skus.keys() & new_skus.keys()):
        old_price = old_skus[sku_id].price
        new_price = new_skus[sku_id].price
        if old_price is not None and new_price is not None and old_price != new_price:
            change_type = "price_increase" if new_price > old_price else "price_decrease"
            delta_value, delta_rate = _numeric_delta(old_price, new_price)
            changes.append(
                ChangeDraft(
                    change_type,
                    sku_id,
                    f"{old_price:.2f}",
                    f"{new_price:.2f}",
                    delta_value,
                    delta_rate,
                )
            )

    for sku_id in sorted(old_skus.keys() & new_skus.keys()):
        old_stock = old_skus[sku_id].stock
        new_stock = new_skus[sku_id].stock
        if old_stock is None or new_stock is None or old_stock == new_stock:
            continue
        if old_stock > 0 and new_stock == 0:
            change_type = "sku_sold_out"
        elif old_stock == 0 and new_stock > 0:
            change_type = "sku_restocked"
        elif old_stock > 0 and new_stock > 0:
            change_type = "stock_increase" if new_stock > old_stock else "stock_decrease"
        else:
            continue
        delta_value, delta_rate = _numeric_delta(Decimal(old_stock), Decimal(new_stock))
        changes.append(
            ChangeDraft(
                change_type,
                sku_id,
                str(old_stock),
                str(new_stock),
                delta_value,
                delta_rate,
            )
        )

    for sku_id in sorted(new_skus.keys() - old_skus.keys()):
        changes.append(ChangeDraft("sku_added", sku_id, None, new_skus[sku_id].sku_name))
    for sku_id in sorted(old_skus.keys() - new_skus.keys()):
        changes.append(ChangeDraft("sku_removed", sku_id, old_skus[sku_id].sku_name, None))

    if (
        _valid_positive_integer(previous.min_order_quantity)
        and _valid_positive_integer(current.min_order_quantity)
        and previous.min_order_quantity != current.min_order_quantity
    ):
        old_quantity = previous.min_order_quantity
        new_quantity = current.min_order_quantity
        delta_value, delta_rate = _numeric_delta(Decimal(old_quantity), Decimal(new_quantity))
        changes.append(
            ChangeDraft(
                "min_order_quantity_increase" if new_quantity > old_quantity else "min_order_quantity_decrease",
                None,
                str(old_quantity),
                str(new_quantity),
                delta_value,
                delta_rate,
            )
        )

    old_title = previous.title.strip() if isinstance(previous.title, str) else ""
    new_title = current.title.strip() if isinstance(current.title, str) else ""
    if old_title and new_title and old_title != new_title:
        changes.append(ChangeDraft("title_changed", None, old_title, new_title))

    if previous.main_image_url and current.main_image_url and previous.main_image_url != current.main_image_url:
        changes.append(
            ChangeDraft(
                "main_image_changed",
                None,
                previous.main_image_url,
                current.main_image_url,
            )
        )
    return changes
