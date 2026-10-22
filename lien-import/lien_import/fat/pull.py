"""FAT pull: analyze / run_pull / status - on the EXISTING zm_dba tables.

Verified against the live zm_dba copy (2026-10):

  * Free America Tax is Zairmail customer ``user_index`` 61379
    (``profile.company_name = 'Free America Tax'``).
  * Every lien already pulled for them is ONE row in ``liens_custom_data``::

        lcdata_lien_source / lcdata_lien_id   -> the lien
        lcdata_user_index  = 61379
        lcdata_name        = 'FREEAMTAX Case ID'
        lcdata_value       = <the Case ID, numeric text>
        lcdata_info        = NULL
        lcdata_last_used   = <timestamp of the pull>

    69,000 rows over 6 pulls of 10,000-14,000; all Federal / Individual /
    >= $5,000 - exactly the handoff's section 16 criteria.
  * Case IDs are unique and contiguous WITHIN a pull but jump BETWEEN pulls
    (38630 -> 38636, 76637 -> 76660, 87159 -> 88230). They are therefore
    allocated outside zm_dba (in Logics), so this tool never invents one: the
    first Case ID of a pull is supplied by the operator, and the range is
    refused if any of it is already used.

No new tables are created - writing the same rows the manual process writes
means the existing Zairmail applications see these pulls too.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import AppConfig
from ..models import COLUMN_ORDER
from .criteria import FatCriteria

log = logging.getLogger("lien_import.fat.pull")

# Observed on the live data: the first pulls drained the newest load window
# (2025-06..2025-09) before going back to older loads -> newest first. The
# manual process document is still needed to confirm the exact ordering.
_ORDER_BY = "l.lien_load_date DESC, l.lien_filing_date DESC, l.lien_source, l.lien_id"


# --------------------------------------------------------------------- analyze

def analyze(conn, cfg: AppConfig, *, source: Optional[str] = None) -> dict:
    crit = FatCriteria.from_config(cfg.fat)
    if source:
        crit.sources = [source]
    where, params = crit.where("l", cfg.fat.assignment_table)
    t = cfg.database.liens_table

    def q(sql, extra=()):
        with conn.cursor() as cur:
            cur.execute(sql, [*params, *extra])
            return list(cur.fetchall())

    total = q(f"SELECT COUNT(*) FROM `{t}` l WHERE {where}")[0][0]
    by_source = q(f"SELECT l.lien_source, COUNT(*) FROM `{t}` l WHERE {where} GROUP BY 1 ORDER BY 1")
    by_state = q(
        f"SELECT l.lien_jurisdiction, COUNT(*) FROM `{t}` l WHERE {where} "
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
    )
    amt = q(
        f"SELECT MIN(l.lien_amount), MAX(l.lien_amount), AVG(l.lien_amount), SUM(l.lien_amount) "
        f"FROM `{t}` l WHERE {where}"
    )[0]
    already, last_pull, max_case = _assigned_summary(conn, cfg)

    return {
        "criteria": crit.to_dict(),
        "candidates_total": total,
        "candidates_by_source": {r[0]: r[1] for r in by_source},
        "candidates_by_state": {r[0]: r[1] for r in by_state},
        "candidate_amount": {
            "min": str(amt[0]) if amt[0] is not None else None,
            "max": str(amt[1]) if amt[1] is not None else None,
            "avg": str(round(amt[2], 2)) if amt[2] is not None else None,
            "sum": str(amt[3]) if amt[3] is not None else None,
        },
        "already_assigned_to_fat": already,
        "last_pull_at": str(last_pull) if last_pull else None,
        "highest_case_id_used": max_case,
    }


def _assigned_summary(conn, cfg: AppConfig) -> tuple[int, Optional[datetime], Optional[int]]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*), MAX(lcdata_last_used), "
            f"MAX(CAST(lcdata_value AS UNSIGNED)) "
            f"FROM `{cfg.fat.assignment_table}` "
            f"WHERE lcdata_user_index = %s AND lcdata_name = %s",
            [int(cfg.fat.user_index), cfg.fat.case_id_name],
        )
        n, last, mx = cur.fetchone()
    return int(n or 0), last, (int(mx) if mx is not None else None)


def render_analysis(rep: dict) -> str:
    out = [
        "FAT candidate analysis (read-only)",
        "=" * 48,
        f"criteria: {rep['criteria']}",
        "",
        f"candidates (not yet assigned): {rep['candidates_total']:,}",
        f"  by source: {rep['candidates_by_source']}",
        f"  by state (top 15): {rep['candidates_by_state']}",
        f"  amount: {rep['candidate_amount']}",
        "",
        f"already assigned to FAT: {rep['already_assigned_to_fat']:,}",
        f"last pull:               {rep['last_pull_at'] or '(none)'}",
        f"highest Case ID used:    {rep['highest_case_id_used'] if rep['highest_case_id_used'] is not None else '(none)'}",
        "  (Case IDs come from Logics - get the next starting number from there,",
        "   not by adding 1 to this figure; past pulls have gaps between them.)",
    ]
    return "\n".join(out)


# ---------------------------------------------------------------------- pull

@dataclass
class PullResult:
    job: str
    selected: int = 0
    assigned: int = 0
    first_case_id: Optional[int] = None
    last_case_id: Optional[int] = None
    committed: bool = False
    csv_path: Optional[str] = None
    criteria: dict = field(default_factory=dict)

    def render(self) -> str:
        state = "COMMITTED" if self.committed else "PREVIEW - nothing written"
        ids = (f"{self.first_case_id} .. {self.last_case_id}"
               if self.first_case_id is not None else "(not assigned - preview)")
        return (
            f"FAT pull  job={self.job}\n"
            f"  criteria: {self.criteria}\n"
            f"  liens selected:        {self.selected:,}\n"
            f"  Case IDs:              {ids}\n"
            f"  assignments written:   {self.assigned:,}   [{state}]\n"
            f"  pull CSV:              {self.csv_path or '(none)'}"
        )


def run_pull(
    conn,
    cfg: AppConfig,
    *,
    job: str,
    run_dir: Path,
    commit: bool = False,
    limit: Optional[int] = None,
    start_case_id: Optional[int] = None,
) -> PullResult:
    """Select the next liens for FAT and (with commit=True) record them in
    ``liens_custom_data`` with sequential Case IDs from *start_case_id*.

    Without commit nothing is written - it only writes the preview CSV.
    """
    if commit and start_case_id is None:
        raise RuntimeError(
            "A FAT pull needs the first Case ID to use (from Logics) - "
            "pass --start-case-id. Nothing was written."
        )
    if start_case_id is not None and start_case_id <= 0:
        raise RuntimeError("--start-case-id must be a positive number. Nothing was written.")

    crit = FatCriteria.from_config(cfg.fat)
    where, params = crit.where("l", cfg.fat.assignment_table)
    t = cfg.database.liens_table
    cols = ", ".join(f"l.`{c}`" for c in COLUMN_ORDER)
    sql = f"SELECT {cols} FROM `{t}` l WHERE {where} ORDER BY {_ORDER_BY}"
    if limit:
        sql += " LIMIT %s"

    with conn.cursor() as cur:
        cur.execute(sql, [*params, limit] if limit else params)
        rows = [dict(zip(COLUMN_ORDER, r)) for r in cur.fetchall()]

    res = PullResult(job=job, selected=len(rows), criteria=crit.to_dict())
    if not rows:
        log.warning("no liens match the FAT criteria (nothing to pull)")
        return res

    if start_case_id is not None:
        first, last = start_case_id, start_case_id + len(rows) - 1
        _, _, highest = _assigned_summary(conn, cfg)
        if highest is not None and first <= highest:
            # Logics Case IDs only ever go up (verified: every past pull starts
            # above the previous one). A lower number is almost certainly a typo
            # - and could slip into an unused gap the overlap check can't see.
            raise RuntimeError(
                f"Starting Case ID {first} is not above the highest Case ID already "
                f"used ({highest}). Case IDs from Logics only go up - check the number. "
                "Nothing was written."
            )
        # belt and braces: another writer could have used part of the range
        # between the check above and now
        clash = _case_ids_in_use(conn, cfg, first, last)
        if clash:
            raise RuntimeError(
                f"Case IDs {first}-{last} overlap {clash:,} Case ID(s) already used for "
                f"user {cfg.fat.user_index}. Get a fresh starting number from Logics. "
                "Nothing was written."
            )
        for i, r in enumerate(rows):
            r["case_id"] = first + i
        res.first_case_id, res.last_case_id = first, last
    else:
        for r in rows:
            r["case_id"] = None

    run_dir.mkdir(parents=True, exist_ok=True)
    csv_path = run_dir / f"fat_pull_{job}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([*COLUMN_ORDER, cfg.fat.case_id_name, "fat_job", "user_index"])
        for r in rows:
            w.writerow([r.get(c) for c in COLUMN_ORDER] + [r["case_id"], job, cfg.fat.user_index])
    res.csv_path = str(csv_path)

    if not commit:
        log.info("FAT job %s: preview only, %d liens selected, nothing written", job, len(rows))
        return res

    now = datetime.now().replace(microsecond=0)
    try:
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO `{cfg.fat.assignment_table}` "
                "(lcdata_lien_source, lcdata_lien_id, lcdata_user_index, lcdata_name, "
                "lcdata_value, lcdata_info, lcdata_last_used) "
                "VALUES (%s,%s,%s,%s,%s,NULL,%s)",
                [
                    (r["lien_source"], r["lien_id"], int(cfg.fat.user_index),
                     cfg.fat.case_id_name, str(r["case_id"]), now)
                    for r in rows
                ],
            )
            res.assigned = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    res.committed = True
    log.info("FAT job %s: committed %d assignments, Case IDs %s-%s",
             job, res.assigned, res.first_case_id, res.last_case_id)
    return res


def _case_ids_in_use(conn, cfg: AppConfig, first: int, last: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM `{cfg.fat.assignment_table}` "
            f"WHERE lcdata_user_index = %s AND lcdata_name = %s "
            f"AND lcdata_value REGEXP '^[0-9]+$' "
            f"AND CAST(lcdata_value AS UNSIGNED) BETWEEN %s AND %s",
            [int(cfg.fat.user_index), cfg.fat.case_id_name, first, last],
        )
        return int(cur.fetchone()[0])


# --------------------------------------------------------------------- status

def status(conn, cfg: AppConfig) -> list[str]:
    """One line per past pull (grouped by the pull timestamp's date)."""
    out = []
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DATE(lcdata_last_used), COUNT(*), "
            f"MIN(CAST(lcdata_value AS UNSIGNED)), MAX(CAST(lcdata_value AS UNSIGNED)) "
            f"FROM `{cfg.fat.assignment_table}` "
            f"WHERE lcdata_user_index = %s AND lcdata_name = %s "
            f"GROUP BY 1 ORDER BY 1",
            [int(cfg.fat.user_index), cfg.fat.case_id_name],
        )
        for d, n, lo, hi in cur.fetchall():
            out.append(f"pulled {d}:  {n:,} liens   Case IDs {lo} .. {hi}")
    if not out:
        out.append("(no FAT assignments recorded)")
    return out
