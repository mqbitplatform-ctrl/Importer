"""ATT/ESS format  ->  lien_source = 'ES'.

Header signature (canonical):
    listid, pin, filing, full name, address, city, state, zip code, county,
    filing date, amount, type, creditor 1, phone number, respond by

Notes:
  * Person/business name arrives as a single "Full Name" field.
  * "Type" gives Federal/State explicitly; "Filing #" prefix (19F- / 19S-)
    is a secondary signal.
  * PIN / Filing # are captured as source_ref for traceability only - never
    used as lien_id (handoff section 8).

Real archive (106 files, 2024-05..2025-07) has ~55 header layouts. Column
aliases seen there - the same ones Get-CsvStats.ps1 already handled:
  name      : "Full Name" | "Name" | "First Name" (holds the FULL name)
  creditor  : "Creditor 1" | "English Creditor"
  zip       : "Zip Code" | "Zip"
  filing #  : "Filing #" | "Lien Reference Number" (some files leave it unnamed)
  PIN/ListID: absent from the 2025-05+ files (542-551)
"""

from __future__ import annotations

import re
from typing import Iterable

from ..models import MappedRow
from ..normalize.text import canon_header, clean
from .base import SourceAdapter

_FILING_PREFIX_RE = re.compile(r"^\d{2}\s*([FS])\b", re.IGNORECASE)

_NAME_COLS = ("full name", "name", "first name")
_CREDITOR_COLS = ("creditor 1", "english creditor")
_ZIP_COLS = ("zip code", "zip")
_FILING_NO_COLS = ("filing", "lien reference number")


def _first(canon: dict, keys) -> str:
    for k in keys:
        v = canon.get(k)
        if v is not None and str(v).strip():
            return v
    return ""


class AttEssAdapter(SourceAdapter):
    source_code = "ES"
    format_name = "att_ess"
    required_headers = frozenset({"type", "filing date", "amount", "address"})
    # TNU layouts carry these; ATT/ESS never does
    forbidden_headers = frozenset({"index", "case", "note", "company", "business name", "last name"})

    @classmethod
    def matches(cls, canon_headers: Iterable[str]) -> bool:
        hs = {canon_header(h) for h in canon_headers}
        return (
            cls.required_headers.issubset(hs)
            and not (cls.forbidden_headers & hs)
            and any(c in hs for c in _NAME_COLS)
            and any(c in hs for c in _CREDITOR_COLS)
        )

    def map_row(self, canon, file, row_num, raw):
        type_col = (canon.get("type") or "").strip().lower()
        hint = None
        if "federal" in type_col:
            hint = "F"
        elif "state" in type_col:
            hint = "S"

        filing_no = str(_first(canon, _FILING_NO_COLS)).strip()
        if hint is None and filing_no:
            m = _FILING_PREFIX_RE.match(filing_no)
            if m:
                hint = m.group(1).upper()

        creditor = clean(_first(canon, _CREDITOR_COLS))
        if hint is None and creditor:  # last resort: 'State Of X' / 'Internal Revenue Service'
            c = creditor.lower()
            if c.startswith("federal") or "internal revenue" in c:
                hint = "F"
            elif c.startswith("state of") or c.startswith("state "):
                hint = "S"

        return MappedRow(
            source_code=self.source_code,
            source_format=self.format_name,
            source_file=file,
            source_row_num=row_num,
            raw=raw,
            company=None,
            full_name=clean(_first(canon, _NAME_COLS)),
            address=clean(canon.get("address")),
            city=clean(canon.get("city")),
            state=clean(canon.get("state")),
            zip=clean(_first(canon, _ZIP_COLS)),
            filing_county=clean(canon.get("county")),
            filing_date_raw=canon.get("filing date"),
            amount_raw=canon.get("amount"),
            filing_type_hint=hint,
            creditor=creditor,
            note=None,
            source_ref=clean(canon.get("pin")) or filing_no or None,
        )
