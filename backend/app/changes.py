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

    old_skus = {sku.sku_id: sku for sku in previous.skus}
    new_skus = {sku.sku_id: sku for sku in current.skus}
    for sku_id in sorted(new_skus.keys() - old_skus.keys()):
        changes.append(ChangeDraft("sku_added", sku_id, None, new_skus[sku_id].sku_name))
    for sku_id in sorted(old_skus.keys() - new_skus.keys()):
        changes.append(ChangeDraft("sku_removed", sku_id, old_skus[sku_id].sku_name, None))
    for sku_id in sorted(old_skus.keys() & new_skus.keys()):
        old_stock = old_skus[sku_id].stock
        new_stock = new_skus[sku_id].stock
        if old_stock is not None and new_stock is not None and old_stock != new_stock:
            changes.append(ChangeDraft("stock_changed", sku_id, str(old_stock), str(new_stock)))
    return changes
