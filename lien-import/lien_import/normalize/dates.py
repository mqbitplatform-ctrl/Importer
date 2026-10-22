"""Date parsing with an explicit format list (no fuzzy parsing).

Formats seen across sources:
    "9/23/19"                    m/d/yy   (ATT/ESS, 2-digit year)
    "8/9/2021"                   m/d/yyyy (TNU Starter)
    "12/14/2021 12:00:00 AM"     m/d/yyyy h:mm:ss AM/PM (TNU Combined)
    "2021-12-14"                 ISO (defensive)

Returns a datetime.date or None.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%m-%d-%y",
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",  # ATT/ESS 60243-425..429: '2023-10-11 00:00:00'
    "%Y-%m-%d %H:%M",
)

# Within one source file the dates almost always share a single format; try the
# last one that worked first, so we don't pay 4+ failing strptime calls per row.
_last_fmt: list[str] = [_FORMATS[3]]


def parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    ordered = (_last_fmt[0], *(f for f in _FORMATS if f != _last_fmt[0]))
    for fmt in ordered:
        try:
            d = datetime.strptime(s, fmt).date()
            if fmt != _last_fmt[0]:
                _last_fmt[0] = fmt
            return d
        except ValueError:
            continue
    return None


def is_reasonable(d: Optional[date], min_year: int = 1980, max_ahead_days: int = 2) -> bool:
    """True if *d* is a plausible lien filing date.

    Rejects dates before *min_year* and dates in the future (allowing a small
    slack for timezone / clock skew).
    """
    if d is None:
        return False
    if d.year < min_year:
        return False
    today = date.today()
    if (d - today).days > max_ahead_days:
        return False
    return True
