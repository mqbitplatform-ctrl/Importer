"""``discover`` - profile source CSVs without mapping or writing anything.

For each distinct header signature found under the input:
  * files + row count
  * column list (raw + canonical)
  * which adapter (if any) would claim it
  * per-column: % populated, sample distinct values
  * detected date / amount format hints on the likely columns
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .adapters import REGISTRY, find_adapter
from .normalize.dates import parse_date
from .normalize.money import parse_money
from .normalize.text import canon_header
from .sourcereader import iter_source_rows

log = logging.getLogger("lien_import.discovery")

_MAX_DISTINCT = 8


@dataclass
class _Sig:
    headers: tuple[str, ...]
    files: set[str] = field(default_factory=set)
    rows: int = 0
    populated: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    distinct: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    date_ok: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    money_ok: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def discover(source_code: Optional[str], input_path: str) -> dict:
    sigs: dict[tuple, _Sig] = {}

    for srow in iter_source_rows(input_path):
        headers = tuple(srow.data.keys())
        sig = sigs.setdefault(headers, _Sig(headers=headers))
        sig.files.add(srow.file)
        sig.rows += 1
        for k, v in srow.data.items():
            v = (v or "").strip()
            if v:
                sig.populated[k] += 1
                if len(sig.distinct[k]) < _MAX_DISTINCT:
                    sig.distinct[k].add(v[:60])
            ck = canon_header(k)
            if any(tok in ck for tok in ("date", "filing date")):
                if parse_date(v):
                    sig.date_ok[k] += 1
            if any(tok in ck for tok in ("amount", "amount owed")):
                if parse_money(v) is not None:
                    sig.money_ok[k] += 1

    report = {"input": str(input_path), "signatures": []}
    for sig in sigs.values():
        adapter = (
            find_adapter(source_code, sig.headers, REGISTRY) if source_code else None
        )
        cols = []
        for h in sig.headers:
            n = sig.rows or 1
            cols.append(
                {
                    "raw": h,
                    "canonical": canon_header(h),
                    "populated_pct": round(100 * sig.populated.get(h, 0) / n, 1),
                    "sample_values": sorted(sig.distinct.get(h, set()))[:_MAX_DISTINCT],
                    "parsed_as_date_pct": round(100 * sig.date_ok.get(h, 0) / n, 1)
                    if h in sig.date_ok else None,
                    "parsed_as_money_pct": round(100 * sig.money_ok.get(h, 0) / n, 1)
                    if h in sig.money_ok else None,
                }
            )
        report["signatures"].append(
            {
                "headers": list(sig.headers),
                "file_count": len(sig.files),
                "example_files": sorted(sig.files)[:5],
                "row_count": sig.rows,
                "matched_adapter": adapter.format_name if adapter else None,
                "columns": cols,
            }
        )
    return report


def render_text(report: dict) -> str:
    out = [f"Discovery - input: {report['input']}", "=" * 60]
    for s in report["signatures"]:
        out.append("")
        out.append(
            f"[{s['matched_adapter'] or 'UNMAPPED'}]  "
            f"{s['file_count']} file(s), {s['row_count']:,} rows"
        )
        out.append(f"  files: {', '.join(s['example_files'])}")
        for c in s["columns"]:
            extra = ""
            if c["parsed_as_date_pct"] is not None:
                extra += f"  date%={c['parsed_as_date_pct']}"
            if c["parsed_as_money_pct"] is not None:
                extra += f"  money%={c['parsed_as_money_pct']}"
            out.append(
                f"    {c['raw']:<22} canon={c['canonical']:<20} "
                f"pop%={c['populated_pct']:<6}{extra}"
            )
            out.append(f"        e.g. {c['sample_values']}")
    return "\n".join(out)
