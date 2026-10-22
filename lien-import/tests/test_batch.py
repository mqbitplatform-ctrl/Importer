"""Auto-import (inbox) + the ATT/ESS header variants found in the real archive."""

from __future__ import annotations

import csv
import io
import os
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

from lien_import.adapters import AttEssAdapter
from lien_import.batch import detect_source, file_sha256, run_batch, scan_inbox
from lien_import.config import AppConfig
from lien_import.normalize.text import canon_row
from lien_import.recordbuilder import build_record

DATA = Path(__file__).resolve().parent / "data"
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _cfg(tmp_path) -> AppConfig:
    c = AppConfig()
    c.output_dir = tmp_path / "out"
    c.inbox_dir = tmp_path / "inbox"
    c.processed_dir = tmp_path / "processed"
    c.failed_dir = tmp_path / "failed"
    c.inbox_dir.mkdir()
    return c


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


# ------------------------------------------------- ATT/ESS real-archive variants

_ROW = {
    "addr": "3801 W Campo Bello Dr", "city": "Glendale", "st": "AZ", "zip": "85308-4212",
    "county": "Maricopa", "date": "9/23/19", "amt": "$12,387.00",
}


@pytest.mark.parametrize("header, values", [
    # 60243-496: "Name"
    (["ListID", "PIN", "Filing #", "Name", "Address", "City", "State", "Zip Code", "County",
      "Filing Date", "Amount", "Type", "Creditor 1"],
     ["1", "P-1", "19F-1", "Jeffrey M Trexler", _ROW["addr"], _ROW["city"], _ROW["st"],
      _ROW["zip"], _ROW["county"], _ROW["date"], _ROW["amt"], "Federal", "Federal Tax Authorities"]),
    # 60243-503: "First Name" holds the full name
    (["ListID", "PIN", "Filing #", "First Name", "Address", "City", "State", "Zip Code", "County",
      "Filing Date", "Amount", "Type", "Creditor 1"],
     ["1", "P-1", "19F-1", "Jeffrey M Trexler", _ROW["addr"], _ROW["city"], _ROW["st"],
      _ROW["zip"], _ROW["county"], _ROW["date"], _ROW["amt"], "Federal", "Federal Tax Authorities"]),
    # 60243-542..551: no ListID / PIN, "English Creditor"
    (["Filing #", "Full Name", "Address", "City", "State", "Zip Code", "County", "Filing Date",
      "Amount", "Type", "English Creditor", "English Number", "Respond By"],
     ["19F-1", "Jeffrey M Trexler", _ROW["addr"], _ROW["city"], _ROW["st"], _ROW["zip"],
      _ROW["county"], _ROW["date"], _ROW["amt"], "Federal", "Federal Tax Authorities", "x", "y"]),
    # 60243-537: "Zip" not "Zip Code", no County column
    (["ListID", "PIN", "Filing #", "Full Name", "Address", "City", "State", "Zip", "Filing Date",
      "Amount", "Type", "English Creditor"],
     ["1", "P-1", "19F-1", "Jeffrey M Trexler", _ROW["addr"], _ROW["city"], _ROW["st"],
      _ROW["zip"], _ROW["date"], _ROW["amt"], "Federal", "Federal Tax Authorities"]),
])
def test_att_ess_header_variants(header, values):
    assert AttEssAdapter.matches(header)
    raw = dict(zip(header, values))
    m = AttEssAdapter().map_row(canon_row(raw), "f.csv", 1, raw)
    res = build_record(m, run_date=date(2026, 10, 22))
    r = res.record
    assert r is not None, res.reasons
    assert (r.lien_first_name, r.lien_last_name) == ("JEFFREY", "TREXLER")
    assert r.lien_zip == "85308"
    assert r.lien_filing_type == "F" and r.lien_plaintiff == "INTERNAL REVENUE SERVICE"
    assert m.source_ref in ("P-1", "19F-1")


def test_att_ess_does_not_claim_tnu_layouts():
    tnu_combined = ["Company", "First Name", "Last Name", "Middle Initial", "Full Name", "Address",
                    "City", "State", "Zip", "Filling County", "Filling Date", "Amount", "Creditor", "Note"]
    assert not AttEssAdapter.matches(tnu_combined)


# ---------------------------------------------------------------- no database

def test_scan_inbox_finds_csv_and_zip_recursively(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.csv").write_text("h\n")
    (tmp_path / "b.zip").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("ignore me")
    found = [p.name for p in scan_inbox(tmp_path)]
    assert found == ["x.csv", "b.zip"]
    assert scan_inbox(tmp_path / "missing") == []


def test_detect_source_on_samples():
    assert detect_source(DATA / "ATT-ESS-example.csv")[:2] == ("ES", "att_ess")
    assert detect_source(DATA / "Combined-State_example.csv")[:2] == ("TN", "tnu_combined")
    assert detect_source(DATA / "TNU Starter example.csv")[:2] == ("TN", "tnu_starter")


def test_detect_source_unrecognised(tmp_path):
    f = _write_csv(tmp_path / "x.csv", ["foo", "bar"], [["1", "2"]])
    src, fmt, problem = detect_source(f)
    assert src is None and "unrecognised" in problem


def test_detect_source_zip_single_and_mixed(tmp_path):
    ok = tmp_path / "es.zip"
    with zipfile.ZipFile(ok, "w") as zf:
        zf.write(DATA / "ATT-ESS-example.csv", "a.csv")
    assert detect_source(ok)[:2] == ("ES", "att_ess")

    mixed = tmp_path / "mixed.zip"
    with zipfile.ZipFile(mixed, "w") as zf:
        zf.write(DATA / "ATT-ESS-example.csv", "a.csv")
        zf.write(DATA / "TNU Starter example.csv", "b.csv")
    src, _, problem = detect_source(mixed)
    assert src is None and "mixes sources" in problem


def test_sha256_ignores_file_name(tmp_path):
    a = tmp_path / "a.csv"
    shutil.copy(DATA / "ATT-ESS-example.csv", a)
    b = tmp_path / "renamed copy.csv"
    shutil.copy(a, b)
    assert file_sha256(a) == file_sha256(b)


def test_empty_inbox(tmp_path):
    res = run_batch(_cfg(tmp_path))
    assert res.files == []


def test_preview_classifies_and_moves_nothing(tmp_path, monkeypatch):
    for k in ("LIEN_DB_HOST", "LIEN_DB_NAME", "LIEN_DB_USER", "LIEN_DB_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    cfg = _cfg(tmp_path)
    shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "es1.csv")
    sub = cfg.inbox_dir / "TNU folder"
    sub.mkdir()
    shutil.copy(DATA / "Combined-State_example.csv", sub / "state.csv")
    shutil.copy(DATA / "TNU Starter example.csv", sub / "starter.csv")
    _write_csv(cfg.inbox_dir / "junk.csv", ["foo"], [["1"]])

    res = run_batch(cfg, commit=False)

    status = {f.name.replace("\\", "/"): f.status for f in res.files}
    assert status == {
        "es1.csv": "previewed",
        "TNU folder/starter.csv": "previewed",
        "TNU folder/state.csv": "previewed",
        "junk.csv": "unrecognised",
    }
    assert res.source_totals["ES"]["would_insert"] == 25
    assert res.source_totals["TN"]["would_insert"] == 22 + 24
    assert len(scan_inbox(cfg.inbox_dir)) == 4          # nothing moved in preview
    assert not cfg.processed_dir.exists() and not cfg.failed_dir.exists()
    assert (res.run_dir / "auto_import_files.csv").is_file()
    assert (res.run_dir / "auto_import_summary.txt").is_file()


def test_preview_counts_a_lien_repeated_across_files_once(tmp_path, monkeypatch):
    for k in ("LIEN_DB_HOST",):
        monkeypatch.delenv(k, raising=False)
    cfg = _cfg(tmp_path)
    shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "mail-1.csv")
    shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "mail-2.csv")  # same 25 liens re-mailed
    res = run_batch(cfg, commit=False)
    t = res.source_totals["ES"]
    assert t["total_examined"] == 50
    assert t["would_insert"] == 25
    assert t["duplicates_within_source"] == 25


def test_commit_without_database_is_refused(tmp_path, monkeypatch):
    for k in ("LIEN_DB_HOST", "LIEN_DB_NAME", "LIEN_DB_USER"):
        monkeypatch.delenv(k, raising=False)
    cfg = _cfg(tmp_path)
    shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "es1.csv")
    with pytest.raises(RuntimeError, match="database"):
        run_batch(cfg, commit=True)
    assert len(scan_inbox(cfg.inbox_dir)) == 1


# ------------------------------------------------------------ live database

_needs_live_db = pytest.mark.skipif(
    not os.environ.get("LIEN_DB_HOST"),
    reason="requires MySQL; set LIEN_DB_* env vars and point at a throwaway schema",
)


@_needs_live_db
class TestAutoImportLive:
    @pytest.fixture()
    def cfg(self, tmp_path):
        from lien_import.config import load_config

        c = load_config(None)
        c.output_dir = tmp_path / "out"
        c.inbox_dir = tmp_path / "inbox"
        c.processed_dir = tmp_path / "processed"
        c.failed_dir = tmp_path / "failed"
        c.inbox_dir.mkdir()
        return c

    @pytest.fixture(autouse=True)
    def fresh_db(self, cfg):
        from lien_import import db as dbmod

        conn = dbmod.connect(cfg)
        with conn.cursor() as cur:
            for t in ("lien_import_files", "lien_import_log", "lien_import_rejects",
                      "liens_custom_data", cfg.database.liens_table):
                cur.execute(f"DROP TABLE IF EXISTS `{t}`")
            cur.execute((SQL_DIR / "liens_reference.sql").read_text(encoding="utf-8"))
            cur.execute((SQL_DIR / "lien_import_log.sql").read_text(encoding="utf-8"))
        conn.commit()
        self.conn = conn
        yield
        conn.close()

    def _q(self, sql, args=()):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def test_imports_moves_and_records_every_file(self, cfg):
        shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "es1.csv")
        (cfg.inbox_dir / "tnu").mkdir()
        shutil.copy(DATA / "Combined-State_example.csv", cfg.inbox_dir / "tnu" / "state.csv")
        _write_csv(cfg.inbox_dir / "junk.csv", ["foo"], [["1"]])

        res = run_batch(cfg, commit=True)

        st = {f.name.replace("\\", "/"): f.status for f in res.files}
        assert st == {"es1.csv": "imported", "tnu/state.csv": "imported", "junk.csv": "unrecognised"}
        assert self._q("SELECT lien_source, COUNT(*) FROM liens GROUP BY 1 ORDER BY 1") == (("ES", 25), ("TN", 22))
        assert len(self._q("SELECT * FROM lien_import_files")) == 2
        # inbox emptied (sub-folder pruned); files moved, junk has a reason file
        assert scan_inbox(cfg.inbox_dir) == []
        assert not (cfg.inbox_dir / "tnu").exists()
        processed = sorted(p.name for p in Path(cfg.processed_dir).rglob("*.csv"))
        assert processed == ["es1.csv", "state.csv"]
        failed = sorted(p.name for p in Path(cfg.failed_dir).rglob("*"))
        assert "junk.csv" in failed and "junk.csv.reason.txt" in failed

    def test_same_file_dropped_again_is_skipped_even_if_renamed(self, cfg):
        shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "es1.csv")
        run_batch(cfg, commit=True)
        shutil.copy(DATA / "ATT-ESS-example.csv", cfg.inbox_dir / "es1 - Copy (renamed).csv")

        res = run_batch(cfg, commit=True)

        assert [f.status for f in res.files] == ["already_imported"]
        assert self._q("SELECT COUNT(*) FROM liens")[0][0] == 25
        assert scan_inbox(cfg.inbox_dir) == []                        # moved out too
        assert len(list(Path(cfg.processed_dir).rglob("*.csv"))) == 2

    def test_lien_repeated_in_a_different_file_is_inserted_once(self, cfg):
        # a different file (one extra row changes its fingerprint) re-mailing the same liens
        rows = list(csv.reader((DATA / "ATT-ESS-example.csv").open(encoding="utf-8-sig")))
        _write_csv(cfg.inbox_dir / "mail-1.csv", rows[0], rows[1:])
        extra = list(rows[1]); extra[3] = "Brand New Person"; extra[10] = "$99,999.00"
        _write_csv(cfg.inbox_dir / "mail-2.csv", rows[0], rows[1:] + [extra])

        res = run_batch(cfg, commit=True)

        assert [f.status for f in res.files] == ["imported", "imported"]
        assert [f.inserted for f in res.files] == [25, 1]
        assert res.files[1].duplicates == 25
        assert self._q("SELECT COUNT(*) FROM liens")[0][0] == 26
