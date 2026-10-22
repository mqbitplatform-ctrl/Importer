"""Data-quality rules added after previewing the REAL archives (Oct 2026):
placeholder names, Real Estate / entity-suffix heuristic, ISO datetime dates,
ATT/ESS filing type from the creditor."""

from __future__ import annotations

from datetime import date

import pytest

from lien_import.adapters import AttEssAdapter, TnuCombinedAdapter, TnuStarterAdapter
from lien_import.models import Disposition
from lien_import.normalize.dates import parse_date
from lien_import.normalize.names import is_placeholder, name_kind, strong_business
from lien_import.normalize.text import canon_row
from lien_import.recordbuilder import build_record

RUN_DATE = date(2026, 10, 22)

_STARTER_HEADER = [
    "Index", "First Name", "Middle Name", "Last Name", "Address", "City", "State", "Zip",
    "Filing County", "Filing Date", "Year", "Amount Owed", "Creditor", "Case #", "Source",
    "Business Name", "Cell", "Home", "Date",
]


def _starter(first, middle, last, business=""):
    values = [
        "1", first, middle, last, "12 Main St", "Austin", "TX", "78701", "Travis",
        "8/9/2021", "2021", "$7,500.00", "Internal Revenue Service", "C-1", "FedTR13",
        business, "", "", "",
    ]
    raw = dict(zip(_STARTER_HEADER, values))
    m = TnuStarterAdapter().map_row(canon_row(raw), "starter.csv", 1, raw)
    return m, build_record(m, run_date=RUN_DATE)


# ------------------------------------------------------------- name heuristics

@pytest.mark.parametrize("name,kind", [
    ("Pac West Real Estate Corp", "Business"),        # 'Real Estate' is not an estate
    ("Sunrise Real Estate", "Business"),
    ("Southwest Investment Trust Lp", "Business"),    # entity suffix beats 'Trust'
    ("Guardina Estate Planning Inc", "Business"),
    ("John Smith Revocable Trust", "TrustEstate"),    # unchanged
    ("Estate Of Jane Doe", "TrustEstate"),
])
def test_name_kind_real_archive_changes(name, kind):
    assert name_kind(name) == kind


@pytest.mark.parametrize("name,expected", [
    ("Jason", False),            # single word: weak fallback only, not evidence
    ("Arts Dance Project", False),
    ("Acme Llc", True),
    ("Joes Auto Repair", True),
    ("007 Handy Man", True),
    ("Bob Dba Bobs Tacos", True),
    ("", False),
    (None, False),
])
def test_strong_business(name, expected):
    assert strong_business(name) is expected


@pytest.mark.parametrize("value,last_name,expected", [
    ("NA", False, True), ("n/a", False, True), ("N.A.", False, True), ("nan", False, True),
    ("Doe", True, True),          # 'John Doe' filler - only as the whole last name
    ("Doe", False, False),        # a first name 'Doe' is left alone
    ("Doerr", True, False),
    ("Nash", True, False),
    ("", True, False), (None, True, False),
])
def test_is_placeholder(value, last_name, expected):
    assert is_placeholder(value, last_name=last_name) is expected


# ------------------------------------------------- TNU Starter placeholder rows

def test_real_last_name_is_unchanged():
    m, res = _starter("Jason", "R", "Smith")
    assert not m.last_name_was_placeholder
    r = res.record
    assert (r.lien_entity_type, r.lien_first_name, r.lien_middle_initial, r.lien_last_name) == \
        ("I", "JASON", "R", "SMITH")


@pytest.mark.parametrize("last", ["NA", "N/A", "Doe", "doe"])
def test_first_name_plus_middle_with_placeholder_last_is_individual(last):
    m, res = _starter("Christopher", "C", last)
    assert m.last_name is None and m.last_name_was_placeholder
    assert res.disposition == Disposition.INSERT, res.reasons
    r = res.record
    assert (r.lien_entity_type, r.lien_first_name, r.lien_middle_initial, r.lien_last_name) == \
        ("I", "CHRISTOPHER", "C", None)
    assert any("placeholder" in n for n in res.classification.notes)


@pytest.mark.parametrize("first", [
    "Glass Doctor", "Freeway Building Materials", "Arts Dance Project", "Doordash",
])
def test_no_middle_with_placeholder_last_is_a_business_row(first):
    # real TNU Starter convention: business name in First Name, filler last name
    _, res = _starter(first, "", "NA")
    assert res.disposition == Disposition.INSERT, res.reasons
    r = res.record
    assert r.lien_entity_type == "B" and r.lien_business_name == first.upper()
    assert r.lien_first_name is None and r.lien_last_name is None


def test_joint_name_with_placeholder_last_is_held():
    _, res = _starter("Robert & Suzy", "", "NA")
    assert res.disposition == Disposition.HOLD_AMBIGUOUS


def test_placeholder_middle_is_blanked():
    m, res = _starter("Maria", "N/A", "Lopez")
    assert m.middle is None
    r = res.record
    assert (r.lien_first_name, r.lien_middle_initial, r.lien_last_name) == ("MARIA", None, "LOPEZ")


def test_business_wording_with_placeholder_last_is_business():
    _, res = _starter("Acme Roofing Llc", "", "NA")
    r = res.record
    assert r.lien_entity_type == "B" and r.lien_business_name == "ACME ROOFING LLC"


def test_trust_with_placeholder_last_is_held():
    _, res = _starter("Smith Family Trust", "", "NA")
    assert res.disposition == Disposition.HOLD_TRUST_ESTATE


def test_business_name_column_wins_over_placeholder_person():
    _, res = _starter("NA", "NA", "NA", business="Big Dawgz Burgers Inc")
    r = res.record
    assert r.lien_entity_type == "B" and r.lien_business_name == "BIG DAWGZ BURGERS INC"


# ----------------------------------------------------- TNU Combined placeholders

def test_tnu_combined_blanks_nan_fillers():
    header = ["Company", "First Name", "Last Name", "Middle Initial", "Full Name", "Address",
              "City", "State", "Zip", "Filling County", "Filling Date", "Amount", "Creditor", "Note"]
    values = ["nan", "Donna", "Murphy", "null", "", "12 Main St", "Nashville", "TN", "37201",
              "Davidson", "12/14/2021 12:00:00 AM", "$9,000.00", "State Of Tennessee", ""]
    raw = dict(zip(header, values))
    m = TnuCombinedAdapter().map_row(canon_row(raw), "c.csv", 1, raw)
    assert m.company is None and m.middle is None
    r = build_record(m, run_date=RUN_DATE).record
    assert (r.lien_entity_type, r.lien_first_name, r.lien_last_name) == ("I", "DONNA", "MURPHY")


# ------------------------------------------------------------------- dates

@pytest.mark.parametrize("raw,expected", [
    ("2023-10-11 00:00:00", date(2023, 10, 11)),   # ATT/ESS 60243-425..429
    ("2023-10-11 00:00", date(2023, 10, 11)),
])
def test_iso_datetime_dates(raw, expected):
    assert parse_date(raw) == expected


# ------------------------------------------- ATT/ESS filing type from creditor

_ESS_HEADER = ["Filing #", "Full Name", "Address", "City", "State", "Zip Code", "County",
               "Filing Date", "Amount", "Type", "English Creditor"]


@pytest.mark.parametrize("creditor,expected", [
    ("State Of Arizona", "S"),
    ("Internal Revenue Service", "F"),
    ("Federal Tax Authorities", "F"),
    ("Chris Baker", None),           # not a taxing authority - stays unresolved
])
def test_att_ess_filing_type_falls_back_to_creditor(creditor, expected):
    values = ["X-1", "Jeffrey M Trexler", "3801 W Campo Bello Dr", "Glendale", "AZ", "85308",
              "Maricopa", "9/23/19", "$12,387.00", "", creditor]
    raw = dict(zip(_ESS_HEADER, values))
    m = AttEssAdapter().map_row(canon_row(raw), "f.csv", 1, raw)
    assert m.filing_type_hint == expected


def test_att_ess_type_column_still_wins_over_creditor():
    values = ["X-1", "Jeffrey M Trexler", "3801 W Campo Bello Dr", "Glendale", "AZ", "85308",
              "Maricopa", "9/23/19", "$12,387.00", "Federal", "State Of Arizona"]
    raw = dict(zip(_ESS_HEADER, values))
    m = AttEssAdapter().map_row(canon_row(raw), "f.csv", 1, raw)
    assert m.filing_type_hint == "F"
