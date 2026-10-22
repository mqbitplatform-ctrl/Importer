"""Command-line interface.

    python -m lien_import discover --input PATH [--source ES|TN]
    python -m lien_import preview  --input PATH --source ES|TN [--check-existing] [--limit N]
    python -m lien_import import   --input PATH --source ES|TN [--commit] [--limit N]
    python -m lien_import verify   --source ES|TN
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from .config import load_config
from .logging_setup import setup_logging

SOURCES = ("ES", "TN")
DB_SOURCES = ("ES", "TN", "LN")


def _run_dir(base: Path, cmd: str, source: str | None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = f"{cmd}_{source}" if source else cmd
    return base / f"{stamp}_{tag}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lien_import", description=__doc__)
    p.add_argument("--config", default="config.json", help="path to config JSON (default: config.json)")
    p.add_argument("--output", help="override output directory")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="profile source CSV layouts (no writes)")
    d.add_argument("--input", required=True)
    d.add_argument("--source", choices=SOURCES)

    pv = sub.add_parser("preview", help="normalise + audit, never writes")
    pv.add_argument("--input", required=True)
    pv.add_argument("--source", required=True, choices=SOURCES)
    pv.add_argument("--check-existing", action="store_true", help="also check ids against the DB")
    pv.add_argument("--limit", type=int)

    im = sub.add_parser("import", help="insert rows (dry-run unless --commit)")
    im.add_argument("--input", required=True)
    im.add_argument("--source", required=True, choices=SOURCES)
    im.add_argument("--commit", action="store_true", help="persist (otherwise rolled back)")
    im.add_argument("--limit", type=int)
    im.add_argument("--force", action="store_true",
                    help="allow a commit larger than import.max_commit_rows")
    im.add_argument("--persist-rejects", action="store_true",
                    help="also write rejected/held rows to the rejects table")

    ai = sub.add_parser("auto-import",
                        help="preview (default) or import EVERY file in the inbox folder")
    ai.add_argument("--inbox", help="folder to read (default: paths.inbox_dir in config.json)")
    ai.add_argument("--commit", action="store_true",
                    help="import, record and move each file (otherwise preview only)")
    ai.add_argument("--open-inbox", action="store_true",
                    help="just create + open the inbox folder in Explorer, then stop")

    for sp in (pv, im, ai):
        sp.add_argument("--allow-duplicates", action="store_true",
                        help="keep a lien repeated across files/rows as separate rows "
                             "(same as import.allow_duplicates=true in config.json)")

    sub.add_parser("db-check", help="test the database connection in config.json")
    sd = sub.add_parser("setup-local-db",
                        help="create a local practice database (127.0.0.1 only) with all tables")
    sd.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    vf = sub.add_parser("verify", help="reconcile liens row counts vs the last audit")
    vf.add_argument("--source", required=True, choices=DB_SOURCES)

    an = sub.add_parser("analyze", help="statistical + data-quality report (no writes)")
    an.add_argument("--input", help="source path for file-mode analysis")
    an.add_argument("--source", choices=DB_SOURCES)
    an.add_argument("--db", action="store_true", help="analyse the liens table instead of files")
    an.add_argument("--limit", type=int)

    da = sub.add_parser("deliverable", help="generate a handoff deliverable document")
    da.add_argument("kind", choices=["A", "C"], help="A = Discovery Summary, C = Preview/Audit Results")
    da.add_argument("--input", required=True)
    da.add_argument("--source", required=True, choices=SOURCES)
    da.add_argument("--limit", type=int)

    fa = sub.add_parser("fat-analyze", help="count liens matching the Free America Tax criteria (read-only)")
    fa.add_argument("--source", choices=DB_SOURCES, help="restrict to one source (default: all)")

    fp = sub.add_parser("fat-pull", help="select + assign liens for a Free America Tax job")
    fp.add_argument("--job", required=True, help="label for this pull's CSV (e.g. FAT-2026-08)")
    fp.add_argument("--commit", action="store_true",
                    help="record the assignments in liens_custom_data (otherwise preview only)")
    fp.add_argument("--limit", type=int, help="how many liens to pull (past pulls: 10,000-14,000)")
    fp.add_argument("--start-case-id", type=int,
                    help="first FREEAMTAX Case ID to use (from Logics); required with --commit")

    sub.add_parser("fat-status", help="show past Free America Tax pulls")

    return p


def _friendly_db_error(exc) -> str:
    """Turn a pymysql error into a plain-language fix (config.json wording)."""
    from . import db as dbmod

    return dbmod.friendly_connect_error(exc, where="config.json")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - top-level friendly handler
        mod = type(exc).__module__ or ""
        if mod.startswith("pymysql"):
            print("\n" + _friendly_db_error(exc), file=sys.stderr)
            return 1
        raise


def _dispatch(args) -> int:
    cfg = load_config(args.config if Path(args.config).is_file() else None)
    if getattr(args, "allow_duplicates", False):
        cfg.imports.allow_duplicates = True
    base_out =Path(args.output) if args.output else cfg.output_dir
    level = logging.DEBUG if args.verbose else logging.INFO

    if args.command == "discover":
        run_dir = _run_dir(base_out, "discover", getattr(args, "source", None))
        setup_logging(run_dir, level)
        from .discovery import discover, render_text

        report = discover(args.source, args.input)
        (run_dir / "discovery.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        text = render_text(report)
        (run_dir / "discovery.txt").write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"\nwritten to {run_dir}")
        return 0

    if args.command == "setup-local-db":
        return _cmd_setup_local_db(cfg, level, args.yes)

    if args.command == "auto-import":
        from .batch import run_batch

        inbox = Path(args.inbox) if args.inbox else cfg.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)
        if args.open_inbox:
            print(f"Inbox folder: {inbox.resolve()}")
            if hasattr(os, "startfile"):
                os.startfile(inbox.resolve())  # Windows Explorer
            return 0
        run_dir = _run_dir(base_out, "auto-import", None)
        setup_logging(run_dir, level)
        result = run_batch(
            cfg, commit=args.commit, inbox=inbox, run_dir=run_dir,
            progress=lambda i, n, msg: print(f"[{i}/{n}] {msg}", flush=True),
        )
        if not result.files:
            print(f"The inbox is empty: {inbox.resolve()}\n"
                  "Drop CSV/ZIP files or whole folders there and run again.")
            return 3  # lets lien-import.bat skip the "type IMPORT" step
        print()
        print(result.render())
        bad = result.counts().get("failed", 0) + result.counts().get("stopped", 0)
        return 2 if bad else 0

    if args.command == "db-check":
        setup_logging(None, level)
        from . import db as dbmod

        db = cfg.database
        if not db.is_configured:
            print("config.json is not filled in yet - replace the REPLACE_ME values "
                  "in the \"database\" section.", file=sys.stderr)
            return 1
        print(f"connecting to  {db.user}@{db.host}:{db.port}  database '{db.name}' ...")
        conn = dbmod.connect(cfg)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DATABASE(), VERSION()")
                name, ver = cur.fetchone()
                cur.execute("SHOW TABLES LIKE %s", [db.liens_table])
                has_liens = cur.fetchone() is not None
                n = None
                if has_liens:
                    cur.execute(f"SELECT COUNT(*) FROM `{db.liens_table}`")
                    n = cur.fetchone()[0]
        finally:
            conn.close()
        print(f"OK - connected to '{name}' on {ver}")
        if has_liens:
            print(f"OK - table '{db.liens_table}' found ({n:,} rows)")
        else:
            print(f"WARNING - table '{db.liens_table}' NOT found in this database. "
                  "Check the \"name\" / \"liens_table\" settings with the DBA.")
            return 2
        return 0

    if args.command == "verify":
        setup_logging(None, level)
        from . import db as dbmod

        conn = dbmod.connect(cfg)
        try:
            n = dbmod.count_by_source(conn, cfg.database.liens_table, args.source)
        finally:
            conn.close()
        expected = _last_audit_would_insert(base_out, args.source)
        print(f"{cfg.database.liens_table}: lien_source={args.source} -> {n:,} rows")
        if expected is not None:
            match = "OK" if expected == n else "MISMATCH"
            print(f"last audit would_insert: {expected:,}   [{match}]")
            return 0 if expected == n else 2
        print("(no prior audit_%s.json found under %s to reconcile against)" % (args.source, base_out))
        return 0

    if args.command == "analyze":
        return _cmd_analyze(args, cfg, base_out, level)

    if args.command == "deliverable":
        return _cmd_deliverable(args, cfg, base_out, level)

    if args.command in ("fat-analyze", "fat-pull", "fat-status"):
        return _cmd_fat(args, cfg, base_out, level)

    # preview / import
    run_dir = _run_dir(base_out, args.command, args.source)
    setup_logging(run_dir, level)
    from .pipeline import run

    result = run(
        source_code=args.source,
        input_path=args.input,
        cfg=cfg,
        run_dir=run_dir,
        mode=args.command,
        limit=args.limit,
        check_existing=getattr(args, "check_existing", False),
        commit=getattr(args, "commit", False),
        force=getattr(args, "force", False),
        persist_rejects=getattr(args, "persist_rejects", False),
    )
    print(result.audit.render_text())
    print(f"\nartifacts: {run_dir}")
    if args.command == "import":
        if result.committed:
            print(f"insert: {result.inserted:,} rows COMMITTED")
        elif result.stopped_early:
            print(f"insert: {result.inserted:,} rows COMMITTED, then stopped at "
                  f"max_commit_rows - re-run with --force to finish")
        else:
            print(f"would insert: {result.audit.would_insert:,} rows  [DRY-RUN, nothing written]")
    if not result.audit.reconciles():
        print("WARNING: audit did not reconcile", file=sys.stderr)
        return 2
    return 0


def _last_audit_would_insert(base_out: Path, source: str) -> int | None:
    """Newest audit_<source>.json under base_out -> combined would_insert."""
    if not base_out.is_dir():
        return None
    cands = sorted(base_out.glob(f"*/audit_{source}.json"))
    if not cands:
        return None
    try:
        data = json.loads(cands[-1].read_text(encoding="utf-8"))
        return int(data["combined"]["section12"]["would_insert"])
    except (json.JSONDecodeError, KeyError, OSError):
        return None


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
_SQL_FILES = ("liens_reference.sql", "liens_custom_data_reference.sql",
              "lien_import_log.sql", "lien_import_rejects.sql")


def _statements(sql_text: str):
    import re

    no_comments = re.sub(r"(?m)^\s*--.*$", "", sql_text)
    for stmt in no_comments.split(";"):
        if stmt.strip():
            yield stmt


def _cmd_setup_local_db(cfg, level, assume_yes: bool) -> int:
    import pymysql

    setup_logging(None, level)
    db = cfg.database
    if db.host not in _LOCAL_HOSTS:
        print(f"error: setup-local-db only runs against a local server, but host is "
              f"'{db.host}'.\n  This creates a REFERENCE copy of the liens table - never "
              f"do that on a shared / production server.", file=sys.stderr)
        return 1
    if not db.name or db.name == "REPLACE_ME":
        print('error: set "name" in config.json to the practice database name first.',
              file=sys.stderr)
        return 1

    sql_dir = Path(__file__).resolve().parents[1] / "sql"
    if not assume_yes:
        print(f"This will create database '{db.name}' on {db.host} (if absent) and the")
        print("tables: liens + liens_custom_data (reference copies), lien_import_log,")
        print("lien_import_rejects.  Existing tables are left as-is.")
        ans = input("Type YES to continue: ").strip()
        if ans != "YES":
            print("Cancelled.")
            return 1

    conn = pymysql.connect(host=db.host, port=db.port, user=db.user,
                           password=db.password, charset=db.charset, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db.name}` CHARACTER SET utf8mb4")
            cur.execute(f"USE `{db.name}`")
            for fname in _SQL_FILES:
                text = (sql_dir / fname).read_text(encoding="utf-8")
                if fname == "liens_reference.sql":
                    text = text.replace("IF NOT EXISTS liens",
                                        f"IF NOT EXISTS `{db.liens_table}`")
                for stmt in _statements(text):
                    cur.execute(stmt)
            cur.execute("SHOW TABLES")
            tables = sorted(r[0] for r in cur.fetchall())
    finally:
        conn.close()
    print(f"OK - database '{db.name}' ready with tables: {', '.join(tables)}")
    print("Run menu option 9 (db-check) to confirm, then you can import into it.")
    return 0


def _cmd_analyze(args, cfg, base_out, level) -> int:
    from . import analytics

    if args.db:
        run_dir = _run_dir(base_out, "analyze-db", args.source)
        setup_logging(run_dir, level)
        from . import db as dbmod

        conn = dbmod.connect(cfg)
        try:
            report = analytics.analyze_db(conn, cfg.database.liens_table, args.source)
        finally:
            conn.close()
    else:
        if not args.input or not args.source or args.source == "LN":
            print("error: file-mode analyze needs --input and --source ES|TN", file=sys.stderr)
            return 1
        run_dir = _run_dir(base_out, "analyze", args.source)
        setup_logging(run_dir, level)
        report = analytics.analyze_files(args.source, args.input, cfg, limit=args.limit)

    text = analytics.render_text(report)
    (run_dir / "analysis.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (run_dir / "analysis.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nartifacts: {run_dir}")
    return 0


def _cmd_deliverable(args, cfg, base_out, level) -> int:
    from . import deliverables

    run_dir = _run_dir(base_out, f"deliverable-{args.kind}", args.source)
    setup_logging(run_dir, level)
    if args.kind == "A":
        md = deliverables.discovery_summary(args.source, args.input)
        name = f"Deliverable-A_Discovery-Summary_{args.source}.md"
    else:
        md = deliverables.preview_audit_results(
            args.source, args.input, cfg, limit=args.limit, work_dir=run_dir
        )
        name = f"Deliverable-C_Preview-Audit_{args.source}.md"
    path = run_dir / name
    path.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nwritten: {path}")
    return 0


def _cmd_fat(args, cfg, base_out, level) -> int:
    from . import db as dbmod
    from .fat import pull as fatpull

    conn = dbmod.connect(cfg)
    try:
        if args.command == "fat-analyze":
            setup_logging(None, level)
            report = fatpull.analyze(conn, cfg, source=args.source)
            print(fatpull.render_analysis(report))
            return 0
        if args.command == "fat-status":
            setup_logging(None, level)
            for row in fatpull.status(conn, cfg):
                print(row)
            return 0
        # fat-pull
        run_dir = _run_dir(base_out, "fat-pull", args.job)
        setup_logging(run_dir, level)
        result = fatpull.run_pull(
            conn, cfg, job=args.job, run_dir=run_dir,
            commit=args.commit, limit=args.limit, start_case_id=args.start_case_id,
        )
        print(result.render())
        print(f"\nartifacts: {run_dir}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
