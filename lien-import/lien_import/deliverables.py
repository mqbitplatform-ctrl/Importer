"""Generate handoff Deliverables A and C as Markdown.

  A - Discovery Summary  (handoff section 18.A)
  C - Preview/Audit Results  (handoff section 18.C / section 12)

Deliverables B (ID Strategy), D (Open Questions) and E (Implementation Plan +
Estimate) are static documents under ``docs/`` - they do not need generating
from a run.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

from .adapters.mapping_docs import FORMAT_DOCS
from .config import AppConfig
from .discovery import discover


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def discovery_summary(source_code: str, input_path: str) -> str:
    rep = discover(source_code, input_path)
    today = date.today().isoformat()
    out = [
        f"# Deliverable A - Discovery Summary ({source_code})",
        "",
        f"- Generated: {today}",
        f"- Input inspected: `{input_path}`",
        f"- Distinct header signatures found: {len(rep['signatures'])}",
        "",
        "> Based on the files actually inspected at the path above. If this was a "
        "sample rather than the full archive, re-run against the complete archive "
        "before sign-off (handoff section 18.A).",
        "",
    ]
    for i, sig in enumerate(rep["signatures"], 1):
        fmt = sig["matched_adapter"] or "UNMAPPED"
        out += [
            f"## Signature {i}: `{fmt}`",
            "",
            f"- Files: {sig['file_count']}  (e.g. {', '.join(sig['example_files'])})",
            f"- Rows: {sig['row_count']:,}",
            f"- Matched adapter: **{fmt}**",
            "",
            "### Column structure",
            "",
            "| Column | Canonical | Populated % | Date % | Money % | Sample values |",
            "|--------|-----------|-------------|--------|---------|---------------|",
        ]
        for c in sig["columns"]:
            sv = "; ".join(str(v) for v in c["sample_values"][:4])
            out.append(
                f"| {c['raw']} | {c['canonical']} | {c['populated_pct']} | "
                f"{c['parsed_as_date_pct'] if c['parsed_as_date_pct'] is not None else '-'} | "
                f"{c['parsed_as_money_pct'] if c['parsed_as_money_pct'] is not None else '-'} | {sv} |"
            )
        doc = FORMAT_DOCS.get(fmt)
        if doc:
            out += [
                "",
                "### Proposed mapping to `liens`",
                "",
                "| `liens` column | Source rule |",
                "|----------------|-------------|",
                *[f"| {k} | {v} |" for k, v in doc["mapping"].items()],
                "",
                f"### Columns not mapped\n\n{_bullets(doc['not_mapped'])}",
                "",
                f"### Transformations required\n\n{_bullets(doc['transformations'])}",
                "",
                f"### Heuristics required\n\n{_bullets(doc['heuristics'])}",
                "",
                f"### Assumptions\n\n{_bullets(doc['assumptions'])}",
                "",
                f"### Known problems / ambiguities\n\n{_bullets(doc['known_problems'])}",
                "",
            ]
        else:
            out += [
                "",
                "### Proposed mapping",
                "",
                "**No adapter matched this layout.** A new adapter module is required "
                "(one class in `lien_import/adapters/` + a line in `REGISTRY`). "
                "Document the mapping here once the layout is understood.",
                "",
            ]
    if rep.get("signatures") and all(s["matched_adapter"] for s in rep["signatures"]):
        out.append("_All header signatures matched an existing adapter._")
    return "\n".join(out) + "\n"


def preview_audit_results(
    source_code: str,
    input_path: str,
    cfg: AppConfig,
    *,
    limit: Optional[int] = None,
    work_dir: Optional[Path] = None,
) -> str:
    from .pipeline import run as run_pipeline

    tmp = (work_dir or cfg.output_dir) / f"_preview_{source_code}"
    result = run_pipeline(
        source_code=source_code,
        input_path=input_path,
        cfg=cfg,
        run_dir=tmp,
        mode="preview",
        limit=limit,
    )
    a = result.audit.to_dict()
    today = date.today().isoformat()

    def s12_table(section12: dict) -> list[str]:
        return [
            "| Metric | Count |",
            "|--------|------:|",
            *[f"| {k.replace('_', ' ')} | {v:,} |" for k, v in section12.items()],
        ]

    out = [
        f"# Deliverable C - Preview / Audit Results ({source_code})",
        "",
        f"- Generated: {today}",
        f"- Input: `{input_path}`",
        f"- Reconciles: **{a['reconciles']}**",
        "",
        "> No rows were written to the database. Counts follow handoff section 12. "
        "Must be regenerated against the complete archives before production import.",
        "",
        "## Combined",
        "",
        *s12_table(a["combined"]["section12"]),
        "",
        "### Cross-tab (Federal/State x Business/Individual)",
        "",
        "| | Business | Individual |",
        "|---|---:|---:|",
        f"| Federal | {a['combined']['cross_tab']['federal']['business']:,} | {a['combined']['cross_tab']['federal']['individual']:,} |",
        f"| State | {a['combined']['cross_tab']['state']['business']:,} | {a['combined']['cross_tab']['state']['individual']:,} |",
        "",
        f"Held: Trust/Estate {a['combined']['cross_tab']['held']['trust_estate']:,}, "
        f"Ambiguous {a['combined']['cross_tab']['held']['ambiguous']:,}",
        "",
        f"Jurisdiction inference: {a['combined']['jurisdiction_inference']}",
        "",
        f"Missing/invalid field tally: {a['combined']['missing_field_tally'] or '(none)'}",
        "",
    ]
    for fmt, fd in a["by_format"].items():
        out += [
            f"## Format: `{fmt}`",
            "",
            *s12_table(fd["section12"]),
            "",
            f"Cross-tab F: B={fd['cross_tab']['federal']['business']:,} "
            f"I={fd['cross_tab']['federal']['individual']:,} / "
            f"S: B={fd['cross_tab']['state']['business']:,} "
            f"I={fd['cross_tab']['state']['individual']:,}",
            "",
            f"Missing/invalid field tally: {fd['missing_field_tally'] or '(none)'}",
            "",
        ]
    samples = (tmp / f"samples_{source_code}.txt")
    if samples.is_file():
        lines = samples.read_text(encoding="utf-8").strip().splitlines()[:25]
        out += ["## Representative classified examples", "", "```", *lines, "```", ""]
    if a["unmapped_headers"]:
        out += [
            "## Unmapped header signatures",
            "",
            "```",
            json.dumps(a["unmapped_headers"], indent=2),
            "```",
            "",
        ]
    return "\n".join(out) + "\n"
