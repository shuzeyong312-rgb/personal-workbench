"""Collection parsing boundaries."""

from app.collection.collector_1688 import (
    CollectionTimeoutError,
    CollectorError,
    LoginRequiredError,
    PageUnavailableError,
    VerificationRequiredError,
    collect_1688_product,
)
from app.collection.parser_1688 import (
    CollectionParseError,
    OfferIdMismatchError,
    parse_1688_html,
)
from app.collection.types import ProductData, SkuData

__all__ = [
    "CollectionTimeoutError",
    "CollectorError",
    "CollectionParseError",
    "LoginRequiredError",
    "OfferIdMismatchError",
    "PageUnavailableError",
    "ProductData",
    "SkuData",
    "VerificationRequiredError",
    "collect_1688_product",
    "parse_1688_html",
]
