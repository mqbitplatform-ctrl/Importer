"""Configuration loading: JSON file + environment-variable overrides.

Environment overrides (take precedence over the JSON file):
    LIEN_DB_HOST, LIEN_DB_PORT, LIEN_DB_NAME, LIEN_DB_USER,
    LIEN_DB_PASSWORD, LIEN_DB_CHARSET, LIEN_LIENS_TABLE
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DbConfig:
    host: str = ""
    port: int = 3306
    name: str = ""
    user: str = ""
    password: str = ""
    charset: str = "utf8mb4"
    liens_table: str = "liens"

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.host != "REPLACE_ME" and self.name and self.user)


@dataclass
class ImportConfig:
    batch_size: int = 2000          # executemany() rows per INSERT round-trip
    chunk_size: int = 10_000        # source rows processed + de-duped (and PK-sorted) per pass
    commit_every_chunks: int = 2    # DB commit cadence (also the crash-resume granularity)
    workers: int = 1                # >1 = parse/normalise rows across N processes
    progress_every: int = 50_000    # log a progress line every N examined rows
    use_import_log_table: bool = True
    import_log_table: str = "lien_import_log"
    rejects_table: str = "lien_import_rejects"
    file_ledger_table: str = "lien_import_files"  # one row per source file imported (auto-import)
    min_filing_year: int = 1980
    max_commit_rows: int = 250_000  # require --force above this in one run
    # True = keep every source row, even the same lien repeated across files:
    # the lien_id then also covers the CSV file name + row number (see
    # pipeline._row_scoped_key). Re-importing the SAME file still adds nothing.
    allow_duplicates: bool = False


@dataclass
class FatConfig:
    """Free America Tax lien-pull selection (handoff section 16)."""

    user_index: str = "61379"
    filing_type: str = "F"
    entity_type: str = "I"
    min_amount: str = "5000"
    sources: list[str] = field(default_factory=list)  # empty = all lien_source values
    # the EXISTING zm_dba table the current FAT process already uses
    assignment_table: str = "liens_custom_data"
    case_id_name: str = "FREEAMTAX Case ID"  # liens_custom_data.lcdata_name for FAT


@dataclass
class AppConfig:
    database: DbConfig = field(default_factory=DbConfig)
    imports: ImportConfig = field(default_factory=ImportConfig)
    fat: FatConfig = field(default_factory=FatConfig)
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    # auto-import ("hot folder"): drop files in inbox; imported -> processed; bad -> failed
    inbox_dir: Path = field(default_factory=lambda: Path("./lien-data/inbox"))
    processed_dir: Path = field(default_factory=lambda: Path("./lien-data/processed"))
    failed_dir: Path = field(default_factory=lambda: Path("./lien-data/failed"))


def _apply_env(db: DbConfig) -> None:
    mapping = {
        "LIEN_DB_HOST": "host",
        "LIEN_DB_NAME": "name",
        "LIEN_DB_USER": "user",
        "LIEN_DB_PASSWORD": "password",
        "LIEN_DB_CHARSET": "charset",
        "LIEN_LIENS_TABLE": "liens_table",
    }
    for env_key, attr in mapping.items():
        val = os.environ.get(env_key)
        if val:
            setattr(db, attr, val)
    port = os.environ.get("LIEN_DB_PORT")
    if port:
        db.port = int(port)


def load_config(path: str | os.PathLike[str] | None) -> AppConfig:
    raw: dict[str, Any] = {}
    if path:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))

    db_raw = raw.get("database", {})
    db = DbConfig(
        host=db_raw.get("host", ""),
        port=int(db_raw.get("port", 3306)),
        name=db_raw.get("name", ""),
        user=db_raw.get("user", ""),
        password=db_raw.get("password", ""),
        charset=db_raw.get("charset", "utf8mb4"),
        liens_table=db_raw.get("liens_table", "liens"),
    )
    _apply_env(db)

    imp_raw = raw.get("import", {})
    imports = ImportConfig(
        batch_size=int(imp_raw.get("batch_size", 2000)),
        chunk_size=int(imp_raw.get("chunk_size", 10_000)),
        commit_every_chunks=int(imp_raw.get("commit_every_chunks", 2)),
        workers=int(imp_raw.get("workers", 1)),
        progress_every=int(imp_raw.get("progress_every", 50_000)),
        use_import_log_table=bool(imp_raw.get("use_import_log_table", True)),
        import_log_table=imp_raw.get("import_log_table", "lien_import_log"),
        rejects_table=imp_raw.get("rejects_table", "lien_import_rejects"),
        file_ledger_table=imp_raw.get("file_ledger_table", "lien_import_files"),
        min_filing_year=int(imp_raw.get("min_filing_year", 1980)),
        max_commit_rows=int(imp_raw.get("max_commit_rows", 250_000)),
        allow_duplicates=bool(imp_raw.get("allow_duplicates", False)),
    )

    fat_raw = raw.get("fat", {})
    fat = FatConfig(
        user_index=str(fat_raw.get("user_index", "61379")),
        filing_type=fat_raw.get("filing_type", "F"),
        entity_type=fat_raw.get("entity_type", "I"),
        min_amount=str(fat_raw.get("min_amount", "5000")),
        sources=list(fat_raw.get("sources", [])),
        assignment_table=fat_raw.get("assignment_table", "liens_custom_data"),
        case_id_name=fat_raw.get("case_id_name", "FREEAMTAX Case ID"),
    )

    paths_raw = raw.get("paths", {})
    output_dir = Path(paths_raw.get("output_dir", "./output"))

    return AppConfig(
        database=db, imports=imports, fat=fat, output_dir=output_dir,
        inbox_dir=Path(paths_raw.get("inbox_dir", "./lien-data/inbox")),
        processed_dir=Path(paths_raw.get("processed_dir", "./lien-data/processed")),
        failed_dir=Path(paths_raw.get("failed_dir", "./lien-data/failed")),
    )


def to_dict(cfg: AppConfig) -> dict[str, Any]:
    """Serialize *cfg* back to the same JSON shape :func:`load_config` reads."""
    db = cfg.database
    imp = cfg.imports
    fat = cfg.fat
    return {
        "database": {
            "host": db.host,
            "port": db.port,
            "name": db.name,
            "user": db.user,
            "password": db.password,
            "charset": db.charset,
            "liens_table": db.liens_table,
        },
        "import": {
            "batch_size": imp.batch_size,
            "chunk_size": imp.chunk_size,
            "commit_every_chunks": imp.commit_every_chunks,
            "workers": imp.workers,
            "progress_every": imp.progress_every,
            "use_import_log_table": imp.use_import_log_table,
            "import_log_table": imp.import_log_table,
            "rejects_table": imp.rejects_table,
            "file_ledger_table": imp.file_ledger_table,
            "min_filing_year": imp.min_filing_year,
            "max_commit_rows": imp.max_commit_rows,
            "allow_duplicates": imp.allow_duplicates,
        },
        "fat": {
            "user_index": fat.user_index,
            "filing_type": fat.filing_type,
            "entity_type": fat.entity_type,
            "min_amount": fat.min_amount,
            "sources": fat.sources,
            "assignment_table": fat.assignment_table,
            "case_id_name": fat.case_id_name,
        },
        "paths": {
            "output_dir": str(cfg.output_dir),
            "inbox_dir": str(cfg.inbox_dir),
            "processed_dir": str(cfg.processed_dir),
            "failed_dir": str(cfg.failed_dir),
        },
    }


def save_config(cfg: AppConfig, path: str | os.PathLike[str]) -> None:
    """Write *cfg* to *path* as JSON, preserving any unknown top-level keys
    already in the file (so a hand-added setting isn't silently dropped)."""
    p = Path(path)
    existing: dict[str, Any] = {}
    if p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing.update(to_dict(cfg))
    p.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
