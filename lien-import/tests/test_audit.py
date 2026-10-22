import csv
from datetime import date

from lien_import.adapters import AttEssAdapter
from lien_import.audit import SourceAudit
from lien_import.normalize.text import canon_row
from lien_import.recordbuilder import build_record

RUN_DATE = date(2026, 8, 28)


def _audit_rows(rows):
    a = SourceAudit(source_code="ES", input_path="x")
    ad = AttEssAdapter()
    for i, raw in enumerate(rows, 1):
        m = ad.map_row(canon_row(raw), "f.csv", i, raw)
        br = build_record(m, run_date=RUN_DATE)
        a.record(br.disposition, br.classification, m.source_format, br.problem_fields)
    return a


def test_per_format_and_missing_field_tally(att_ess_csv):
    with open(att_ess_csv, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    rows[0] = {**rows[0], "Amount": ""}          # -> REJECT_MISSING lien_amount
    rows[1] = {**rows[1], "Filing Date": "??"}   # -> REJECT_MISSING lien_filing_date
    rows[2] = {**rows[2], "Amount": "-5"}        # -> REJECT_INVALID lien_amount

    a = _audit_rows(rows)
    assert a.examined == 25
    assert a.rejected_missing == 2
    assert a.rejected_invalid == 1
    assert a.would_insert == 22
    assert a.reconciles()

    tally = a.combined.missing_fields
    assert tally["lien_amount"] == 2          # one empty, one negative
    assert tally["lien_filing_date"] == 1

    # single format -> by_format mirrors combined
    assert set(a.by_format) == {"att_ess"}
    assert a.by_format["att_ess"].reconciles()
    assert a.by_format["att_ess"].would_insert == 22


def test_crosstab_totals(att_ess_csv):
    with open(att_ess_csv, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    a = _audit_rows(rows)
    c = a.combined
    assert c.fed_business + c.fed_individual + c.state_business + c.state_individual == c.would_insert
    assert c.federal == c.fed_business + c.fed_individual
    assert c.business == c.fed_business + c.state_business
