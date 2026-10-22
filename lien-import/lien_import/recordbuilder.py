"""Turn a :class:`MappedRow` into a validated :class:`LienRecord`
(or a non-INSERT disposition with reasons).

Disposition priority is defined in :data:`models.DISPOSITION_PRIORITY`.
``lien_id`` is left blank here - the pipeline fills it once it can perform
collision lookups against the run + DB / import-log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .idgen import build_natural_key
from .models import DISPOSITION_PRIORITY, Disposition, LienRecord, MappedRow
from .normalize.dates import is_reasonable, parse_date
from .normalize.geo import derive_plaintiff, normalize_state, resolve_jurisdiction
from .normalize.money import parse_money
from .normalize.names import (
    assemble_name,
    middle_initial_of,
    name_kind,
    split_person_name,
    strong_business,
)
from .normalize.text import to_db_county, to_db_text, to_db_zip, truncate

_MAX_AMOUNT = Decimal("10000000000000")  # decimal(15,2) upper bound


@dataclass
class Classification:
    filing_type: Optional[str] = None
    entity_type: Optional[str] = None
    name_kind: Optional[str] = None
    name_used: Optional[str] = None
    jurisdiction: Optional[str] = None
    jurisdiction_source: str = "none"
    notes: list[str] = field(default_factory=list)


@dataclass
class BuildResult:
    disposition: Disposition
    reasons: list[str] = field(default_factory=list)
    record: Optional[LienRecord] = None
    classification: Classification = field(default_factory=Classification)
    #: field names implicated in a REJECT_MISSING / REJECT_INVALID (for the
    #: data-quality tally), e.g. ["lien_amount", "lien_jurisdiction"]
    problem_fields: list[str] = field(default_factory=list)


@dataclass
class _Entity:
    entity_type: Optional[str]  # 'B' | 'I' | None
    kind: str  # Business | Individual | TrustEstate | Ambiguous | Missing
    name_used: Optional[str]
    business_name: Optional[str] = None
    first: Optional[str] = None
    middle_initial: Optional[str] = None
    last: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _resolve_entity(m: MappedRow) -> _Entity:
    company = (m.company or "").strip() or None
    if m.full_name and m.full_name.strip():
        person = m.full_name.strip()
    else:
        person = assemble_name(m.first_name, m.middle, m.last_name)
    has_person = bool(person and person.strip())
    has_company = company is not None

    if has_company and not has_person:
        return _Entity("B", "Business", company, business_name=company)

    if has_company and has_person:
        return _Entity(
            "B", "Business", company, business_name=company,
            notes=["both company and person name populated - treated as Business"],
        )

    if has_person and m.last_name_was_placeholder and not m.full_name:
        return _resolve_placeholder_last(m, person)

    if has_person:
        kind = name_kind(person)
        if kind == "Business":
            return _Entity("B", "Business", person, business_name=person)
        if kind == "Individual":
            if m.full_name and not (m.first_name or m.last_name):
                f, mi, l = split_person_name(person)
                notes = ["person name split from single Full Name field"]
            else:
                f = (m.first_name or "").strip() or None
                mi = middle_initial_of(m.middle)
                l = (m.last_name or "").strip() or None
                notes = []
                if not l and m.middle:
                    l, mi = m.middle.strip() or None, None
                    notes.append("last name empty - promoted middle name to last name")
            return _Entity("I", "Individual", person, first=f, middle_initial=mi, last=l, notes=notes)
        # TrustEstate | Ambiguous
        return _Entity(None, kind, person)

    return _Entity(None, "Missing", None)


_PLACEHOLDER_NOTE = "last name was a placeholder ('NA'/'N/A'/'Doe') - left blank"


def _resolve_placeholder_last(m: MappedRow, person: str) -> _Entity:
    """The source's last name was only a filler and has been blanked.

    Profiled on the real TNU Starter file (~82,500 such rows): with NO middle
    name, the First Name column holds a business name ('Glass Doctor',
    'Freeway Building Materials', 'Doordash' - ~95% of a random sample);
    the people are the rows that DO carry a middle initial ('Christopher C').
    name_kind alone calls most 2-4 word business names Individual, so:
      * positive business evidence (LLC, INC, digits, DBA, ...) -> Business
      * trust / estate wording, or joint names ('&', '/')       -> hold
      * one given name + a middle name                          -> Individual,
        last name left blank
      * otherwise (no middle name)                              -> Business
    """
    if strong_business(person):
        return _Entity("B", "Business", person, business_name=person, notes=[_PLACEHOLDER_NOTE])
    kind = name_kind(person)
    if kind in ("TrustEstate", "Ambiguous"):
        return _Entity(None, kind, person, notes=[_PLACEHOLDER_NOTE])
    first = (m.first_name or "").strip()
    middle = (m.middle or "").strip()
    if middle and first and " " not in first:
        return _Entity(
            "I", "Individual", person,
            first=first, middle_initial=middle_initial_of(middle), last=None,
            notes=[_PLACEHOLDER_NOTE],
        )
    return _Entity(
        "B", "Business", person, business_name=person,
        notes=[_PLACEHOLDER_NOTE + "; no middle name - TNU Starter business row"],
    )


def build_record(
    m: MappedRow, *, run_date: date, min_filing_year: int = 1980
) -> BuildResult:
    problems: list[tuple[Disposition, str, str]] = []  # (disposition, field, reason)
    cls = Classification()

    # --- filing type -------------------------------------------------------
    ft = m.filing_type_hint if m.filing_type_hint in ("F", "S") else None
    cls.filing_type = ft
    if ft is None:
        problems.append(
            (Disposition.REJECT_MISSING, "lien_filing_type",
             "lien_filing_type: cannot determine Federal vs State")
        )

    # --- entity type -----------------------------------------------------
    ent = _resolve_entity(m)
    cls.entity_type = ent.entity_type
    cls.name_kind = ent.kind
    cls.name_used = ent.name_used
    cls.notes.extend(ent.notes)
    if ent.kind == "TrustEstate":
        problems.append(
            (Disposition.HOLD_TRUST_ESTATE, "lien_entity_type",
             f"entity name {ent.name_used!r} classified Trust/Estate")
        )
    elif ent.kind == "Ambiguous":
        problems.append(
            (Disposition.HOLD_AMBIGUOUS, "lien_entity_type",
             f"entity name {ent.name_used!r} classified Ambiguous")
        )
    elif ent.entity_type is None:
        problems.append(
            (Disposition.REJECT_MISSING, "lien_entity_type",
             "lien_entity_type: no usable business or person name")
        )

    # --- amount --------------------------------------------------------
    amt = parse_money(m.amount_raw)
    if amt is None:
        problems.append(
            (Disposition.REJECT_MISSING, "lien_amount", f"lien_amount: unparseable {m.amount_raw!r}")
        )
    elif amt <= 0:
        problems.append(
            (Disposition.REJECT_INVALID, "lien_amount", f"lien_amount: non-positive ({amt})")
        )
    elif amt >= _MAX_AMOUNT:
        problems.append(
            (Disposition.REJECT_INVALID, "lien_amount", f"lien_amount: exceeds decimal(15,2) ({amt})")
        )

    # --- filing date -------------------------------------------------
    fdate = parse_date(m.filing_date_raw)
    if fdate is None:
        problems.append(
            (Disposition.REJECT_MISSING, "lien_filing_date",
             f"lien_filing_date: unparseable {m.filing_date_raw!r}")
        )
    elif not is_reasonable(fdate, min_filing_year):
        problems.append(
            (Disposition.REJECT_INVALID, "lien_filing_date",
             f"lien_filing_date: out of range ({fdate.isoformat()})")
        )

    # --- jurisdiction ----------------------------------------------
    juris = None
    if ft in ("F", "S"):
        juris, juris_src = resolve_jurisdiction(
            ft, creditor=m.creditor, note=m.note, address_state=m.state
        )
        cls.jurisdiction = juris
        cls.jurisdiction_source = juris_src
        if juris is None:
            problems.append(
                (Disposition.REJECT_MISSING, "lien_jurisdiction",
                 "lien_jurisdiction: cannot determine 2-letter state")
            )

    if problems:
        primary = min(problems, key=lambda pr: DISPOSITION_PRIORITY[pr[0]])[0]
        return BuildResult(
            disposition=primary,
            reasons=[r for _, _, r in problems],
            record=None,
            classification=cls,
            problem_fields=sorted({f for d, f, _ in problems
                                   if d in (Disposition.REJECT_MISSING, Disposition.REJECT_INVALID)}),
        )

    # --- assemble record (all required values present) ---------------
    assert ft is not None and amt is not None and fdate is not None and juris is not None
    # Stored values use the existing liens formatting (to_db_*); the natural key
    # below is still built from the raw source values, so lien_ids are unchanged.
    if ent.entity_type == "B":
        b_name = truncate(to_db_text(ent.business_name), 200)
        first = mi = last = None
        entity_name_for_key = ent.business_name or ""
    else:
        b_name = None
        first = truncate(to_db_text(ent.first), 60)
        mi = (to_db_text(ent.middle_initial) or "")[:1] or None
        last = truncate(to_db_text(ent.last), 60)
        entity_name_for_key = assemble_name(ent.first, ent.middle_initial, ent.last) or ent.name_used or ""

    natural_key = build_natural_key(
        entity_name=entity_name_for_key,
        address=m.address,
        zip_code=m.zip,
        filing_type=ft,
        filing_date_iso=fdate.isoformat(),
        amount=f"{amt:.2f}",
    )

    record = LienRecord(
        lien_source=m.source_code,
        lien_id="",
        lien_filing_type=ft,
        lien_jurisdiction=juris,
        lien_entity_type=ent.entity_type,
        lien_amount=amt,
        lien_filing_date=fdate,
        lien_load_date=run_date,
        lien_release_date=None,
        lien_business_name=b_name,
        lien_first_name=first,
        lien_middle_initial=mi,
        lien_last_name=last,
        lien_address=truncate(to_db_text(m.address), 255),
        lien_city=truncate(to_db_text(m.city), 100),
        lien_state=normalize_state(m.state) or truncate(to_db_text(m.state), 2),
        lien_zip=to_db_zip(m.zip),
        lien_plaintiff=truncate(derive_plaintiff(ft, juris), 50),
        lien_filing_county=truncate(to_db_county(m.filing_county), 100),
        natural_key=natural_key,
    )
    return BuildResult(
        disposition=Disposition.INSERT, reasons=[], record=record, classification=cls
    )
