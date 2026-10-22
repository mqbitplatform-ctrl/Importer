from datetime import date

import pytest

from lien_import.normalize.dates import is_reasonable, parse_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9/23/19", date(2019, 9, 23)),               # ATT/ESS 2-digit year
        ("8/9/2021", date(2021, 8, 9)),               # TNU Starter
        ("12/14/2021 12:00:00 AM", date(2021, 12, 14)),  # TNU Combined
        ("2/18/2015", date(2015, 2, 18)),
        ("2021-12-14", date(2021, 12, 14)),
        ("", None),
        (None, None),
        ("not a date", None),
        ("13/40/2021", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_is_reasonable():
    assert is_reasonable(date(2019, 9, 23))
    assert not is_reasonable(date(1900, 1, 1))
    assert not is_reasonable(date(2999, 1, 1))
    assert not is_reasonable(None)
