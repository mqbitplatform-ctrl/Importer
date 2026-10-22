"""TNU Starter format  ->  lien_source = 'TN'.

Header signature (canonical):
    index, first name, middle name, last name, address, city, state, zip,
    filing county, filing date, year, amount owed, creditor, case, source,
    business name, cell, home, date

Notes:
  * Separate person-name and "Business Name" fields.
  * Federal/State from "Creditor" ("Federal Taxing Authorities" /
    "Internal Revenue Service" / "State ..."); "Source" tag (e.g. "FedTR13")
    is a fallback.
  * index / Case # / Source are source_ref only - never lien_id.
  * Shares lien_source 'TN' with TNU Combined; the natural-key fingerprint is
    identical across both formats so the same lien in both files de-duplicates
    (handoff section 9).
"""

from __future__ import annotations

from ..models import MappedRow
from ..normalize.names import is_placeholder
from ..normalize.text import clean
from .base import SourceAdapter


def _real(value):
    v = clean(value)
    return None if is_placeholder(v) else v


class TnuStarterAdapter(SourceAdapter):
    source_code = "TN"
    format_name = "tnu_starter"
    required_headers = frozenset(
        {"index", "case", "source", "amount owed", "first name", "last name"}
    )
    forbidden_headers = frozenset({"note", "company"})

    def map_row(self, canon, file, row_num, raw):
        creditor = clean(canon.get("creditor"))
        hint = self._filing_type(creditor, canon.get("source"))

        case_no = (canon.get("case") or "").strip()
        src_tag = (canon.get("source") or "").strip()
        source_ref = "/".join(p for p in (case_no, src_tag) if p) or None

        # fillers ('NA', 'N/A', 'Doe', ...) mean "no value" - see names.is_placeholder
        company = _real(canon.get("business name"))
        first = _real(canon.get("first name"))
        middle = _real(canon.get("middle name"))
        raw_last = clean(canon.get("last name"))
        last = None if is_placeholder(raw_last, last_name=True) else raw_last

        return MappedRow(
            source_code=self.source_code,
            source_format=self.format_name,
            source_file=file,
            source_row_num=row_num,
            raw=raw,
            company=company,
            first_name=first,
            middle=middle,
            last_name=last,
            last_name_was_placeholder=bool(raw_last) and last is None,
            full_name=None,
            address=clean(canon.get("address")),
            city=clean(canon.get("city")),
            state=clean(canon.get("state")),
            zip=clean(canon.get("zip")),
            filing_county=clean(canon.get("filing county")),
            filing_date_raw=canon.get("filing date"),
            amount_raw=canon.get("amount owed"),
            filing_type_hint=hint,
            creditor=creditor,
            note=None,
            source_ref=source_ref,
        )

    @staticmethod
    def _filing_type(creditor, source_tag):
        c = (creditor or "").lower()
        if "federal" in c or "internal revenue" in c:
            return "F"
        if "state" in c:
            return "S"
        s = (source_tag or "").lower()
        if s.startswith("fed"):
            return "F"
        if s.startswith("st"):
            return "S"
        return None
