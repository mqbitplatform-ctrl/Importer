"""Parallel-worker path and the streaming knobs produce identical results to
the serial path."""

from __future__ import annotations

import csv
from datetime import date

from lien_import.config import AppConfig
from lien_import.pipeline import run

RUN_DATE = date(2026, 8, 28)
HEADER = [
    "ListID", "PIN", "Filing #", "Full Name", "Address", "City", "State",
    "Zip Code", "County", "Filing Date", "Amount", "Type", "Creditor 1",
    "Phone number", "Respond By",
]


def _make(path, n):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for i in range(n):
            kind = "Federal" if i % 3 else "State"
            cred = "Federal Tax Authorities" if i % 3 else "State Of California"
            w.writerow([
                "286", f"60243-{i:06d}", f"19F-{i:06d}", f"Person{i} Q Last{i}",
                f"{i} Main St", "Springfield", "IL", "62704", "Sangamon",
                "6/15/2021", f"${20000 + i}.00", kind, cred, "x", "9/2/2024",
            ])


def _audit(cfg, src, tmp_path, tag):
    return run(source_code="ES", input_path=str(src), cfg=cfg,
               run_dir=tmp_path / tag, mode="preview", run_date=RUN_DATE).audit


def test_workers_match_serial(tmp_path):
    src = tmp_path / "w.csv"
    _make(src, 8_000)

    c1 = AppConfig(); c1.output_dir = tmp_path
    c1.imports.chunk_size = 1000; c1.imports.workers = 1
    a1 = _audit(c1, src, tmp_path, "serial")

    c4 = AppConfig(); c4.output_dir = tmp_path
    c4.imports.chunk_size = 1000; c4.imports.workers = 4
    a4 = _audit(c4, src, tmp_path, "par")

    assert a1.to_dict()["combined"]["section12"] == a4.to_dict()["combined"]["section12"]
    assert a1.would_insert == a4.would_insert == 8_000
    assert a1.federal == a4.federal
    assert a1.state == a4.state
    assert a4.reconciles()


def test_chunk_size_does_not_change_counts(tmp_path):
    src = tmp_path / "c.csv"
    _make(src, 6_000)
    results = []
    for cs in (500, 2000, 6000, 20000):
        c = AppConfig(); c.output_dir = tmp_path
        c.imports.chunk_size = cs
        a = _audit(c, src, tmp_path, f"cs{cs}")
        results.append((a.examined, a.would_insert, a.federal, a.state))
        assert a.reconciles()
    assert len(set(results)) == 1  # identical regardless of chunk size
