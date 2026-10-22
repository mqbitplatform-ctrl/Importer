"""``analyze`` - statistical / data-quality reporting.

Two modes:
  * file mode  - profile the source CSVs before import (like the old
                 Get-CsvStats.ps1, but no $5,000 filter and with data-quality
                 detail). Does NOT de-duplicate - it is analytical, not the
                 importer.
  * db mode    - profile the consolidated `liens` table after import
                 (optionally filtered to one lien_source).

Reports: Federal/State x Business/Individual cross-tab, amount bands, filing-
year histogram, jurisdiction distribution, name-kind distribution with
examples, top creditors, and (file mode) the section-12 audit + missing-field
tally per format.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from .adapters import REGISTRY, find_adapter
from .audit import SourceAudit
from .config import AppConfig
from .models import Disposition
from .normalize.text import canon_header, canon_row
from .recordbuilder import build_record
from .sourcereader import iter_source_rows

_BANDS = [
    (Decimal(0), Decimal(1000), "< $1k"),
    (Decimal(1000), Decimal(5000), "$1k - $5k"),
    (Decimal(5000), Decimal(10000), "$5k - $10k"),
    (Decimal(10000), Decimal(25000), "$10k - $25k"),
    (Decimal(25000), Decimal(50000), "$25k - $50k"),
    (Decimal(50000), Decimal(100000), "$50k - $100k"),
    (Decimal(100000), Decimal(250000), "$100k - $250k"),
    (Decimal(250000), Decimal(1000000), "$250k - $1M"),
    (Decimal(1000000), None, ">= $1M"),
]


def _band(amount: Optional[Decimal]) -> str:
    if amount is None:
        return "(unparseable)"
    for lo, hi, label in _BANDS:
        if amount >= lo and (hi is None or amount < hi):
            return label
    return "(other)"


@dataclass
class Distributions:
    amount_bands: Counter = field(default_factory=Counter)
    filing_year: Counter = field(default_factory=Counter)
    jurisdiction: Counter = field(default_factory=Counter)
    filing_type: Counter = field(default_factory=Counter)
    entity_type: Counter = field(default_factory=Counter)
    name_kind: Counter = field(default_factory=Counter)
    name_kind_examples: dict[str, list[str]] = field(default_factory=dict)
    top_creditors: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount_bands": _ordered_bands(self.amount_bands),
            "filing_year": dict(sorted(self.filing_year.items())),
            "jurisdiction": dict(self.jurisdiction.most_common(60)),
            "filing_type": dict(self.filing_type),
            "entity_type": dict(self.entity_type),
            "name_kind": dict(self.name_kind),
            "name_kind_examples": self.name_kind_examples,
            "top_creditors": dict(self.top_creditors.most_common(20)),
        }


def _ordered_bands(c: Counter) -> dict[str, int]:
    out = {label: c.get(label, 0) for _, _, label in _BANDS}
    for k in c:
        if k not in out:
            out[k] = c[k]
    return out


# --------------------------------------------------------------------- file mode

def analyze_files(
    source_code: str,
    input_path: str,
    cfg: AppConfig,
    *,
    run_date: Optional[date] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    run_date = run_date or date.today()
    audit = SourceAudit(source_code=source_code, input_path=str(input_path))
    dist = Distributions()
    adapter_cache: dict[tuple, Any] = {}
    seen_unmapped: set[tuple] = set()
    n = 0

    for srow in iter_source_rows(input_path):
        sig = tuple(sorted(canon_header(h) for h in srow.data.keys()))
        if sig not in adapter_cache:
            adapter_cache[sig] = find_adapter(source_code, srow.data.keys(), REGISTRY)
        adapter = adapter_cache[sig]
        if adapter is None:
            if sig not in seen_unmapped:
                seen_unmapped.add(sig)
                audit.unmapped_headers.append(
                    {"file": srow.file, "headers": list(srow.data.keys())}
                )
            continue

        mapped = adapter.map_row(canon_row(srow.data), srow.file, srow.row_num, srow.data)
        br = build_record(mapped, run_date=run_date, min_filing_year=cfg.imports.min_filing_year)
        audit.record(br.disposition, br.classification, mapped.source_format, br.problem_fields)

        cls = br.classification
        rec = br.record
        amt = rec.lien_amount if rec else None
        dist.amount_bands[_band(amt)] += 1
        if rec and rec.lien_filing_date:
            dist.filing_year[rec.lien_filing_date.year] += 1
        if cls.jurisdiction:
            dist.jurisdiction[cls.jurisdiction] += 1
        if cls.filing_type:
            dist.filing_type[cls.filing_type] += 1
        if cls.entity_type:
            dist.entity_type[cls.entity_type] += 1
        k = cls.name_kind or "Unknown"
        dist.name_kind[k] += 1
        ex = dist.name_kind_examples.setdefault(k, [])
        if cls.name_used and len(ex) < 8 and cls.name_used not in ex:
            ex.append(cls.name_used)
        if mapped.creditor:
            c = mapped.creditor.strip()
            # keep the counter bounded on pathologically varied creditor text
            if c in dist.top_creditors or len(dist.top_creditors) < 5000:
                dist.top_creditors[c] += 1

        n += 1
        if limit and n >= limit:
            break

    return {
        "mode": "file",
        "source_code": source_code,
        "input_path": str(input_path),
        "audit": audit.to_dict(),
        "distributions": dist.to_dict(),
    }


# ----------------------------------------------------------------------- db mode

def analyze_db(conn, table: str, source: Optional[str] = None) -> dict[str, Any]:
    where = "WHERE lien_source = %s" if source else ""
    args = [source] if source else []

    def q(sql: str) -> list[tuple]:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    total = q(f"SELECT COUNT(*) FROM `{table}` {where}")[0][0]
    by_source = q(f"SELECT lien_source, COUNT(*) FROM `{table}` {where} GROUP BY 1 ORDER BY 1")
    crosstab = q(
        f"SELECT lien_filing_type, lien_entity_type, COUNT(*) "
        f"FROM `{table}` {where} GROUP BY 1,2 ORDER BY 1,2"
    )
    juris = q(
        f"SELECT lien_jurisdiction, COUNT(*) FROM `{table}` {where} "
        f"GROUP BY 1 ORDER BY 2 DESC"
    )
    years = q(
        f"SELECT YEAR(lien_filing_date), COUNT(*) FROM `{table}` {where} GROUP BY 1 ORDER BY 1"
    )
    plaintiffs = q(
        f"SELECT lien_plaintiff, COUNT(*) FROM `{table}` {where} "
        f"GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
    )
    released = q(
        f"SELECT SUM(lien_release_date IS NOT NULL), SUM(lien_release_date IS NULL) "
        f"FROM `{table}` {where}"
    )[0]
    amt_case = " ".join(
        f"WHEN lien_amount >= {lo} AND {'1=1' if hi is None else f'lien_amount < {hi}'} THEN '{label}'"
        for lo, hi, label in _BANDS
    )
    bands = q(
        f"SELECT CASE {amt_case} ELSE '(other)' END b, COUNT(*) "
        f"FROM `{table}` {where} GROUP BY 1"
    )
    amt_stats = q(
        f"SELECT MIN(lien_amount), MAX(lien_amount), AVG(lien_amount), "
        f"SUM(lien_amount) FROM `{table}` {where}"
    )[0]

    return {
        "mode": "db",
        "table": table,
        "source_filter": source,
        "total_rows": total,
        "by_source": {r[0]: r[1] for r in by_source},
        "cross_tab": {f"{r[0]}/{r[1]}": r[2] for r in crosstab},
        "jurisdiction": {r[0]: r[1] for r in juris},
        "filing_year": {int(r[0]): r[1] for r in years if r[0] is not None},
        "amount_bands": _ordered_bands(Counter({r[0]: r[1] for r in bands})),
        "amount_stats": {
            "min": str(amt_stats[0]),
            "max": str(amt_stats[1]),
            "avg": str(round(amt_stats[2], 2)) if amt_stats[2] is not None else None,
            "sum": str(amt_stats[3]),
        },
        "release_date": {"populated": int(released[0] or 0), "null": int(released[1] or 0)},
        "top_plaintiffs": {r[0]: r[1] for r in plaintiffs},
    }


# ----------------------------------------------------------------------- render

def render_text(report: dict[str, Any]) -> str:
    if report["mode"] == "file":
        out = [
            f"ANALYSIS (file) - source {report['source_code']}   {report['input_path']}",
            "=" * 64,
        ]
        a = report["audit"]["combined"]["section12"]
        ct = report["audit"]["combined"]["cross_tab"]
        out += [
            "Section 12 (combined):",
            *[f"  {k:<28} {v:>12,}" for k, v in a.items()],
            "",
            "Cross-tab:",
            f"  Federal  Business {ct['federal']['business']:>10,}   Individual {ct['federal']['individual']:>10,}",
            f"  State    Business {ct['state']['business']:>10,}   Individual {ct['state']['individual']:>10,}",
            f"  Held     Trust/Estate {ct['held']['trust_estate']:>7,}   Ambiguous {ct['held']['ambiguous']:>7,}",
        ]
        d = report["distributions"]
        out += ["", "Amount bands:"]
        out += [f"  {k:<16} {v:>12,}" for k, v in d["amount_bands"].items()]
        out += ["", "Filing year:"]
        out += [f"  {k:<16} {v:>12,}" for k, v in d["filing_year"].items()]
        out += ["", "Jurisdiction (top 20):"]
        out += [f"  {k:<16} {v:>12,}" for k, v in list(d["jurisdiction"].items())[:20]]
        out += ["", "Name-kind distribution:"]
        for k, v in d["name_kind"].items():
            ex = ", ".join(d["name_kind_examples"].get(k, [])[:4])
            out.append(f"  {k:<14} {v:>10,}   e.g. {ex}")
        out += ["", "Top creditors:"]
        out += [f"  {v:>8,}  {k}" for k, v in list(d["top_creditors"].items())[:15]]
        by_fmt = report["audit"].get("by_format", {})
        if len(by_fmt) > 1:
            out += ["", "Per-format section 12:"]
            for fmt, fd in by_fmt.items():
                s = fd["section12"]
                out.append(f"  [{fmt}] examined={s['total_examined']:,} "
                           f"would_insert={s['would_insert']:,} "
                           f"missing={s['missing_required_values']:,} "
                           f"held={s['trust_estate_held'] + s['ambiguous_entity_held']:,}")
        return "\n".join(x for x in out if x is not None)

    # db mode
    out = [
        f"ANALYSIS (db) - table {report['table']}"
        + (f"   source={report['source_filter']}" if report["source_filter"] else ""),
        "=" * 64,
        f"total rows: {report['total_rows']:,}",
        f"by source:  {report['by_source']}",
        "",
        "Cross-tab (filing_type/entity_type):",
    ]
    out += [f"  {k:<10} {v:>12,}" for k, v in report["cross_tab"].items()]
    out += ["", f"amount stats: {report['amount_stats']}", "", "Amount bands:"]
    out += [f"  {k:<16} {v:>12,}" for k, v in report["amount_bands"].items()]
    out += ["", "Filing year:"]
    out += [f"  {k:<16} {v:>12,}" for k, v in report["filing_year"].items()]
    out += ["", "Jurisdiction (top 20):"]
    out += [f"  {k:<16} {v:>12,}" for k, v in list(report["jurisdiction"].items())[:20]]
    out += ["", f"release_date populated: {report['release_date']}", "", "Top plaintiffs:"]
    out += [f"  {v:>8,}  {k}" for k, v in report["top_plaintiffs"].items()]
    return "\n".join(out)
