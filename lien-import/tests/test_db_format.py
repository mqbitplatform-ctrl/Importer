"""Output formatting must match the existing rows in zm_dba.liens (verified
against the live table): UPPER-case ASCII text, 5-digit ZIPs, counties with
no COUNTY/PARISH suffix and no '.' or "'", 'Saint' spelled out."""

import pytest

from lien_import.normalize.text import to_db_county, to_db_text, to_db_zip


@pytest.mark.parametrize("raw, expected", [
    ("Jeffrey M Trexler", "JEFFREY M TREXLER"),
    ("  3801  W Campo Bello Dr ", "3801 W CAMPO BELLO DR"),
    ("José Núñez", "JOSE NUNEZ"),          # zm_dba has zero non-ASCII names
    ("1 Amazing Home Health Care L L C", "1 AMAZING HOME HEALTH CARE L L C"),
    ("", None),
    (None, None),
    ("   ", None),
])
def test_to_db_text(raw, expected):
    assert to_db_text(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Union County", "UNION"),
    ("El Dorado County", "EL DORADO"),
    ("Maricopa", "MARICOPA"),                      # ATT/ESS has no suffix already
    ("Prince George'S County", "PRINCE GEORGES"),  # live LN: PRINCE GEORGES
    ("St. Lucie County", "SAINT LUCIE"),           # live LN: SAINT LUCIE
    ("St. Tammany", "SAINT TAMMANY"),              # live LN: SAINT TAMMANY
    ("Orleans Parish", "ORLEANS"),                 # live LN: ORLEANS
    ("Anchorage Borough", "ANCHORAGE"),
    ("Baltimore City", "BALTIMORE CITY"),          # independent city: keep CITY
    ("Miami-Dade County", "MIAMI-DADE"),
    ("Stafford", "STAFFORD"),                      # starts with ST but isn't 'St '
    ("", None),
    (None, None),
])
def test_to_db_county(raw, expected):
    assert to_db_county(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("85308-4212", "85308"),
    ("07036-7212", "07036"),
    ("62704", "62704"),
    ("8701", "08701"),           # Excel dropped the leading zero
    ("501", "00501"),
    ("853084212", "85308"),      # ZIP+4 without a dash
    ("87015355", "08701"),       # ZIP+4, leading zero dropped
    ("12", None),
    ("", None),
    (None, None),
])
def test_to_db_zip(raw, expected):
    assert to_db_zip(raw) == expected
