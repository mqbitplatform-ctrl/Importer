"""Audit accumulator + rendering.

Produces the handoff section 12 counts, a Federal/State x Business/Individual
cross-tab (mirrors Get-CsvStats.ps1), inference-source stats, and a
missing-required-field tally - **per source format** as well as combined
(section 12: "if different CSV formats require different assumptions, identify
those separately").

Reconciliation invariant (per format and combined):

    examined == would_insert + duplicates_within_source
                + rejected_missing + rejected_invalid
                + held_trust_estate + held_ambiguous
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .models import Disposition


@dataclass
class Counters:
    examined: int = 0
    would_insert: int = 0
    duplicates_within_source: int = 0
    rejected_missing: int = 0
    rejected_invalid: int = 0
    held_trust_estate: int = 0
    held_ambiguous: int = 0

    # cross-tab over would_insert rows
    fed_business: int = 0
    fed_individual: int = 0
    state_business: int = 0
    state_individual: int = 0

    # jurisdiction inference source (would_insert rows)
    juris_from_creditor: int = 0
    juris_from_note: int = 0
    juris_from_address: int = 0

    missing_fields: Counter = field(default_factory=Counter)
    disposition_counts: Counter = field(default_factory=Counter)

    def add(self, disposition: Disposition, cls, problem_fields) -> None:
        self.examined += 1
        self.disposition_counts[disposition.value] += 1

        if disposition is Disposition.INSERT:
            self.would_insert += 1
            if cls.filing_type == "F" and cls.entity_type == "B":
                self.fed_business += 1
            elif cls.filing_type == "F" and cls.entity_type == "I":
                self.fed_individual += 1
            elif cls.filing_type == "S" and cls.entity_type == "B":
                self.state_business += 1
            elif cls.filing_type == "S" and cls.entity_type == "I":
                self.state_individual += 1
            src = cls.jurisdiction_source
            if src == "creditor":
                self.juris_from_creditor += 1
            elif src == "note_filing_office":
                self.juris_from_note += 1
            elif src == "address_state":
                self.juris_from_address += 1
        elif disposition is Disposition.SKIP_DUPLICATE:
            self.duplicates_within_source += 1
        elif disposition is Disposition.REJECT_MISSING:
            self.rejected_missing += 1
            for f in problem_fields:
                self.missing_fields[f] += 1
        elif disposition is Disposition.REJECT_INVALID:
            self.rejected_invalid += 1
            for f in problem_fields:
                self.missing_fields[f] += 1
        elif disposition is Disposition.HOLD_TRUST_ESTATE:
            self.held_trust_estate += 1
        elif disposition is Disposition.HOLD_AMBIGUOUS:
            self.held_ambiguous += 1

    @property
    def federal(self) -> int:
        return self.fed_business + self.fed_individual

    @property
    def state(self) -> int:
        return self.state_business + self.state_individual

    @property
    def business(self) -> int:
        return self.fed_business + self.state_business

    @property
    def individual(self) -> int:
        return self.fed_individual + self.state_individual

    @property
    def usable(self) -> int:
        return (
            self.examined
            - self.rejected_missing
            - self.rejected_invalid
            - self.held_trust_estate
            - self.held_ambiguous
        )

    def reconciles(self) -> bool:
        return self.examined == (
            self.would_insert
            + self.duplicates_within_source
            + self.rejected_missing
            + self.rejected_invalid
            + self.held_trust_estate
            + self.held_ambiguous
        )

    def section12(self) -> dict[str, int]:
        return {
            "total_examined": self.examined,
            "considered_usable": self.usable,
            "federal_liens": self.federal,
            "state_liens": self.state,
            "business_liens": self.business,
            "individual_liens": self.individual,
            "trust_estate_held": self.held_trust_estate,
            "ambiguous_entity_held": self.held_ambiguous,
            "duplicates_within_source": self.duplicates_within_source,
            "missing_required_values": self.rejected_missing,
            "rejected_other": self.rejected_invalid,
            "would_insert": self.would_insert,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "section12": self.section12(),
            "cross_tab": {
                "federal": {"business": self.fed_business, "individual": self.fed_individual},
                "state": {"business": self.state_business, "individual": self.state_individual},
                "held": {
                    "trust_estate": self.held_trust_estate,
                    "ambiguous": self.held_ambiguous,
                },
            },
            "jurisdiction_inference": {
                "from_creditor": self.juris_from_creditor,
                "from_note_filing_office": self.juris_from_note,
                "from_address_state": self.juris_from_address,
            },
            "missing_field_tally": dict(self.missing_fields),
            "dispositions": dict(self.disposition_counts),
            "reconciles": self.reconciles(),
        }


def _fmt(n: int) -> str:
    return f"{n:,}"


def _counter_table(c: Counters) -> str:
    s = c.section12()
    lines = [
        f"  total records examined            {s['total_examined']:>12,}",
        f"  records considered usable         {s['considered_usable']:>12,}",
        f"  Federal liens                     {s['federal_liens']:>12,}",
        f"  State liens                       {s['state_liens']:>12,}",
        f"  Business liens                    {s['business_liens']:>12,}",
        f"  Individual liens                  {s['individual_liens']:>12,}",
        f"  Trust/Estate records (held)       {s['trust_estate_held']:>12,}",
        f"  Ambiguous entity records (held)   {s['ambiguous_entity_held']:>12,}",
        f"  duplicates within source          {s['duplicates_within_source']:>12,}",
        f"  missing required values           {s['missing_required_values']:>12,}",
        f"  rejected for other reasons        {s['rejected_other']:>12,}",
        f"  records that WOULD be inserted    {s['would_insert']:>12,}",
    ]
    return "\n".join(lines)


def _crosstab(c: Counters) -> str:
    return "\n".join(
        [
            "                     Business    Individual",
            f"  Federal          {c.fed_business:>10,}  {c.fed_individual:>12,}",
            f"  State            {c.state_business:>10,}  {c.state_individual:>12,}",
            f"  (held) Trust/Estate {c.held_trust_estate:>10,}     Ambiguous {c.held_ambiguous:>8,}",
        ]
    )


def _inference(c: Counters) -> str:
    return (
        "  jurisdiction resolved from:  "
        f"creditor={_fmt(c.juris_from_creditor)}  "
        f"note_filing_office={_fmt(c.juris_from_note)}  "
        f"address_state={_fmt(c.juris_from_address)}"
    )


@dataclass
class SourceAudit:
    source_code: str
    input_path: str
    started_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    combined: Counters = field(default_factory=Counters)
    by_format: dict[str, Counters] = field(default_factory=dict)
    unmapped_headers: list[dict[str, Any]] = field(default_factory=list)
    allow_duplicates: bool = False  # import.allow_duplicates was ON for this run

    # ------------------------------------------------------------------ ingest
    def record(self, disposition: Disposition, cls, source_format: str,
               problem_fields=()) -> None:
        self.combined.add(disposition, cls, problem_fields)
        self.by_format.setdefault(source_format, Counters()).add(
            disposition, cls, problem_fields
        )

    # ----------------------------------------------------- compatibility shims
    @property
    def examined(self) -> int:
        return self.combined.examined

    @property
    def would_insert(self) -> int:
        return self.combined.would_insert

    @property
    def duplicates_within_source(self) -> int:
        return self.combined.duplicates_within_source

    @property
    def rejected_missing(self) -> int:
        return self.combined.rejected_missing

    @property
    def rejected_invalid(self) -> int:
        return self.combined.rejected_invalid

    @property
    def held_trust_estate(self) -> int:
        return self.combined.held_trust_estate

    @property
    def held_ambiguous(self) -> int:
        return self.combined.held_ambiguous

    @property
    def federal(self) -> int:
        return self.combined.federal

    @property
    def state(self) -> int:
        return self.combined.state

    @property
    def business(self) -> int:
        return self.combined.business

    @property
    def individual(self) -> int:
        return self.combined.individual

    @property
    def usable(self) -> int:
        return self.combined.usable

    def reconciles(self) -> bool:
        return self.combined.reconciles() and all(
            c.reconciles() for c in self.by_format.values()
        )

    # ----------------------------------------------------------------- output
    def to_dict(self) -> dict[str, Any]:
        return {
            "source_code": self.source_code,
            "input_path": self.input_path,
            "started_at": self.started_at,
            "allow_duplicates": self.allow_duplicates,
            "combined": self.combined.to_dict(),
            "by_format": {k: v.to_dict() for k, v in self.by_format.items()},
            "unmapped_headers": self.unmapped_headers,
            "reconciles": self.reconciles(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def render_text(self) -> str:
        out = [
            f"Audit - source {self.source_code}   input: {self.input_path}",
            f"  run started {self.started_at}",
            *(["  DUPLICATES ALLOWED - a lien repeated in several files/rows is kept "
               "once per source row"] if self.allow_duplicates else []),
            "",
            "=== COMBINED ===",
            _counter_table(self.combined),
            "",
            _crosstab(self.combined),
            _inference(self.combined),
        ]
        if self.combined.missing_fields:
            out.append(
                "  missing/invalid field tally: "
                + ", ".join(f"{k}={v}" for k, v in sorted(self.combined.missing_fields.items()))
            )
        out.append(f"  reconciles: {self.combined.reconciles()}")

        for fmt, c in sorted(self.by_format.items()):
            out += [
                "",
                f"=== FORMAT: {fmt} ===",
                _counter_table(c),
                "",
                _crosstab(c),
                _inference(c),
            ]
            if c.missing_fields:
                out.append(
                    "  missing/invalid field tally: "
                    + ", ".join(f"{k}={v}" for k, v in sorted(c.missing_fields.items()))
                )
            out.append(f"  reconciles: {c.reconciles()}")

        if self.unmapped_headers:
            out.append("")
            out.append(
                f"UNMAPPED header signatures: {len(self.unmapped_headers)} "
                f"(see audit_{self.source_code}.json)"
            )
        return "\n".join(out)
