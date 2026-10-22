"""Live-MySQL integration test for the insert + idempotency path.

SKIPPED unless a database is configured via environment:

    LIEN_DB_HOST, LIEN_DB_NAME, LIEN_DB_USER, LIEN_DB_PASSWORD  (LIEN_DB_PORT optional)

It creates the reference `liens` table and `lien_import_log` in the target
schema, so point it at a THROWAWAY test database only. It asserts the complete
flow required by the handoff:

    preview (no writes)  ->  import --commit  ->  import --commit again (0 new)
    ->  verify count matches

Run:  LIEN_DB_HOST=... LIEN_DB_NAME=lien_test ... python -m pytest tests/test_db_integration.py -q
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("LIEN_DB_HOST"),
    reason="requires MySQL; set LIEN_DB_* env vars and point at a throwaway schema",
)

from lien_import import db as dbmod  # noqa: E402
from lien_import.config import load_config  # noqa: E402
from lien_import.pipeline import run  # noqa: E402

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
RUN_DATE = date(2026, 8, 28)


@pytest.fixture()
def cfg(tmp_path):
    c = load_config(None)  # env-only
    c.output_dir = tmp_path
    return c


@pytest.fixture()
def fresh_db(cfg):
    conn = dbmod.connect(cfg)
    with conn.cursor() as cur:
        for t in ("liens_custom_data", "lien_import_rejects",
                  "lien_import_log", cfg.database.liens_table):
            cur.execute(f"DROP TABLE IF EXISTS `{t}`")
        cur.execute(
            (SQL_DIR / "liens_reference.sql").read_text(encoding="utf-8")
            .replace("IF NOT EXISTS liens", f"IF NOT EXISTS `{cfg.database.liens_table}`")
        )
        cur.execute((SQL_DIR / "liens_custom_data_reference.sql").read_text(encoding="utf-8"))
        cur.execute((SQL_DIR / "lien_import_log.sql").read_text(encoding="utf-8"))
    conn.commit()
    yield conn
    conn.close()


def _count(conn, cfg):
    # end any stale MVCC snapshot so commits from the pipeline's own
    # connection become visible on this read connection
    conn.rollback()
    return dbmod.count_by_source(conn, cfg.database.liens_table, "ES")


def _run(cfg, tmp_path, mode, **kw):
    return run(
        source_code="ES",
        input_path=str(Path(__file__).resolve().parent / "data" / "ATT-ESS-example.csv"),
        cfg=cfg,
        run_dir=tmp_path / mode,
        mode=mode,
        run_date=RUN_DATE,
        **kw,
    )


def test_preview_then_import_is_idempotent(cfg, fresh_db, tmp_path):
    pv = _run(cfg, tmp_path, "preview", check_existing=True)
    assert pv.audit.would_insert == 25
    assert _count(fresh_db, cfg) == 0

    first = _run(cfg, tmp_path, "import", commit=True)
    assert first.inserted == 25
    assert first.committed
    assert _count(fresh_db, cfg) == 25

    second = _run(cfg, tmp_path, "import", commit=True)
    assert second.inserted == 0
    assert second.audit.duplicates_within_source == 25
    assert second.audit.would_insert == 0
    assert _count(fresh_db, cfg) == 25


def test_dry_run_import_writes_nothing(cfg, fresh_db, tmp_path):
    res = _run(cfg, tmp_path, "import", commit=False)
    assert res.inserted == 25  # prepared
    assert not res.committed
    assert _count(fresh_db, cfg) == 0


def test_import_log_captures_source_ref(cfg, fresh_db, tmp_path):
    _run(cfg, tmp_path, "import", commit=True)
    with fresh_db.cursor() as cur:
        cur.execute("SELECT COUNT(*), COUNT(source_ref) FROM lien_import_log")
        total, with_ref = cur.fetchone()
    assert total == 25
    assert with_ref == 25  # ATT/ESS PIN captured for every row


def test_persist_rejects_table(cfg, fresh_db, tmp_path):
    import csv as _csv

    src = Path(__file__).resolve().parent / "data" / "ATT-ESS-example.csv"
    rows = list(_csv.DictReader(src.open(encoding="utf-8-sig")))
    rows[0]["Amount"] = ""  # force one REJECT_MISSING
    bad = tmp_path / "bad.csv"
    with bad.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    run(source_code="ES", input_path=str(bad), cfg=cfg, run_dir=tmp_path / "imp",
        mode="import", commit=True, persist_rejects=True, run_date=RUN_DATE)
    fresh_db.rollback()
    with fresh_db.cursor() as cur:
        cur.execute("SELECT disposition, reasons FROM lien_import_rejects")
        recs = cur.fetchall()
    assert len(recs) == 1
    assert recs[0][0] == "REJECT_MISSING"
    assert "lien_amount" in recs[0][1]


def test_max_commit_rows_guard(cfg, fresh_db, tmp_path):
    cfg.imports.max_commit_rows = 5
    with pytest.raises(RuntimeError, match="max_commit_rows"):
        _run(cfg, tmp_path, "import", commit=True)  # 25 > 5
    assert _count(fresh_db, cfg) == 0
    # --force overrides
    res = _run(cfg, tmp_path, "import", commit=True, force=True)
    assert res.committed and res.inserted == 25


def _fat_rows(conn, user_index=61379):
    conn.rollback()  # fresh snapshot
    with conn.cursor() as cur:
        cur.execute(
            "SELECT lcdata_lien_source, lcdata_lien_id, lcdata_name, lcdata_value, "
            "lcdata_info, lcdata_last_used FROM liens_custom_data "
            "WHERE lcdata_user_index=%s ORDER BY CAST(lcdata_value AS UNSIGNED)",
            [user_index],
        )
        return cur.fetchall()


def test_fat_pull_writes_existing_liens_custom_data(cfg, fresh_db, tmp_path):
    from lien_import.fat import pull as fatpull

    _run(cfg, tmp_path, "import", commit=True)          # 25 ES liens
    fresh_db.rollback()

    an = fatpull.analyze(fresh_db, cfg)
    n = an["candidates_total"]
    assert n > 0
    assert an["already_assigned_to_fat"] == 0

    # preview: nothing written, no Case IDs
    dry = fatpull.run_pull(fresh_db, cfg, job="J1", run_dir=tmp_path / "fat", commit=False)
    assert dry.selected == n and not dry.committed and dry.first_case_id is None
    assert Path(dry.csv_path).is_file()
    assert _fat_rows(fresh_db) == ()

    # commit: one row per lien, exactly like the manual process
    live = fatpull.run_pull(fresh_db, cfg, job="J1", run_dir=tmp_path / "fat",
                            commit=True, start_case_id=1000)
    assert live.committed and live.assigned == n
    assert (live.first_case_id, live.last_case_id) == (1000, 1000 + n - 1)
    rows = _fat_rows(fresh_db)
    assert len(rows) == n
    assert [int(r[3]) for r in rows] == list(range(1000, 1000 + n))   # contiguous
    assert {r[2] for r in rows} == {"FREEAMTAX Case ID"}
    assert all(r[4] is None and r[5] is not None for r in rows)       # info NULL, last_used set

    # everything assigned -> nothing left, re-running selects nothing
    again = fatpull.analyze(fresh_db, cfg)
    assert again["candidates_total"] == 0
    assert again["already_assigned_to_fat"] == n
    assert again["highest_case_id_used"] == 1000 + n - 1
    rerun = fatpull.run_pull(fresh_db, cfg, job="J2", run_dir=tmp_path / "fat2",
                             commit=True, start_case_id=5000)
    assert rerun.selected == 0

    # every assignment satisfies the section 16 criteria
    with fresh_db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM liens_custom_data a JOIN liens l "
            " ON l.lien_source=a.lcdata_lien_source AND l.lien_id=a.lcdata_lien_id "
            " WHERE a.lcdata_user_index=61379 AND "
            " (l.lien_filing_type<>'F' OR l.lien_entity_type<>'I' OR l.lien_amount<5000)"
        )
        assert cur.fetchone()[0] == 0


def test_fat_commit_without_start_case_id_is_refused(cfg, fresh_db, tmp_path):
    from lien_import.fat import pull as fatpull

    _run(cfg, tmp_path, "import", commit=True)
    with pytest.raises(RuntimeError, match="start-case-id"):
        fatpull.run_pull(fresh_db, cfg, job="J1", run_dir=tmp_path / "f", commit=True)
    assert _fat_rows(fresh_db) == ()


def test_fat_ignores_other_customers_assignments(cfg, fresh_db, tmp_path):
    """A lien pulled for TNU (60275) is still available to Free America Tax."""
    from lien_import.fat import pull as fatpull

    _run(cfg, tmp_path, "import", commit=True)
    fresh_db.rollback()
    n = fatpull.analyze(fresh_db, cfg)["candidates_total"]
    with fresh_db.cursor() as cur:
        cur.execute("SELECT lien_source, lien_id FROM liens WHERE lien_filing_type='F' "
                    "AND lien_entity_type='I' LIMIT 1")
        src, lid = cur.fetchone()
        cur.execute("INSERT INTO liens_custom_data VALUES (%s,%s,60275,'TNU Case',  '1',NULL,NOW())",
                    [src, lid])
    fresh_db.commit()
    assert fatpull.analyze(fresh_db, cfg)["candidates_total"] == n


def test_fat_start_case_id_must_be_above_highest_used(cfg, fresh_db, tmp_path):
    """Catches typos: Logics Case IDs only go up, so a start at or below the
    highest one already used (incl. one that would overlap) is refused."""
    from lien_import.fat import pull as fatpull

    _run(cfg, tmp_path, "import", commit=True)
    fresh_db.rollback()
    with fresh_db.cursor() as cur:   # one lien already pulled with Case ID 5000
        cur.execute("SELECT lien_source, lien_id FROM liens WHERE lien_filing_type='F' "
                    "AND lien_entity_type='I' AND lien_amount>=5000 LIMIT 1")
        src, lid = cur.fetchone()
        cur.execute("INSERT INTO liens_custom_data VALUES "
                    "(%s,%s,61379,'FREEAMTAX Case ID','5000',NULL,NOW())", [src, lid])
    fresh_db.commit()

    for bad in (4995, 5000, 98):     # overlapping / equal / typo far below
        with pytest.raises(RuntimeError, match="not above the highest"):
            fatpull.run_pull(fresh_db, cfg, job="J1", run_dir=tmp_path / "f",
                             commit=True, start_case_id=bad)
    assert len(_fat_rows(fresh_db)) == 1                     # nothing new written

    ok = fatpull.run_pull(fresh_db, cfg, job="J1", run_dir=tmp_path / "f",
                          commit=True, start_case_id=6000)
    assert ok.committed and ok.first_case_id == 6000


def test_fat_non_positive_start_case_id_is_refused(cfg, fresh_db, tmp_path):
    from lien_import.fat import pull as fatpull

    _run(cfg, tmp_path, "import", commit=True)
    with pytest.raises(RuntimeError, match="positive"):
        fatpull.run_pull(fresh_db, cfg, job="J1", run_dir=tmp_path / "f",
                         commit=True, start_case_id=0)
    assert _fat_rows(fresh_db) == ()
