"""Collection parsing boundaries."""

from app.collection.parser_1688 import (
    CollectionParseError,
    OfferIdMismatchError,
    parse_1688_html,
)
from app.collection.types import ProductData, SkuData

__all__ = [
    "CollectionParseError",
    "OfferIdMismatchError",
    "ProductData",
    "SkuData",
    "parse_1688_html",
]
