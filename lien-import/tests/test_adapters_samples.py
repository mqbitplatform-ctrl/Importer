"""Row-level checks: adapter + recordbuilder against specific known sample rows."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal

import pytest

from lien_import.adapters import AttEssAdapter, TnuCombinedAdapter, TnuStarterAdapter
from lien_import.models import Disposition
from lien_import.normalize.text import canon_row
from lien_import.recordbuilder import build_record

RUN_DATE = date(2026, 8, 28)


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _build(adapter, raw, file="sample.csv", row_num=1):
    mapped = adapter.map_row(canon_row(raw), file, row_num, raw)
    return mapped, build_record(mapped, run_date=RUN_DATE, min_filing_year=1980)


# --------------------------------------------------------------------------- ES

def test_att_ess_individual_federal(att_ess_csv):
    rows = _rows(att_ess_csv)
    mapped, res = _build(AttEssAdapter(), rows[0])  # Jeffrey M Trexler
    assert res.disposition is Disposition.INSERT
    r = res.record
    assert r.lien_source == "ES"
    assert r.lien_filing_type == "F"
    assert r.lien_entity_type == "I"
    # stored in the existing zm_dba.liens format: UPPER CASE, ZIP5, county w/o suffix
    assert (r.lien_first_name, r.lien_middle_initial, r.lien_last_name) == ("JEFFREY", "M", "TREXLER")
    assert r.lien_address == "3801 W CAMPO BELLO DR"
    assert r.lien_city == "GLENDALE"
    assert r.lien_zip == "85308"                 # source had ZIP+4 '85308-4212'
    assert r.lien_filing_county == "MARICOPA"
    assert r.lien_jurisdiction == "AZ"
    assert r.lien_amount == Decimal("12387.00")
    assert r.lien_filing_date == date(2019, 9, 23)
    assert r.lien_load_date == RUN_DATE
    assert r.lien_release_date is None
    assert r.lien_plaintiff == "INTERNAL REVENUE SERVICE"
    assert r.lien_business_name is None


def test_att_ess_business_row(att_ess_csv):
    rows = _rows(att_ess_csv)
    row = next(r for r in rows if r["Full Name"] == "Ccb Shop Company Llc")
    _, res = _build(AttEssAdapter(), row)
    assert res.disposition is Disposition.INSERT
    assert res.record.lien_entity_type == "B"
    assert res.record.lien_business_name == "CCB SHOP COMPANY LLC"
    assert res.record.lien_first_name is None


def test_att_ess_state_lien_jurisdiction_from_creditor(att_ess_csv):
    rows = _rows(att_ess_csv)
    # Jennifer Boehm: address MT, creditor "State Of California" -> juris CA
    row = next(r for r in rows if r["Full Name"] == "Jennifer Boehm")
    _, res = _build(AttEssAdapter(), row)
    assert res.record.lien_filing_type == "S"
    assert res.record.lien_jurisdiction == "CA"
    assert res.record.lien_plaintiff == "STATE OF CALIFORNIA"


# ---------------------------------------------------------------- TN / combined

def test_combined_federal_abbreviated_first_name(combined_federal_csv):
    rows = _rows(combined_federal_csv)
    mapped, res = _build(TnuCombinedAdapter(), rows[0])  # ",A,Acevedo,,A Acevedo,..."
    assert res.disposition is Disposition.INSERT
    r = res.record
    assert r.lien_source == "TN"
    assert r.lien_filing_type == "F"
    assert r.lien_entity_type == "I"
    assert r.lien_first_name == "A"
    assert r.lien_last_name == "ACEVEDO"
    assert r.lien_zip == "07036"                # leading zero kept, +4 dropped
    assert r.lien_filing_county == "UNION"      # 'Union County' -> 'UNION'
    assert r.lien_jurisdiction == "NJ"          # federal -> address state
    assert r.lien_amount == Decimal("12293.00")
    assert r.lien_filing_date == date(2021, 12, 14)
    assert mapped.source_ref == "445612821"      # Filing Number pulled from Note


def test_combined_state_business_jurisdiction_from_creditor(combined_state_csv):
    rows = _rows(combined_state_csv)
    # "1 Hampton Place Associates Llc": address MI, creditor "State Of Alabama"
    row = next(r for r in rows if r["Company"].startswith("1 Hampton Place"))
    _, res = _build(TnuCombinedAdapter(), row)
    r = res.record
    assert r.lien_filing_type == "S"
    assert r.lien_entity_type == "B"
    assert r.lien_business_name.startswith("1 HAMPTON PLACE")
    assert r.lien_jurisdiction == "AL"          # creditor wins over address (MI)
    assert r.lien_plaintiff == "STATE OF ALABAMA"


# ----------------------------------------------------------------- TN / starter

def test_tnu_starter_individual(tnu_starter_csv):
    rows = _rows(tnu_starter_csv)
    _, res = _build(TnuStarterAdapter(), rows[0])  # Kevin Smith
    r = res.record
    assert res.disposition is Disposition.INSERT
    assert r.lien_source == "TN"
    assert r.lien_filing_type == "F"
    assert r.lien_entity_type == "I"
    assert r.lien_first_name == "KEVIN"
    assert r.lien_last_name == "SMITH"
    assert r.lien_filing_county == "EL DORADO"  # 'El Dorado County'
    assert r.lien_amount == Decimal("102372.00")
    assert r.lien_filing_date == date(2021, 8, 9)


def test_tnu_starter_empty_last_name_promotes_middle(tnu_starter_csv):
    rows = _rows(tnu_starter_csv)
    row = next(r for r in rows if r["First Name"] == "Annette")  # First=Annette Middle=Gore Last=""
    _, res = _build(TnuStarterAdapter(), row)
    r = res.record
    assert res.disposition is Disposition.INSERT
    assert r.lien_entity_type == "I"
    assert r.lien_first_name == "ANNETTE"
    assert r.lien_last_name == "GORE"
    assert any("promoted middle" in n for n in res.classification.notes)


# ----------------------------------------------------------------- validation

def test_missing_amount_is_rejected(att_ess_csv):
    rows = _rows(att_ess_csv)
    row = dict(rows[0])
    row["Amount"] = ""
    _, res = _build(AttEssAdapter(), row)
    assert res.disposition is Disposition.REJECT_MISSING
    assert any("lien_amount" in r for r in res.reasons)


def test_unresolvable_filing_type_is_rejected(att_ess_csv):
    rows = _rows(att_ess_csv)
    row = dict(rows[0])
    row["Type"] = ""
    row["Filing #"] = "XYZ-1"
    row["Creditor 1"] = "Unknown"
    _, res = _build(AttEssAdapter(), row)
    assert res.disposition is Disposition.REJECT_MISSING
    assert any("lien_filing_type" in r for r in res.reasons)
