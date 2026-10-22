"""Orchestration: read -> map -> normalise -> validate -> de-dupe -> audit -> (load).

Streaming design (bounded memory, safe for very large archives):

  * source rows are read incrementally (see sourcereader) and processed in
    chunks of ``import.chunk_size``;
  * ``rejects_<SRC>.csv`` / ``held_<SRC>.csv`` / ``samples_<SRC>.txt`` are
    written as we go, never buffered whole;
  * on ``import --commit`` each chunk is inserted and committed on its own, so
    the transaction/undo-log stays small and a failed run is resumable (the
    importer is idempotent - re-running skips what was already inserted);
  * de-dupe state held in RAM is just the set of lien_ids not yet visible to
    the DB existence check: only the current chunk when committing per chunk,
    the whole run for a dry-run / preview.

Modes:
  preview  - never writes; optional DB reads for existing-id / collision check
  import   - writes only when commit=True (per chunk); otherwise counts only
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from . import db as dbmod
from .adapters import REGISTRY, find_adapter
from .audit import SourceAudit
from .config import AppConfig
from .idgen import make_lien_id
from .models import Disposition
from .normalize.text import canon_header, canon_row
from .recordbuilder import build_record

log = logging.getLogger("lien_import.pipeline")

_SAMPLE_LIMIT = 40
_CSV_HEADER = [
    "source_file", "source_row", "source_format", "disposition", "reasons",
    "name_or_company", "amount_raw", "filing_date_raw", "creditor",
]
_REJECT_DISPS = (Disposition.REJECT_MISSING, Disposition.REJECT_INVALID)
_HELD_DISPS = (Disposition.HOLD_TRUST_ESTATE, Disposition.HOLD_AMBIGUOUS)


@dataclass
class RunResult:
    audit: SourceAudit
    run_dir: Path
    inserted: int = 0
    committed: bool = False
    examined: int = 0
    stopped_early: bool = False


def _raw_get(raw: dict[str, str], *names: str) -> str:
    lowered = {k.lower(): v for k, v in raw.items()}
    for n in names:
        if n.lower() in lowered and lowered[n.lower()]:
            return lowered[n.lower()]
    return ""


def _base_row(mapped, br, d) -> list:
    return [
        mapped.source_file, mapped.source_row_num, mapped.source_format, d.value,
        " | ".join(br.reasons),
        _raw_get(mapped.raw, "Full Name", "Company", "Business Name", "First Name", "Last Name"),
        mapped.amount_raw or "", mapped.filing_date_raw or "", mapped.creditor or "",
    ]


def _row_scoped_key(natural_key: str, source_file: str, row_num: int) -> str:
    """allow_duplicates: make the key unique per SOURCE ROW, so the same lien in
    several files gets several lien_ids. Only the CSV's own name is used (not
    the folder / zip path), so moving a file inbox -> processed, or re-zipping
    it, gives the same ids and a re-import of that file still adds nothing."""
    member = source_file.rsplit("!", 1)[-1]  # 'archive.zip!dir/x.csv' -> 'dir/x.csv'
    return f"{natural_key}|ROW|{Path(member).name.upper()}#{row_num}"


def _batched_raw(row_iter, size: int, limit: Optional[int]):
    """Yield lists of (file, row_num, raw_dict), <= *size* each, <= *limit* total."""
    batch, n = [], 0
    for srow in row_iter:
        batch.append((srow.file, srow.row_num, srow.data))
        n += 1
        if len(batch) >= size:
            yield batch
            batch = []
        if limit and n >= limit:
            break
    if batch:
        yield batch


def _serial_built(raw_batch, source_code, run_date, min_year, adapter_cache):
    built, unmapped = [], []
    for file, row_num, raw in raw_batch:
        raw_headers = tuple(raw.keys())
        cached = adapter_cache.get(raw_headers)
        if cached is None:
            sig = tuple(sorted(canon_header(h) for h in raw_headers))
            cached = (sig, find_adapter(source_code, raw_headers, REGISTRY))
            adapter_cache[raw_headers] = cached
        sig, adapter = cached
        if adapter is None:
            unmapped.append((file, list(raw_headers), sig))
            continue
        mapped = adapter.map_row(canon_row(raw), file, row_num, raw)
        br = build_record(mapped, run_date=run_date, min_filing_year=min_year)
        built.append((mapped, br))
    return built, unmapped


def _parallel_built(executor, fn, raw_batches, workers, source_code, run_date_iso, min_year):
    """Submit batches to *executor*, yield (built, unmapped) in original order,
    keeping at most ~2*workers batches outstanding."""
    from collections import deque

    pending: deque = deque()
    it = iter(raw_batches)

    def _submit_next() -> bool:
        try:
            b = next(it)
        except StopIteration:
            return False
        pending.append(executor.submit(fn, (source_code, run_date_iso, min_year, b)))
        return True

    for _ in range(max(2, workers * 2)):
        if not _submit_next():
            break

    while pending:
        res = pending.popleft().result()  # in submission order
        built, unmapped = [], []
        for item in res:
            if item[0] == "ok":
                built.append((item[1], item[2]))
            else:
                unmapped.append((item[1], item[2], item[3]))
        yield built, unmapped
        _submit_next()


def run(
    *,
    source_code: str,
    input_path: str,
    cfg: AppConfig,
    run_dir: Path,
    mode: str,  # 'preview' | 'import'
    limit: Optional[int] = None,
    check_existing: bool = False,
    commit: bool = False,
    force: bool = False,
    persist_rejects: bool = False,
    run_date: Optional[date] = None,
) -> RunResult:
    from .sourcereader import iter_source_rows

    run_date = run_date or date.today()
    if mode == "import" and not cfg.database.is_configured:
        raise RuntimeError(
            "import mode requires a configured database - fill config.json "
            "(database.host/name/user) or set LIEN_DB_* environment variables"
        )

    ic = cfg.imports
    liens_table = cfg.database.liens_table
    audit = SourceAudit(source_code=source_code, input_path=str(input_path),
                        allow_duplicates=ic.allow_duplicates)
    if ic.allow_duplicates:
        log.warning("allow_duplicates is ON: a lien repeated across files/rows is kept as "
                    "separate rows (re-importing the same file still adds nothing)")
    run_dir.mkdir(parents=True, exist_ok=True)

    want_db = mode == "import" or (mode == "preview" and check_existing)
    conn = None
    if want_db and cfg.database.is_configured:
        conn = dbmod.connect(cfg)
    elif want_db:
        log.warning("DB check requested but database not configured - skipping existence check")

    log_table = ic.import_log_table if ic.use_import_log_table else None
    if mode == "import" and commit and conn is not None:
        if log_table:
            dbmod.ensure_import_log_table(conn, log_table)
        if persist_rejects:
            dbmod.ensure_rejects_table(conn, ic.rejects_table)

    # Fast path: if this source has no rows anywhere yet, skip the per-chunk DB
    # existence/collision round-trips and keep the whole-run de-dupe set in RAM
    # (~150 B per inserted row). Re-imports into a non-empty source take the
    # safe path: per-chunk DB checks + a de-dupe set bounded to one chunk.
    first_import = False
    if conn is not None:
        n_liens = dbmod.count_by_source(conn, liens_table, source_code)
        n_log = 0
        if log_table and dbmod.table_exists(conn, log_table):
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM `{log_table}` WHERE lien_source = %s", [source_code]
                )
                n_log = int(cur.fetchone()[0])
        first_import = n_liens == 0 and n_log == 0
        if first_import:
            log.info("source %s empty in DB - append fast path (no per-chunk existence checks)",
                     source_code)

    # incremental output writers
    rej_fh = (run_dir / f"rejects_{source_code}.csv").open("w", newline="", encoding="utf-8")
    held_fh = (run_dir / f"held_{source_code}.csv").open("w", newline="", encoding="utf-8")
    samp_fh = (run_dir / f"samples_{source_code}.txt").open("w", encoding="utf-8")
    rej_w, held_w = csv.writer(rej_fh), csv.writer(held_fh)
    rej_w.writerow(_CSV_HEADER)
    held_w.writerow(_CSV_HEADER)

    seen: dict[str, str] = {}  # lien_id -> natural_key_sha1 (not yet DB-visible)
    adapter_cache: dict[tuple, object] = {}
    seen_unmapped: set[tuple] = set()
    state = {"examined": 0, "inserted": 0, "samples": 0, "stopped": False}
    t0 = time.monotonic()

    def process_chunk(chunk: list[tuple]) -> None:
        if not chunk or state["stopped"]:
            return
        disp = [br.disposition for _, br in chunk]
        ins_idx = [i for i, (_, br) in enumerate(chunk) if br.disposition is Disposition.INSERT]

        # ids + within-run duplicate detection
        for i in ins_idx:
            rec = chunk[i][1].record
            if ic.allow_duplicates:
                m = chunk[i][0]
                rec.natural_key = _row_scoped_key(rec.natural_key, m.source_file, m.source_row_num)
            lid, sha = make_lien_id(rec.lien_source, rec.natural_key)
            rec.lien_id, rec.natural_key_sha1 = lid, sha
            if lid in seen:
                disp[i] = Disposition.SKIP_DUPLICATE
            else:
                seen[lid] = sha

        # DB existence + collision (per chunk) - skipped on the append fast path
        if conn is not None and not first_import:
            live = [i for i in ins_idx if disp[i] is Disposition.INSERT]
            ids = [chunk[i][1].record.lien_id for i in live]
            existing = dbmod.fetch_existing_liens_ids(conn, liens_table, source_code, ids)
            log_sha1: dict[str, str] = {}
            if log_table:
                try:
                    log_sha1 = dbmod.fetch_log_sha1(conn, log_table, source_code, ids)
                except Exception as exc:  # table absent during a preview
                    log.debug("import-log lookup skipped: %s", exc)
            for i in live:
                rec = chunk[i][1].record
                if rec.lien_id in existing:
                    disp[i] = Disposition.SKIP_DUPLICATE
                    continue
                prior = log_sha1.get(rec.lien_id)
                if prior and prior != rec.natural_key_sha1:
                    new_id, _ = make_lien_id(
                        rec.lien_source, rec.natural_key,
                        lookup_existing_sha1=lambda c: log_sha1.get(c) or seen.get(c),
                    )
                    log.warning("lien_id collision %s -> %s", rec.lien_id, new_id)
                    rec.lien_id = new_id
                    seen[new_id] = rec.natural_key_sha1

        # collect INSERT rows
        to_insert = []
        for i in ins_idx:
            if disp[i] is not Disposition.INSERT:
                continue
            mapped, br = chunk[i]
            rec = br.record
            rec._source_format = mapped.source_format
            rec._source_file = mapped.source_file
            rec._source_row_num = mapped.source_row_num
            rec._source_ref = mapped.source_ref
            to_insert.append(rec)

        # max-commit guard (cumulative across the run)
        if mode == "import" and commit and not force:
            if state["inserted"] + len(to_insert) > ic.max_commit_rows:
                if state["inserted"] == 0:
                    raise RuntimeError(
                        f"this run would insert more than import.max_commit_rows "
                        f"({ic.max_commit_rows:,}); review the preview/audit then re-run "
                        f"with --force (the import is idempotent and resumable)"
                    )
                state["stopped"] = True
                if conn is not None:
                    conn.commit()  # keep the rows inserted so far
                log.warning(
                    "max_commit_rows (%d) reached; %d rows committed so far. Re-run "
                    "with --force to finish (idempotent, resumes where it stopped).",
                    ic.max_commit_rows, state["inserted"],
                )
                return

        # audit + incremental files
        for (mapped, br), d in zip(chunk, disp):
            audit.record(d, br.classification, mapped.source_format, br.problem_fields)
            if d in _REJECT_DISPS:
                rej_w.writerow(_base_row(mapped, br, d))
            elif d in _HELD_DISPS:
                held_w.writerow(_base_row(mapped, br, d))
            elif d is Disposition.INSERT and state["samples"] < _SAMPLE_LIMIT:
                state["samples"] += 1
                r, cls = br.record, br.classification
                samp_fh.write(
                    f"{r.lien_id}  {r.lien_source}/{r.lien_filing_type}/{r.lien_entity_type}  "
                    f"juris={r.lien_jurisdiction}({cls.jurisdiction_source})  "
                    f"amt={r.lien_amount}  date={r.lien_filing_date}  "
                    f"name={cls.name_used!r}  kind={cls.name_kind}"
                    + (f"  notes={cls.notes}" if cls.notes else "") + "\n"
                )

        # insert into the open transaction (main loop decides when to commit);
        # dry-run just counts without writing
        if mode == "import" and commit and conn is not None:
            if to_insert:
                # sort by lien_id so the primary-key B-tree sees near-sequential
                # inserts within a batch (lien_id is a hash - unsorted it is
                # random, which multiplies InnoDB page splits)
                to_insert.sort(key=lambda r: r.lien_id)
                state["inserted"] += dbmod.insert_records(
                    conn, liens_table, to_insert, log_table=log_table, batch_size=ic.batch_size
                )
            if persist_rejects:
                rr = [
                    (
                        m.source_code, m.source_format, m.source_file, m.source_row_num,
                        d.value, " | ".join(b.reasons),
                        _raw_get(m.raw, "Full Name", "Company", "Business Name", "First Name",
                                 "Last Name")[:255] or None,
                        m.amount_raw or None, m.filing_date_raw or None, m.creditor or None,
                    )
                    for (m, b), d in zip(chunk, disp)
                    if d in _REJECT_DISPS or d in _HELD_DISPS
                ]
                if rr:
                    dbmod.insert_rejects(conn, ic.rejects_table, run_dir.name, rr)
        elif mode == "import":
            state["inserted"] += len(to_insert)  # would-insert, not written

    def _handle_unmapped(file, headers, sig):
        if sig not in seen_unmapped:
            seen_unmapped.add(sig)
            audit.unmapped_headers.append({"file": file, "headers": headers})
            log.warning("no %s adapter for headers in %s: %s", source_code, file, headers)

    executor = None
    next_progress = ic.progress_every
    workers = ic.workers
    if workers > 1:
        import multiprocessing as _mp

        if _mp.current_process().name != "MainProcess":
            workers = 1  # never spawn a nested pool from inside a worker
        elif getattr(__import__("sys").modules.get("__main__"), "__file__", None) is None:
            log.warning("workers>1 needs a script entry point (python -m lien_import); "
                        "running serial")
            workers = 1
    try:
        raw_batches = _batched_raw(iter_source_rows(input_path), ic.chunk_size, limit)

        if workers > 1:
            from concurrent.futures import ProcessPoolExecutor

            from ._worker import process_batch

            executor = ProcessPoolExecutor(max_workers=workers)
            built_iter = _parallel_built(
                executor, process_batch, raw_batches, workers,
                source_code, run_date.isoformat(), ic.min_filing_year,
            )
            log.info("processing with %d worker processes", workers)
        else:
            built_iter = (
                _serial_built(b, source_code, run_date, ic.min_filing_year, adapter_cache)
                for b in raw_batches
            )

        chunk_no = 0
        writing = mode == "import" and commit and conn is not None
        for built, unmapped in built_iter:
            for file, headers, sig in unmapped:
                _handle_unmapped(file, headers, sig)
            if built:
                process_chunk(built)
                state["examined"] += len(built)
                if writing and not first_import:
                    # the per-chunk DB existence check (same connection) already
                    # sees every prior chunk's INSERTs - committed or not - so
                    # only within-chunk de-dupe needs to stay in RAM
                    seen.clear()
            chunk_no += 1
            if writing and chunk_no % max(1, ic.commit_every_chunks) == 0:
                conn.commit()
            if state["examined"] >= next_progress:
                el = time.monotonic() - t0
                if writing:
                    log.info("progress: examined=%d inserted=%d %.0f rows/s",
                             state["examined"], state["inserted"],
                             state["examined"] / el if el else 0)
                else:  # preview / dry-run: nothing is written, so "inserted" is always 0
                    log.info("progress: examined=%d would_insert=%d (preview - nothing written) "
                             "%.0f rows/s", state["examined"], audit.would_insert,
                             state["examined"] / el if el else 0)
                next_progress += ic.progress_every
            if state["stopped"]:
                break

        if writing and not state["stopped"]:
            conn.commit()  # final partial commit window
    finally:
        if executor is not None:
            executor.shutdown(cancel_futures=True)
        rej_fh.close()
        held_fh.close()
        samp_fh.close()
        if conn is not None:
            if mode == "preview" or not commit:
                conn.rollback()
            conn.close()

    (run_dir / f"audit_{source_code}.json").write_text(audit.to_json(), encoding="utf-8")
    (run_dir / f"audit_{source_code}.txt").write_text(audit.render_text() + "\n", encoding="utf-8")

    committed = mode == "import" and commit and not state["stopped"]
    el = time.monotonic() - t0
    if mode == "import" and commit:
        log.info("done: examined=%d inserted=%d elapsed=%.1fs",
                 state["examined"], state["inserted"], el)
    else:
        log.info("done: examined=%d would_insert=%d (preview - nothing written) elapsed=%.1fs",
                 state["examined"], audit.would_insert, el)
    return RunResult(
        audit=audit, run_dir=run_dir, inserted=state["inserted"],
        committed=committed, examined=state["examined"], stopped_early=state["stopped"],
    )
