"""TNU Combined format (Combined-Federal / Combined-State)  ->  lien_source = 'TN'.

Header signature (canonical, "Filling" typo normalised to "filing"):
    company, first name, last name, middle initial, full name, address, city,
    state, zip, filing county, filing date, amount, creditor, note

Notes:
  * Business rows carry the name in "Company" with the person fields blank;
    individual rows carry first/last (Combined-Federal samples show first name
    abbreviated to an initial - kept as-is, that is the source data).
  * Federal vs State: "Creditor" ("Federal Taxing Authorities" / "State Of X")
    is primary; "Note" ("FEDERAL TAX LIEN" / "STATE TAX LIEN") and the file
    name are fallbacks.
  * "Note" is a multi-line blob holding Filing Number / Certificate Number /
    Filing Office - captured for traceability + jurisdiction fallback.
"""

from __future__ import annotations

import re

from ..models import MappedRow
from ..normalize.names import is_placeholder
from ..normalize.text import clean
from .base import SourceAdapter

_FILING_NUMBER_RE = re.compile(r"filing\s*number\s*:\s*(\S+)", re.IGNORECASE)


def _real(value):
    """Blank fillers such as 'nan' / 'null' (16 rows in the real archive)."""
    v = clean(value)
    return None if is_placeholder(v) else v


class TnuCombinedAdapter(SourceAdapter):
    source_code = "TN"
    format_name = "tnu_combined"
    required_headers = frozenset(
        {"company", "note", "creditor", "amount", "filing date"}
    )
    forbidden_headers = frozenset({"index", "case", "source"})

    def map_row(self, canon, file, row_num, raw):
        creditor = clean(canon.get("creditor"))
        note = canon.get("note") or None
        hint = self._filing_type(creditor, note, file)

        source_ref = None
        if note:
            m = _FILING_NUMBER_RE.search(note)
            if m:
                source_ref = m.group(1)

        return MappedRow(
            source_code=self.source_code,
            source_format=self.format_name,
            source_file=file,
            source_row_num=row_num,
            raw=raw,
            company=_real(canon.get("company")),
            first_name=_real(canon.get("first name")),
            middle=_real(canon.get("middle initial")),
            last_name=_real(canon.get("last name")),
            full_name=_real(canon.get("full name")),
            address=clean(canon.get("address")),
            city=clean(canon.get("city")),
            state=clean(canon.get("state")),
            zip=clean(canon.get("zip")),
            filing_county=clean(canon.get("filing county")),
            filing_date_raw=canon.get("filing date"),
            amount_raw=canon.get("amount"),
            filing_type_hint=hint,
            creditor=creditor,
            note=note,
            source_ref=source_ref,
        )

    @staticmethod
    def _filing_type(creditor, note, file):
        c = (creditor or "").lower()
        if c.startswith("federal") or "internal revenue" in c:
            return "F"
        if c.startswith("state of") or c.startswith("state "):
            return "S"
        n = (note or "").upper()
        if "FEDERAL TAX LIEN" in n:
            return "F"
        if "STATE TAX LIEN" in n:
            return "S"
        f = (file or "").lower()
        if "federal" in f:
            return "F"
        if "state" in f:
            return "S"
        return None
