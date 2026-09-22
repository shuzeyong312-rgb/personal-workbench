from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class SkuData:
    sku_id: str
    sku_name: str
    stock: int | None
    price: Decimal | None


@dataclass(frozen=True)
class ProductData:
    offer_id: str
    title: str
    shop_name: str
    main_image_url: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    product_status: str
    collection_source: str
    captured_at: datetime
    skus: list[SkuData]
    min_order_quantity: int | None = None
