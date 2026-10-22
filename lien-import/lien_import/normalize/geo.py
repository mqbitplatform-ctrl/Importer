"""US state lookup + jurisdiction / plaintiff resolution."""

from __future__ import annotations

import re
from typing import Optional

# 50 states + DC. Territories intentionally excluded until confirmed present
# in the real archives (discovery output will flag any unmapped values).
_NAME_TO_ABBR = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}
ABBR_TO_NAME = {v: k for k, v in _NAME_TO_ABBR.items()}
VALID_ABBR = frozenset(_NAME_TO_ABBR.values())

_STATE_OF_RE = re.compile(r"state\s+of\s+(.+)", re.IGNORECASE)
# "Filing Office:UNION COUNTY COURT, NJ"  -> NJ  (last 2-letter token on the line)
_OFFICE_STATE_RE = re.compile(r",\s*([A-Za-z]{2})\s*$")


def normalize_state(value: Optional[str]) -> Optional[str]:
    """Return a valid 2-letter abbreviation, or None."""
    if not value:
        return None
    v = value.strip().upper()
    if len(v) == 2 and v in VALID_ABBR:
        return v
    if v in _NAME_TO_ABBR:
        return _NAME_TO_ABBR[v]
    return None


def state_from_creditor(creditor: Optional[str]) -> Optional[str]:
    """'State Of California' -> 'CA'."""
    if not creditor:
        return None
    m = _STATE_OF_RE.search(creditor.strip())
    if not m:
        return None
    return normalize_state(m.group(1).strip())


def state_from_note_office(note: Optional[str]) -> Optional[str]:
    """First 'Filing Office:... , XX' state found in a TNU Combined Note blob."""
    if not note:
        return None
    for line in note.splitlines():
        line = line.strip()
        if "filing office" not in line.lower():
            continue
        m = _OFFICE_STATE_RE.search(line)
        if m:
            abbr = normalize_state(m.group(1))
            if abbr:
                return abbr
    return None


def resolve_jurisdiction(
    filing_type: str,
    *,
    creditor: Optional[str],
    note: Optional[str],
    address_state: Optional[str],
) -> tuple[Optional[str], str]:
    """Return ``(abbr_or_None, source_used)``.

    State liens  -> creditor ("State Of X") > Note filing office > address state
    Federal liens -> address (filing location) > Note filing office
    """
    if filing_type == "S":
        by_cred = state_from_creditor(creditor)
        if by_cred:
            return by_cred, "creditor"
        by_note = state_from_note_office(note)
        if by_note:
            return by_note, "note_filing_office"
        by_addr = normalize_state(address_state)
        if by_addr:
            return by_addr, "address_state"
        return None, "none"

    # Federal
    by_addr = normalize_state(address_state)
    if by_addr:
        return by_addr, "address_state"
    by_note = state_from_note_office(note)
    if by_note:
        return by_note, "note_filing_office"
    return None, "none"


def derive_plaintiff(filing_type: str, jurisdiction: Optional[str]) -> Optional[str]:
    """Match existing DB convention:
    Federal -> 'INTERNAL REVENUE SERVICE'
    State   -> 'STATE OF <FULL NAME>'
    """
    if filing_type == "F":
        return "INTERNAL REVENUE SERVICE"
    if filing_type == "S" and jurisdiction:
        name = ABBR_TO_NAME.get(jurisdiction)
        if name:
            return f"STATE OF {name}"[:50]
    return None
