from decimal import Decimal

import pytest

from lien_import.normalize.money import parse_money


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$12,387.00", Decimal("12387.00")),      # ATT/ESS
        ("12293", Decimal("12293.00")),           # TNU Combined
        ("102,372", Decimal("102372.00")),        # TNU Starter
        ("$1,321,500.00", Decimal("1321500.00")),
        ("$3,100,964", Decimal("3100964.00")),
        (" 28809 ", Decimal("28809.00")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("", None),
        (None, None),
        ("n/a", None),
        ("$", None),
        ("1.2.3", None),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected
