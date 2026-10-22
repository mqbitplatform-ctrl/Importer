"""MySQL access: existence checks, optional import-log table, batched insert.

The ``liens`` table itself is never altered. ``lien_import_log`` is a *new*
side table (opt-in via config) that records what was inserted so re-runs are
idempotent and every row is traceable to its source file/row. Creating it is
subject to client sign-off (handoff section 14); set
``import.use_import_log_table = false`` to rely solely on the
``(lien_source, lien_id)`` primary key of ``liens`` instead.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional, Sequence

import pymysql

from .config import AppConfig
from .models import COLUMN_ORDER, LienRecord

log = logging.getLogger("lien_import.db")


def friendly_connect_error(exc: Exception, *, where: str = "config.json") -> str:
    """Turn a pymysql connection/query error into a plain-language fix.

    *where* names the settings the user should go fix - "config.json" for the
    CLI, "the Database panel above" for the GUI - so one message serves both.
    Shared by the CLI's top-level error handler and the GUI's "Test
    Connection" / run buttons, so both surfaces give the same guidance.
    """
    args = getattr(exc, "args", ())
    code = args[0] if args else None
    detail = args[1] if len(args) > 1 else str(exc)
    if code == 1049:  # Unknown database
        return (
            f"There is no database with that name on this server ({detail}).\n"
            f"  The tool uses the database/schema name from {where} EXACTLY as\n"
            "  typed - it never adds or changes anything.\n"
            "  Fix one of these:\n"
            "  * Wrong value: it must be the DATABASE that holds the liens table,\n"
            "    not the login. Copy the exact name from the hosting control panel\n"
            "    (Hostinger: hPanel > Databases > the 'Database' column - it may\n"
            "    look like u1234567_line_item).\n"
            "  * Wrong server: for a hosted DB, the host is usually NOT 127.0.0.1.\n"
            "  * The database just isn't created yet - ask the DBA to create it."
        )
    if code in (1045, 1044):  # access denied
        return f"Login was rejected ({detail}).\n  Check the username and password in {where}."
    if code in (2003, 2002, 2005):  # can't reach server
        return (
            f"Could not reach the database server ({detail}).\n"
            f"  Check the host (and port) in {where}, the VPN, and that the server is running."
        )
    return f"Database error {code}: {detail}\n  Check the settings in {where}."


def connect(cfg: AppConfig):
    db = cfg.database
    if not db.is_configured:
        raise RuntimeError(
            "Database is not configured. Fill config.json (or set LIEN_DB_* env vars)."
        )
    conn = pymysql.connect(
        host=db.host,
        port=db.port,
        user=db.user,
        password=db.password,
        database=db.name,
        charset=db.charset,
        autocommit=False,
        cursorclass=pymysql.cursors.Cursor,
    )
    log.info("connected to mysql %s@%s/%s", db.user, db.host, db.name)
    return conn


def _chunks(seq: Sequence, size: int) -> Iterable[Sequence]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def fetch_existing_liens_ids(
    conn, table: str, lien_source: str, ids: Sequence[str], batch: int = 1000
) -> set[str]:
    """Return the subset of *ids* already present in ``liens`` for this source."""
    found: set[str] = set()
    if not ids:
        return found
    with conn.cursor() as cur:
        for chunk in _chunks(list(ids), batch):
            placeholders = ",".join(["%s"] * len(chunk))
            cur.execute(
                f"SELECT lien_id FROM `{table}` "
                f"WHERE lien_source = %s AND lien_id IN ({placeholders})",
                [lien_source, *chunk],
            )
            found.update(r[0] for r in cur.fetchall())
    return found


def ensure_import_log_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
              lien_source       CHAR(2)      NOT NULL,
              lien_id           VARCHAR(15)  NOT NULL,
              natural_key_sha1  CHAR(40)     NOT NULL,
              source_format     VARCHAR(40)  NOT NULL,
              source_file       VARCHAR(255) NOT NULL,
              source_row_num    INT          NOT NULL,
              source_ref        VARCHAR(80)  NULL,
              imported_at       DATETIME     NOT NULL,
              PRIMARY KEY (lien_source, lien_id),
              KEY ix_import_log_sha1 (natural_key_sha1)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    conn.commit()


def ensure_rejects_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
              id              BIGINT       NOT NULL AUTO_INCREMENT,
              run_id          VARCHAR(40)  NOT NULL,
              lien_source     CHAR(2)      NOT NULL,
              source_format   VARCHAR(40)  NOT NULL,
              source_file     VARCHAR(255) NOT NULL,
              source_row_num  INT          NOT NULL,
              disposition     VARCHAR(24)  NOT NULL,
              reasons         TEXT         NOT NULL,
              name_or_company VARCHAR(255) NULL,
              amount_raw      VARCHAR(40)  NULL,
              filing_date_raw VARCHAR(40)  NULL,
              creditor        VARCHAR(120) NULL,
              recorded_at     DATETIME     NOT NULL,
              PRIMARY KEY (id),
              KEY ix_rejects_run (run_id),
              KEY ix_rejects_disp (disposition)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    conn.commit()


def insert_rejects(conn, table: str, run_id: str, rows: Sequence[tuple]) -> int:
    """rows: (lien_source, source_format, source_file, source_row_num, disposition,
    reasons, name_or_company, amount_raw, filing_date_raw, creditor)"""
    if not rows:
        return 0
    now = datetime.now()
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO `{table}` (run_id, lien_source, source_format, source_file, "
            "source_row_num, disposition, reasons, name_or_company, amount_raw, "
            "filing_date_raw, creditor, recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(run_id, *r, now) for r in rows],
        )
        return cur.rowcount


def fetch_log_sha1(
    conn, table: str, lien_source: str, ids: Sequence[str], batch: int = 1000
) -> dict[str, str]:
    """Map lien_id -> natural_key_sha1 from the import log (for collision detection)."""
    out: dict[str, str] = {}
    if not ids:
        return out
    with conn.cursor() as cur:
        for chunk in _chunks(list(ids), batch):
            placeholders = ",".join(["%s"] * len(chunk))
            cur.execute(
                f"SELECT lien_id, natural_key_sha1 FROM `{table}` "
                f"WHERE lien_source = %s AND lien_id IN ({placeholders})",
                [lien_source, *chunk],
            )
            out.update({r[0]: r[1] for r in cur.fetchall()})
    return out


def _row_values(rec: LienRecord) -> list:
    return [getattr(rec, col) for col in COLUMN_ORDER]


def insert_records(
    conn,
    liens_table: str,
    records: Sequence[LienRecord],
    *,
    log_table: Optional[str] = None,
    batch_size: int = 500,
) -> int:
    """Insert *records* into ``liens`` (+ import log if given). Caller controls
    commit/rollback. Returns the number of rows inserted."""
    if not records:
        return 0

    cols = ",".join(f"`{c}`" for c in COLUMN_ORDER)
    placeholders = ",".join(["%s"] * len(COLUMN_ORDER))
    liens_sql = f"INSERT INTO `{liens_table}` ({cols}) VALUES ({placeholders})"

    log_sql = None
    now = datetime.now()
    if log_table:
        log_sql = (
            f"INSERT INTO `{log_table}` "
            "(lien_source, lien_id, natural_key_sha1, source_format, source_file, "
            "source_row_num, source_ref, imported_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
        )

    inserted = 0
    with conn.cursor() as cur:
        for chunk in _chunks(records, batch_size):
            cur.executemany(liens_sql, [_row_values(r) for r in chunk])
            inserted += cur.rowcount
            if log_sql:
                cur.executemany(
                    log_sql,
                    [
                        (
                            r.lien_source,
                            r.lien_id,
                            r.natural_key_sha1,
                            getattr(r, "_source_format", ""),
                            getattr(r, "_source_file", ""),
                            getattr(r, "_source_row_num", 0),
                            getattr(r, "_source_ref", None),
                            now,
                        )
                        for r in chunk
                    ],
                )
    return inserted


def count_by_source(conn, table: str, lien_source: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM `{table}` WHERE lien_source = %s", [lien_source]
        )
        return int(cur.fetchone()[0])


def table_exists(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE %s", [table])
        return cur.fetchone() is not None
