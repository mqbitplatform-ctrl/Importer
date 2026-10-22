"""Money parsing.

Accepts the formats seen across sources:
    "$12,387.00"   (ATT/ESS)
    "12293"        (TNU Combined)
    "102,372"      (TNU Starter)
    "(1,234.56)"   parenthesised negative (rejected downstream, but parsed)

Returns a Decimal quantised to 2 dp, or None if the value cannot be parsed.
Port of Parse-MoneyToDecimal from Get-CsvStats.ps1.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional

_STRIP = re.compile(r"[^\d.\-]")
_CENTS = Decimal("0.01")


def parse_money(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]

    s = _STRIP.sub("", s)
    if not s or s in {"-", ".", "-."}:
        return None

    # Guard against multiple dots / stray minus after stripping
    if s.count(".") > 1 or s.count("-") > 1 or ("-" in s and not s.startswith("-")):
        return None

    try:
        d = Decimal(s)
    except InvalidOperation:
        return None

    if negative:
        d = -d
    return d.quantize(_CENTS, rounding=ROUND_HALF_UP)
