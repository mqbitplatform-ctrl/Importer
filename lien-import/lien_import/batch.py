"""Auto-import ("hot folder"): import everything dropped in the inbox.

The operator drops files or whole folders - any mix of ATT/ESS and TNU, CSV or
ZIP - into ``paths.inbox_dir``. Nobody picks a source or a file one by one:

  * the source (ES / TN) and layout are detected from each file's header;
  * ``preview`` (the default) reads everything, reports per-source totals with
    cross-file duplicates counted correctly, and changes nothing;
  * ``commit`` imports file by file, records each file in the file ledger
    (``import.file_ledger_table``, keyed by the SHA-256 of its content) and
    moves it to ``processed_dir/<date>/...``; a file that can't be read or
    imported goes to ``failed_dir/<date>/...`` with a ``.reason.txt`` and the
    run carries on with the next file.

Duplicates are prevented three ways: (1) a file whose content was already
imported is skipped even if renamed or dropped again; (2) the lien-level id +
DB check stops the same lien in two different files being inserted twice;
(3) imported files leave the inbox.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import db as dbmod
from .adapters import REGISTRY, find_adapter
from .config import AppConfig

log = logging.getLogger("lien_import.batch")

SOURCES = ("ES", "TN")
_HASH_CHUNK = 1024 * 1024


# ------------------------------------------------------------------ helpers

def scan_inbox(inbox: Path) -> list[Path]:
    """Every *.csv / *.zip under *inbox*, in a stable order."""
    if not inbox.is_dir():
        return []
    return sorted(
        p for p in inbox.rglob("*")
        if p.is_file() and p.suffix.lower() in (".csv", ".zip")
    )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _header_from_bytes(raw: bytes) -> list[str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text else ""
    return next(csv.reader(io.StringIO(first)), [])


def _match(header: list[str]) -> Optional[tuple[str, str]]:
    for src in SOURCES:
        a = find_adapter(src, header, REGISTRY)
        if a is not None:
            return src, a.format_name
    return None


def detect_source(path: Path) -> tuple[Optional[str], Optional[str], str]:
    """Return ``(source_code, format_name, problem)``. For a ZIP every CSV
    inside must be the same source; *problem* explains why not."""
    try:
        if path.suffix.lower() == ".zip":
            found = set()
            with zipfile.ZipFile(path) as zf:
                members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
                if not members:
                    return None, None, "ZIP contains no CSV files"
                for m in members:
                    with zf.open(m) as fh:
                        hit = _match(_header_from_bytes(fh.read(65536)))
                    if hit is None:
                        return None, None, f"unrecognised layout inside ZIP: {m}"
                    found.add(hit)
            sources = {s for s, _ in found}
            if len(sources) > 1:
                return None, None, f"ZIP mixes sources {sorted(sources)} - split it into separate ZIPs"
            src = sources.pop()
            fmts = sorted({f for _, f in found})
            return src, "+".join(fmts), ""
        with path.open("rb") as fh:
            header = _header_from_bytes(fh.read(65536))
        hit = _match(header)
        if hit is None:
            return None, None, f"unrecognised column layout: {header[:8]}"
        return hit[0], hit[1], ""
    except (OSError, zipfile.BadZipFile, StopIteration) as exc:
        return None, None, f"could not read file: {exc}"


def _move(src: Path, inbox: Path, dest_root: Path, stamp: str) -> Path:
    try:
        rel = src.relative_to(inbox)
    except ValueError:
        rel = Path(src.name)
    target = dest_root / stamp / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while target.exists():  # never overwrite an earlier file of the same name
        target = target.with_name(f"{target.stem}__{n}{target.suffix}")
        n += 1
    shutil.move(str(src), str(target))
    return target


def _prune_empty_dirs(inbox: Path) -> None:
    if not inbox.is_dir():
        return
    for d in sorted((p for p in inbox.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()  # only succeeds if empty
        except OSError:
            pass


# ------------------------------------------------------------------- ledger

def ensure_ledger_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
              file_sha256     CHAR(64)     NOT NULL,
              file_name       VARCHAR(255) NOT NULL,
              lien_source     CHAR(2)      NOT NULL,
              source_format   VARCHAR(60)  NOT NULL,
              rows_examined   INT          NOT NULL,
              rows_inserted   INT          NOT NULL,
              rows_duplicate  INT          NOT NULL,
              rows_rejected   INT          NOT NULL,
              rows_held       INT          NOT NULL,
              imported_at     DATETIME     NOT NULL,
              PRIMARY KEY (file_sha256)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    conn.commit()


def ledger_lookup(conn, table: str, sha: str) -> Optional[tuple]:
    """``(file_name, imported_at)`` if this exact content was imported before."""
    if not dbmod.table_exists(conn, table):
        return None
    with conn.cursor() as cur:
        cur.execute(f"SELECT file_name, imported_at FROM `{table}` WHERE file_sha256 = %s", [sha])
        return cur.fetchone()


def ledger_record(conn, table: str, *, sha, name, source, fmt, audit, inserted) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO `{table}` (file_sha256, file_name, lien_source, source_format, "
            "rows_examined, rows_inserted, rows_duplicate, rows_rejected, rows_held, imported_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [sha, name[:255], source, fmt[:60], audit.examined, inserted,
             audit.duplicates_within_source,
             audit.rejected_missing + audit.rejected_invalid,
             audit.held_trust_estate + audit.held_ambiguous,
             datetime.now().replace(microsecond=0)],
        )
    conn.commit()


# ------------------------------------------------------------------ results

@dataclass
class FileOutcome:
    path: Path
    name: str
    status: str  # previewed | imported | already_imported | unrecognised | failed | stopped
    source: Optional[str] = None
    fmt: Optional[str] = None
    sha256: str = ""
    examined: int = 0
    would_insert: int = 0
    inserted: int = 0
    duplicates: int = 0
    rejected: int = 0
    held: int = 0
    message: str = ""
    moved_to: Optional[Path] = None


@dataclass
class BatchResult:
    mode: str
    run_dir: Path
    files: list[FileOutcome] = field(default_factory=list)
    source_totals: dict = field(default_factory=dict)  # preview: source -> section12 dict

    def counts(self) -> dict:
        out: dict[str, int] = defaultdict(int)
        for f in self.files:
            out[f.status] += 1
        return dict(out)

    def render(self) -> str:
        lines = [f"AUTO-IMPORT ({self.mode.upper()})  - {len(self.files)} file(s)", "=" * 72]
        for f in self.files:
            src = f"{f.source or '--'}/{f.fmt or '--'}"
            if f.status == "imported":
                detail = (f"{f.examined:>9,} rows  {f.inserted:>9,} inserted  "
                          f"{f.duplicates:>9,} dup  {f.rejected:>6,} rej  {f.held:>6,} held")
            else:
                detail = f.message
            lines.append(f"  {f.status:<16} {src:<18} {f.name}")
            lines.append(f"      {detail}")
        if self.source_totals:
            lines += ["", "Totals per source (duplicates across files counted once):"]
            for src, s in self.source_totals.items():
                lines.append(
                    f"  {src}: examined {s['total_examined']:,}  would insert {s['would_insert']:,}  "
                    f"duplicates {s['duplicates_within_source']:,}  "
                    f"rejected {s['missing_required_values'] + s['rejected_other']:,}  "
                    f"held {s['trust_estate_held'] + s['ambiguous_entity_held']:,}"
                )
        lines += ["", f"summary: {self.counts()}", f"report:  {self.run_dir}"]
        return "\n".join(lines)


def _write_report(result: BatchResult) -> None:
    result.run_dir.mkdir(parents=True, exist_ok=True)
    with (result.run_dir / "auto_import_files.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "status", "source", "format", "rows_examined", "would_insert",
                    "inserted", "duplicates", "rejected", "held", "sha256", "moved_to", "message"])
        for f in result.files:
            w.writerow([str(f.path), f.status, f.source, f.fmt, f.examined, f.would_insert,
                        f.inserted, f.duplicates, f.rejected, f.held, f.sha256,
                        str(f.moved_to or ""), f.message])
    (result.run_dir / "auto_import_summary.txt").write_text(result.render() + "\n", encoding="utf-8")


# --------------------------------------------------------------------- run

ProgressFn = Callable[[int, int, str], None]


def run_batch(
    cfg: AppConfig,
    *,
    commit: bool = False,
    inbox: Optional[Path] = None,
    run_dir: Optional[Path] = None,
    progress: Optional[ProgressFn] = None,
) -> BatchResult:
    """Preview (default) or import every file in the inbox."""
    from .pipeline import run as run_pipeline

    inbox = Path(inbox or cfg.inbox_dir)
    stamp = datetime.now().strftime("%Y-%m-%d")
    run_dir = run_dir or (cfg.output_dir / f"{datetime.now():%Y%m%d-%H%M%S}_auto-import")
    result = BatchResult(mode="commit" if commit else "preview", run_dir=run_dir)
    files = scan_inbox(inbox)
    if not files:
        _write_report(result)
        return result

    if commit and not cfg.database.is_configured:
        raise RuntimeError("Importing needs the database settings - fill them in first.")

    conn = dbmod.connect(cfg) if cfg.database.is_configured else None
    ledger = cfg.imports.file_ledger_table
    try:
        if commit:
            ensure_ledger_table(conn, ledger)

        # 1) classify every file
        outcomes: list[FileOutcome] = []
        for i, path in enumerate(files, 1):
            if progress:
                progress(i, len(files), f"checking {path.name}")
            o = FileOutcome(path=path, name=str(path.relative_to(inbox)), status="")
            o.sha256 = file_sha256(path)
            prior = ledger_lookup(conn, ledger, o.sha256) if conn is not None else None
            if prior is not None:
                o.status = "already_imported"
                o.message = f"same content imported before as '{prior[0]}' on {prior[1]}"
            else:
                o.source, o.fmt, problem = detect_source(path)
                if o.source is None:
                    o.status, o.message = "unrecognised", problem
            outcomes.append(o)

        todo = [o for o in outcomes if not o.status]

        if not commit:
            # 2a) PREVIEW: one pipeline pass per source over all its files, so a
            #     lien repeated across files is counted once, like a real import
            for src in SOURCES:
                group = [o for o in todo if o.source == src]
                if not group:
                    continue
                if progress:
                    progress(len(files), len(files), f"previewing {len(group)} {src} file(s)")
                res = run_pipeline(
                    source_code=src, input_path=[str(o.path) for o in group], cfg=cfg,
                    run_dir=run_dir / f"preview_{src}", mode="preview",
                    check_existing=conn is not None,
                )
                result.source_totals[src] = res.audit.to_dict()["combined"]["section12"]
                for o in group:
                    o.status = "previewed"
                    o.message = f"counted in the {src} totals below"
        else:
            # 2b) IMPORT: file by file - each file is imported, recorded and moved
            #     on its own, so one bad file never blocks the rest
            for i, o in enumerate(todo, 1):
                if progress:
                    progress(i, len(todo), f"importing {o.name}")
                file_run = run_dir / f"{i:03d}_{o.path.stem}"
                try:
                    res = run_pipeline(
                        source_code=o.source, input_path=str(o.path), cfg=cfg,
                        run_dir=file_run, mode="import", commit=True, force=True,
                    )
                except Exception as exc:  # noqa: BLE001 - recorded, run continues
                    o.status = "failed"
                    o.message = (dbmod.friendly_connect_error(exc)
                                 if type(exc).__module__.startswith("pymysql") else str(exc))
                    continue
                a = res.audit
                o.examined, o.inserted = a.examined, res.inserted
                o.would_insert = a.would_insert
                o.duplicates = a.duplicates_within_source
                o.rejected = a.rejected_missing + a.rejected_invalid
                o.held = a.held_trust_estate + a.held_ambiguous
                if res.stopped_early or not res.committed:
                    o.status = "stopped"
                    o.message = "import did not finish - re-run auto-import to continue (safe)"
                    continue
                ledger_record(conn, ledger, sha=o.sha256, name=o.name, source=o.source,
                              fmt=o.fmt, audit=a, inserted=res.inserted)
                o.status = "imported"
                o.message = f"report: {file_run}"

            # 3) move files out of the inbox
            for o in outcomes:
                try:
                    if o.status in ("imported", "already_imported"):
                        o.moved_to = _move(o.path, inbox, Path(cfg.processed_dir), stamp)
                    elif o.status in ("unrecognised", "failed"):
                        o.moved_to = _move(o.path, inbox, Path(cfg.failed_dir), stamp)
                        o.moved_to.with_name(o.moved_to.name + ".reason.txt").write_text(
                            f"{o.status}: {o.message}\n", encoding="utf-8")
                except OSError as exc:
                    o.message += f" (could not move file: {exc})"
            _prune_empty_dirs(inbox)

        result.files = outcomes
    finally:
        if conn is not None:
            conn.close()

    _write_report(result)
    return result
