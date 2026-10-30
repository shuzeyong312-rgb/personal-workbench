import pytest

from app.product_library_simple_prices import parse_wholesale_prices


@pytest.mark.parametrize(("text", "expected"), [
    (None, []),
    (" 0 ", [(None, 0)]),
    ("26元/个", [(None, 2600)]),
    ("5000mAh：26；10000mAh:32元/件\n20000mAh：40.50", [("5000mAh", 2600), ("10000mAh", 3200), ("20000mAh", 4050)]),
    ("999999999.99", [(None, 99999999999)]),
    ("1000000000", None),
    ("A:26; A:27", None),
    ("A:26; 27", None),
    ("A:26:27", None),
    ("A:一件代发26", None),
    ("零售：26", None),
    ("出货价26", None),
    ("26-30", None),
    ("26元/箱", None),
    ("26.123", None),
])
def test_wholesale_price_parser(text, expected):
    assert parse_wholesale_prices(text) == expected
