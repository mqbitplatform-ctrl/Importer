"""Streaming / large-input behaviour: multi-chunk processing, cross-chunk
de-dup, ZIP streaming, and a rough throughput sanity check."""

from __future__ import annotations

import csv
import io
import time
import zipfile
from datetime import date

from lien_import.config import AppConfig
from lien_import.pipeline import run

RUN_DATE = date(2026, 8, 28)
HEADER = [
    "ListID", "PIN", "Filing #", "Full Name", "Address", "City", "State",
    "Zip Code", "County", "Filing Date", "Amount", "Type", "Creditor 1",
    "Phone number", "Respond By",
]


def _row(i: int) -> list[str]:
    return [
        "286", f"60243-{i:06d}", f"19F-{i:06d}", f"Person{i} Q Lastname{i}",
        f"{i} Main St", "Springfield", "IL", "62704", "Sangamon",
        "6/15/2021", f"${10000 + i}.00", "Federal", "Federal Tax Authorities",
        "(800) 000-0000", "9/2/2024",
    ]


def _make_csv(path, n_rows: int, dup_every: int = 0):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for i in range(n_rows):
            w.writerow(_row(i))
            if dup_every and i % dup_every == 0:
                w.writerow(_row(i))  # exact duplicate of an earlier row


def _cfg(tmp_path, chunk_size=1000):
    c = AppConfig()
    c.output_dir = tmp_path
    c.imports.chunk_size = chunk_size
    c.imports.progress_every = 2000
    return c


def test_multi_chunk_preview_reconciles(tmp_path):
    src = tmp_path / "big.csv"
    _make_csv(src, 12_000)
    cfg = _cfg(tmp_path, chunk_size=1000)
    res = run(source_code="ES", input_path=str(src), cfg=cfg,
              run_dir=tmp_path / "out", mode="preview", run_date=RUN_DATE)
    assert res.examined == 12_000
    assert res.audit.would_insert == 12_000
    assert res.audit.reconciles()
    # single format, per-format mirrors combined across all 12 chunks
    assert res.audit.by_format["att_ess"].examined == 12_000
    assert res.audit.by_format["att_ess"].reconciles()


def test_cross_chunk_duplicate_detection(tmp_path):
    src = tmp_path / "dups.csv"
    # 5,000 unique rows + an exact duplicate every 500th row (10 dupes),
    # duplicates land in the same or a later chunk than their original
    _make_csv(src, 5_000, dup_every=500)
    cfg = _cfg(tmp_path, chunk_size=700)
    res = run(source_code="ES", input_path=str(src), cfg=cfg,
              run_dir=tmp_path / "out", mode="preview", run_date=RUN_DATE)
    assert res.examined == 5_010
    assert res.audit.would_insert == 5_000
    assert res.audit.duplicates_within_source == 10
    assert res.audit.reconciles()


def test_zip_input_streams(tmp_path):
    zpath = tmp_path / "arch.zip"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADER)
    for i in range(3_000):
        w.writerow(_row(i))
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("part-01.csv", buf.getvalue())
    cfg = _cfg(tmp_path, chunk_size=800)
    res = run(source_code="ES", input_path=str(zpath), cfg=cfg,
              run_dir=tmp_path / "out", mode="preview", run_date=RUN_DATE)
    assert res.examined == 3_000
    assert res.audit.would_insert == 3_000
    assert res.audit.reconciles()


def test_throughput_sane(tmp_path):
    src = tmp_path / "perf.csv"
    n = 20_000
    _make_csv(src, n)
    cfg = _cfg(tmp_path, chunk_size=5000)
    t0 = time.monotonic()
    res = run(source_code="ES", input_path=str(src), cfg=cfg,
              run_dir=tmp_path / "out", mode="preview", run_date=RUN_DATE)
    elapsed = time.monotonic() - t0
    assert res.examined == n
    # generous CI-safe floor: full parse+normalise+classify+id-gen at >2k rows/s
    assert elapsed < n / 2000, f"{n} rows took {elapsed:.1f}s ({n/elapsed:.0f} rows/s)"
