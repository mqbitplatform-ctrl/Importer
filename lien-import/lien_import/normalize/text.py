"""Small text helpers: header canonicalisation, whitespace, truncation.

``canon_header`` and the per-header-tuple key list are memoised - on a large
import they are otherwise recomputed for every column of every row.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Optional

_WS = re.compile(r"\s+")
_HAS_WS_RUN = re.compile(r"\s\s|\t|\n|\r")


# --- output formatting: match the existing rows in zm_dba.liens -------------
# Verified against the live table (1.39M LexisNexis rows): every name, address,
# city, county and business name is upper-case ASCII; ZIPs are always 5
# digits; counties carry no COUNTY/PARISH/BOROUGH suffix and no "." or "'"
# (PRINCE GEORGES, QUEEN ANNES), and "Saint" is spelled out (SAINT LUCIE).
# Handoff section 11 pt 4: "normalize the source values into the existing
# database representation".

_COUNTY_SUFFIX = re.compile(r"\s+(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY)$")
_ST_PREFIX = re.compile(r"^ST\s+")


def to_db_text(value: Optional[str]) -> Optional[str]:
    """Upper-case ASCII with single spaces (accents transliterated: É -> E)."""
    v = collapse_ws(value)
    if v is None:
        return None
    v = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode("ascii")
    v = collapse_ws(v)
    return v.upper() if v else None


def to_db_county(value: Optional[str]) -> Optional[str]:
    v = to_db_text(value)
    if v is None:
        return None
    v = collapse_ws(v.replace(".", " ").replace("'", "")) or ""
    v = _COUNTY_SUFFIX.sub("", v)
    v = _ST_PREFIX.sub("SAINT ", v)
    return v or None


def to_db_zip(value: Optional[str]) -> Optional[str]:
    """5-digit ZIP. '85308-4212' -> '85308'; Excel-stripped '8701' -> '08701'."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 8:  # ZIP+4 with its leading zero lost: '87015355' -> '08701'
        return digits.zfill(9)[:5]
    if len(digits) >= 5:
        return digits[:5]
    if len(digits) in (3, 4):  # leading zeros lost (NJ/MA/CT ZIPs opened in Excel)
        return digits.zfill(5)
    return None


def collapse_ws(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    # fast path: already trimmed, no internal whitespace runs
    if value and value == value.strip() and not _HAS_WS_RUN.search(value):
        return value
    out = _WS.sub(" ", value).strip()
    return out or None


@lru_cache(maxsize=1024)
def canon_header(name: str) -> str:
    """Map a raw CSV header to a stable canonical key.

    Handles the known source quirks:
      * "Filling County" / "Filling Date"  -> "filing ..."  (source typo)
      * "Filing #"                          -> "filing"
      * trailing punctuation, case, spacing
    """
    h = _WS.sub(" ", (name or "").strip()).lower()
    h = h.replace("filling", "filing")
    h = h.replace("#", "").replace(".", "")
    h = _WS.sub(" ", h).strip()
    return h


@lru_cache(maxsize=256)
def _canon_keys(headers: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(canon_header(h) for h in headers)


def canon_row(row: dict[str, str]) -> dict[str, str]:
    """Return a copy of *row* keyed by canonical header names."""
    keys = _canon_keys(tuple(k for k in row.keys() if k is not None))
    return {
        ck: (v if v is not None else "")
        for ck, v in zip(keys, (row[k] for k in row.keys() if k is not None))
    }


def clean(value: Optional[str]) -> Optional[str]:
    """Trim + collapse internal whitespace; empty -> None."""
    return collapse_ws(value)


def truncate(value: Optional[str], length: int) -> Optional[str]:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    return v[:length]


def title_us(value: Optional[str]) -> Optional[str]:
    """Best-effort readable casing for ALL CAPS / all lower source data."""
    v = clean(value)
    if v is None:
        return None
    return v.title()
