"""End-to-end: run `preview` (no DB) over each sample file and the whole set."""

from __future__ import annotations

import shutil
from datetime import date

import pytest

from lien_import.config import AppConfig
from lien_import.models import Disposition
from lien_import.pipeline import run

RUN_DATE = date(2026, 8, 28)


def _preview(source_code, input_path, tmp_path, limit=None):
    cfg = AppConfig()
    return run(
        source_code=source_code,
        input_path=str(input_path),
        cfg=cfg,
        run_dir=tmp_path / "out",
        mode="preview",
        limit=limit,
        run_date=RUN_DATE,
    )


def test_att_ess_sample_all_insert(att_ess_csv, tmp_path):
    res = _preview("ES", att_ess_csv, tmp_path)
    a = res.audit
    assert a.examined == 25
    assert a.reconciles()
    assert a.rejected_missing == 0 and a.rejected_invalid == 0
    assert a.held_trust_estate == 0 and a.held_ambiguous == 0
    assert a.would_insert == 25
    assert a.federal + a.state == 25
    assert a.business + a.individual == 25
    assert a.state == 3          # Roger K Williams, Jennifer Boehm, Creative Motovation Llc
    assert a.business == 3       # Ccb Shop Company Llc, Big Dawgz Burgers Inc, Creative Motovation Llc


def test_combined_federal_sample(combined_federal_csv, tmp_path):
    a = _preview("TN", combined_federal_csv, tmp_path).audit
    assert a.examined == 21
    assert a.reconciles()
    assert a.would_insert == 21
    assert a.federal == 21 and a.state == 0
    assert a.individual == 21 and a.business == 0


def test_combined_state_sample(combined_state_csv, tmp_path):
    a = _preview("TN", combined_state_csv, tmp_path).audit
    assert a.examined == 22
    assert a.reconciles()
    assert a.would_insert == 22
    assert a.state == 22 and a.federal == 0
    assert a.business == 22 and a.individual == 0


def test_tnu_starter_sample(tnu_starter_csv, tmp_path):
    a = _preview("TN", tnu_starter_csv, tmp_path).audit
    assert a.examined == 24
    assert a.reconciles()
    assert a.would_insert == 24
    assert a.federal == 24
    assert a.individual == 24


def test_wrong_source_code_yields_no_adapter(att_ess_csv, tmp_path):
    # ATT/ESS file handed to the TN source -> no adapter matches, nothing examined
    a = _preview("TN", att_ess_csv, tmp_path).audit
    assert a.examined == 0
    assert a.unmapped_headers


def test_in_run_duplicate_detection(att_ess_csv, tmp_path):
    # same file twice in a directory -> second copy is all duplicates
    d = tmp_path / "dup"
    d.mkdir()
    shutil.copy(att_ess_csv, d / "copy_a.csv")
    shutil.copy(att_ess_csv, d / "copy_b.csv")
    a = _preview("ES", d, tmp_path).audit
    assert a.examined == 50
    assert a.would_insert == 25
    assert a.duplicates_within_source == 25
    assert a.reconciles()


def test_limit_option(combined_state_csv, tmp_path):
    a = _preview("TN", combined_state_csv, tmp_path, limit=5).audit
    assert a.examined == 5


def test_outputs_written(att_ess_csv, tmp_path):
    res = _preview("ES", att_ess_csv, tmp_path)
    out = res.run_dir
    assert (out / "audit_ES.json").is_file()
    assert (out / "audit_ES.txt").is_file()
    assert (out / "rejects_ES.csv").is_file()
    assert (out / "held_ES.csv").is_file()
    assert (out / "samples_ES.txt").is_file()
