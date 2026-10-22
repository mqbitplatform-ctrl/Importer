"""Worker-side row processing for the optional multi-process import path.

Must stay import-safe and side-effect-free at module load (spawn start method).
The main process keeps all DB / de-dupe / audit / ordering logic; workers only
do the CPU-bound per-row map + normalise + validate + build.
"""

from __future__ import annotations

from datetime import date

from .adapters import REGISTRY, find_adapter
from .normalize.text import canon_header, canon_row
from .recordbuilder import build_record

_adapters: dict[tuple, object] = {}


def _resolve(source_code: str, raw_headers: tuple):
    hit = _adapters.get(raw_headers)
    if hit is None:
        sig = tuple(sorted(canon_header(h) for h in raw_headers))
        hit = (sig, find_adapter(source_code, raw_headers, REGISTRY))
        _adapters[raw_headers] = hit
    return hit


def process_batch(args):
    """args = (source_code, run_date_iso, min_year, rows)
    where rows = list of (file, row_num, raw_dict).
    Returns list of ('ok', MappedRow, BuildResult) or ('unmapped', file, headers).
    """
    source_code, run_date_iso, min_year, rows = args
    run_date = date.fromisoformat(run_date_iso)
    out = []
    for file, row_num, raw in rows:
        raw_headers = tuple(raw.keys())
        sig, adapter = _resolve(source_code, raw_headers)
        if adapter is None:
            out.append(("unmapped", file, list(raw_headers), sig))
            continue
        mapped = adapter.map_row(canon_row(raw), file, row_num, raw)
        br = build_record(mapped, run_date=run_date, min_filing_year=min_year)
        out.append(("ok", mapped, br))
    return out
