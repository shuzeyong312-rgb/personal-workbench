from dataclasses import dataclass, field
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
    image_urls: list[str] = field(default_factory=list)
    min_order_quantity: int | None = None


@dataclass(frozen=True)
class OperatingMetricData:
    metric_key: str
    status: str
    raw_value: str | None
    source: str
    offer_id: str
    observed_at: datetime
    reason: str | None = None


@dataclass(frozen=True)
class CollectionPageResult:
    offer_id: str
    product: ProductData | None
    product_error: Exception | None
    operating_metrics: list[OperatingMetricData]
