"""import.allow_duplicates / --allow-duplicates: keep a lien repeated across
files (or rows) as separate rows, while a re-import of the SAME file still
adds nothing."""

from __future__ import annotations

import csv
import json
import os
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

from lien_import.config import AppConfig, load_config
from lien_import.pipeline import _row_scoped_key, run

DATA = Path(__file__).resolve().parent / "data"
SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
SAMPLE = DATA / "ATT-ESS-example.csv"  # 25 rows, all insertable
RUN_DATE = date(2026, 10, 22)


def _cfg(allow: bool) -> AppConfig:
    c = AppConfig()
    c.imports.allow_duplicates = allow
    return c


def _preview(cfg, input_path, run_dir):
    return run(source_code="ES", input_path=input_path, cfg=cfg, run_dir=run_dir,
               mode="preview", run_date=RUN_DATE)


def _two_copies(tmp_path) -> Path:
    d = tmp_path / "in"
    d.mkdir()
    shutil.copy(SAMPLE, d / "may.csv")
    shutil.copy(SAMPLE, d / "june.csv")  # same liens, re-mailed next month
    return d


# ------------------------------------------------------------------ the key

def test_row_scoped_key_uses_only_the_csv_name_and_row():
    base = "JOHN SMITH|1 MAIN ST|85308|F|2019-09-23|100.00"
    k = _row_scoped_key(base, "60243-415.csv", 7)
    assert k == base + "|ROW|60243-415.CSV#7"
    # moving the file or zipping it must not change the id
    assert _row_scoped_key(base, "ATT-ESS.zip!ATT-ESS/60243-415.csv", 7) == k
    assert _row_scoped_key(base, "60243-415.csv", 8) != k


# ---------------------------------------------------------------- previews

def test_off_by_default_repeated_liens_counted_once(tmp_path):
    a = _preview(_cfg(False), str(_two_copies(tmp_path)), tmp_path / "out").audit
    assert (a.examined, a.would_insert, a.duplicates_within_source) == (50, 25, 25)
    assert not a.allow_duplicates


def test_on_repeated_liens_across_files_are_all_kept(tmp_path):
    a = _preview(_cfg(True), str(_two_copies(tmp_path)), tmp_path / "out").audit
    assert (a.examined, a.would_insert, a.duplicates_within_source) == (50, 50, 0)
    assert a.reconciles()
    assert "DUPLICATES ALLOWED" in a.render_text()
    assert json.loads(a.to_json())["allow_duplicates"] is True


def test_on_identical_rows_inside_one_file_are_all_kept(tmp_path):
    with SAMPLE.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    f = tmp_path / "doubled.csv"
    with f.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows([rows[0], *rows[1:], *rows[1:]])
    on = _preview(_cfg(True), str(f), tmp_path / "on").audit
    off = _preview(_cfg(False), str(f), tmp_path / "off").audit
    assert (on.would_insert, off.would_insert) == (50, 25)


def test_on_rejects_and_holds_still_apply(tmp_path):
    # the flag only affects de-duplication, never validation
    f = tmp_path / "bad.csv"
    with SAMPLE.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    amount_col = rows[0].index("Amount")
    rows[1][amount_col] = "$-"
    with f.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    a = _preview(_cfg(True), str(f), tmp_path / "out").audit
    assert a.rejected_missing == 1 and a.would_insert == 24


def test_cli_flag_turns_it_on(tmp_path):
    from lien_import.cli import main

    d = _two_copies(tmp_path)
    rc = main(["--config", str(tmp_path / "none.json"), "--output", str(tmp_path / "out"),
               "preview", "--source", "ES", "--input", str(d), "--allow-duplicates"])
    assert rc == 0
    audit = json.loads(next((tmp_path / "out").rglob("audit_ES.json")).read_text(encoding="utf-8"))
    assert audit["allow_duplicates"] is True
    assert audit["combined"]["section12"]["would_insert"] == 50


def test_config_round_trip(tmp_path):
    from lien_import.config import save_config

    c = AppConfig()
    c.imports.allow_duplicates = True
    p = tmp_path / "config.json"
    save_config(c, p)
    assert load_config(p).imports.allow_duplicates is True
    assert load_config(None).imports.allow_duplicates is False


# ------------------------------------------------------------ live database

@pytest.mark.skipif(not os.environ.get("LIEN_DB_HOST"),
                    reason="requires MySQL; set LIEN_DB_* env vars and point at a throwaway schema")
class TestAllowDuplicatesLive:
    @pytest.fixture()
    def cfg(self, tmp_path):
        from lien_import import db as dbmod

        c = load_config(None)
        c.imports.allow_duplicates = True
        conn = dbmod.connect(c)
        with conn.cursor() as cur:
            for t in ("lien_import_log", c.database.liens_table):
                cur.execute(f"DROP TABLE IF EXISTS `{t}`")
            cur.execute((SQL_DIR / "liens_reference.sql").read_text(encoding="utf-8"))
            cur.execute((SQL_DIR / "lien_import_log.sql").read_text(encoding="utf-8"))
        conn.commit()
        self.conn = conn
        yield c
        conn.close()

    def _count(self, cfg):
        from lien_import import db as dbmod

        self.conn.rollback()
        return dbmod.count_by_source(self.conn, cfg.database.liens_table, "ES")

    def _import(self, cfg, path, run_dir):
        return run(source_code="ES", input_path=path, cfg=cfg, run_dir=run_dir,
                   mode="import", commit=True, run_date=RUN_DATE)

    def test_both_copies_inserted_and_rerun_adds_nothing(self, cfg, tmp_path):
        d = _two_copies(tmp_path)
        assert self._import(cfg, str(d), tmp_path / "r1").inserted == 50
        assert self._count(cfg) == 50
        # same files again (even moved into a zip) -> nothing new
        z = tmp_path / "again.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(d / "may.csv", "sub/may.csv")
            zf.write(d / "june.csv", "june.csv")
        assert self._import(cfg, str(z), tmp_path / "r2").inserted == 0
        assert self._count(cfg) == 50
