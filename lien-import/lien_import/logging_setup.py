"""Structured logging to console + a per-run log file."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(run_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger("lien_import")
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(logging.Formatter(_FMT))
    root.addHandler(console)

    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        fileh = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
        fileh.setFormatter(logging.Formatter(_FMT))
        root.addHandler(fileh)

    return root
