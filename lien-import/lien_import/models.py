"""Core data structures shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class Disposition(str, Enum):
    """Exactly one is assigned to every examined source row.

    Priority order (highest first) when a row hits more than one problem:
    REJECT_MISSING > REJECT_INVALID > HOLD_TRUST_ESTATE > HOLD_AMBIGUOUS
    > SKIP_DUPLICATE > INSERT
    """

    INSERT = "INSERT"
    SKIP_DUPLICATE = "SKIP_DUPLICATE"
    HOLD_TRUST_ESTATE = "HOLD_TRUST_ESTATE"
    HOLD_AMBIGUOUS = "HOLD_AMBIGUOUS"
    REJECT_MISSING = "REJECT_MISSING"
    REJECT_INVALID = "REJECT_INVALID"


DISPOSITION_PRIORITY = {
    Disposition.REJECT_MISSING: 0,
    Disposition.REJECT_INVALID: 1,
    Disposition.HOLD_TRUST_ESTATE: 2,
    Disposition.HOLD_AMBIGUOUS: 3,
    Disposition.SKIP_DUPLICATE: 4,
    Disposition.INSERT: 5,
}


@dataclass
class MappedRow:
    """Raw values pulled out of one source CSV row by a format adapter,
    before normalisation / validation."""

    source_code: str  # 'ES' | 'TN'
    source_format: str  # 'att_ess' | 'tnu_combined' | 'tnu_starter'
    source_file: str
    source_row_num: int
    raw: dict[str, str] = field(default_factory=dict)

    company: Optional[str] = None
    first_name: Optional[str] = None
    middle: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None

    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    filing_county: Optional[str] = None

    filing_date_raw: Optional[str] = None
    amount_raw: Optional[str] = None
    filing_type_hint: Optional[str] = None  # 'F' | 'S' | None
    creditor: Optional[str] = None
    note: Optional[str] = None

    source_ref: Optional[str] = None  # PIN / Case# / Filing Number - traceability only
    # set by an adapter when the source's last name was only a filler ('NA',
    # 'N/A', 'Doe') and was blanked - the remaining name needs careful B/I rules
    last_name_was_placeholder: bool = False


@dataclass
class LienRecord:
    """A normalised row ready to insert into ``liens``."""

    lien_source: str
    lien_id: str
    lien_filing_type: str  # 'S' | 'F'
    lien_jurisdiction: str  # 2-letter state
    lien_entity_type: str  # 'B' | 'I'
    lien_amount: Decimal
    lien_filing_date: date
    lien_load_date: date
    lien_release_date: Optional[date] = None  # no source supplies this
    lien_business_name: Optional[str] = None
    lien_first_name: Optional[str] = None
    lien_middle_initial: Optional[str] = None
    lien_last_name: Optional[str] = None
    lien_address: Optional[str] = None
    lien_city: Optional[str] = None
    lien_state: Optional[str] = None
    lien_zip: Optional[str] = None
    lien_plaintiff: Optional[str] = None
    lien_filing_county: Optional[str] = None

    # not persisted to `liens`; used for the import-log table + audit trail
    natural_key: str = ""
    natural_key_sha1: str = ""


COLUMN_ORDER = [
    "lien_source",
    "lien_id",
    "lien_filing_type",
    "lien_jurisdiction",
    "lien_entity_type",
    "lien_amount",
    "lien_filing_date",
    "lien_release_date",
    "lien_load_date",
    "lien_business_name",
    "lien_first_name",
    "lien_middle_initial",
    "lien_last_name",
    "lien_address",
    "lien_city",
    "lien_state",
    "lien_zip",
    "lien_plaintiff",
    "lien_filing_county",
]
