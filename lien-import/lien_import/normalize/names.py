"""Name classification + person-name splitting.

``name_kind`` is a port of ``Get-NameKind`` from Get-CsvStats.ps1 (the
$5,000 amount filter that lived in the *caller* is intentionally NOT
reproduced here - per handoff sections 4 and 6).

Changes to the original heuristic, made after previewing the REAL archives
(handoff s6: "modify or add heuristics where necessary and document them"):
  1. "REAL ESTATE" is a business term, not an estate. The original sent
     'Pac West Real Estate Corp' to Trust/Estate - 1,937 real businesses
     (1,816 ATT/ESS + 121 TNU) were being held.
  2. A legal-entity suffix (LLC, INC, CORP, LTD, LP, LLP, PLLC, PC, COMPANY)
     beats trust/estate words: 'Southwest Investment Trust Lp' and
     'Guardina Estate Planning Inc' are companies.

Buckets: "Business" | "Individual" | "TrustEstate" | "Ambiguous"
"""

from __future__ import annotations

import re
from typing import Optional

from .text import collapse_ws

_TRUST_RE = re.compile(r"\b(TRUST|ESTATE|DECEASED|REVOCABLE|IRREVOCABLE)\b")
_REAL_ESTATE_RE = re.compile(r"\bREAL\s+ESTATE\b")
_ENTITY_SUFFIX_RE = re.compile(
    r"\b(LLC|L\.L\.C\.?|INC|INCORPORATED|CORP|CORPORATION|LTD|LP|L\.P\.?|LLP|PLLC|PC|P\.C\.?|COMPANY)\b"
)
_DBA_RE = re.compile(r"\b(DBA|D/B/A)\b")
_SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV)\b")

_BIZ_PATTERNS = [
    r"\bLLC\b", r"\bL\.L\.C\.?\b",
    r"\bINC\b", r"\bINCORPORATED\b",
    r"\bCORP\b", r"\bCORPORATION\b",
    r"\bCOMPANY\b", r"\bCO\b",
    r"\bLTD\b", r"\bLP\b", r"\bL\.P\.?\b",
    r"\bLLP\b", r"\bL\.L\.P\.?\b",
    r"\bPLLC\b", r"\bP\.L\.L\.C\.?\b",
    r"\bPC\b", r"\bP\.C\.?\b",
    r"\bCONSTRUCTION\b", r"\bEXCAVATION\b", r"\bROOF(ING)?\b", r"\bPLUMB(ING)?\b",
    r"\bELECTRIC(AL)?\b", r"\bHVAC\b", r"\bHEATING\b", r"\bCOOLING\b",
    r"\bSERVICE(S)?\b", r"\bSOLUTIONS\b", r"\bMANAGEMENT\b", r"\bHOLDINGS\b",
    r"\bPROPERT(Y|IES)\b", r"\bINVESTMENTS?\b", r"\bGROUP\b", r"\bENTERPRISES?\b",
    r"\bSYSTEMS?\b", r"\bDRILLING\b", r"\bTRUCKING\b", r"\bTRANSPORT\b",
    r"\bLOGISTICS\b", r"\bLANDSCAP(E|ING)\b", r"\bLAWN\b", r"\bCARE\b",
    r"\bREMODEL(ING)?\b", r"\bRENOVATION\b", r"\bPAINTING\b", r"\bFLOORING\b",
    r"\bCONCRETE\b", r"\bAUTO\b", r"\bMOTORS?\b", r"\bREPAIR\b", r"\bTIRE(S)?\b",
    r"\bTOWING\b", r"\bRESTAURANT\b", r"\bCAFE\b", r"\bBAR\b", r"\bGRILL\b",
    r"\bMARKET\b", r"\bGROCERY\b", r"\bBAKERY\b", r"\bBREW(ING|ERY)\b",
    r"\bFOOD(S)?\b", r"\bKITCHEN\b", r"\bTAQUERIA\b", r"\bINN\b", r"\bHOTEL\b",
    r"\bMOTEL\b", r"\bSUITES\b", r"\bHEALTHCARE\b", r"\bHEALTH\b", r"\bHOMECARE\b",
    r"\bCHURCH\b", r"\bMINISTRIES\b", r"\bSCHOOL\b", r"\bACADEMY\b",
    r"\bUNIVERSITY\b", r"\bCOLLEGE\b", r"\bHOSPITAL\b", r"\bCLINIC\b",
    r"\bDENTAL\b", r"\bPHARMACY\b", r"\bASSOCIATES\b", r"\bASSOCIATION\b",
    r"\bFOUNDATION\b", r"\bBANK\b", r"\bCREDIT UNION\b", r"\bCREDIT\b", r"\bUNION\b",
    r"\bREAL\s+ESTATE\b",
]
_BIZ_RE = re.compile("|".join(_BIZ_PATTERNS))

_PERSONAL_PARTICLES = {
    "DE", "DEL", "LA", "LOS", "LAS", "DA", "DO", "DOS", "DAS", "DI",
    "VAN", "VON", "MC", "MAC",
}
_NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-.]*$")
_INITIAL_RE = re.compile(r"^[A-Za-z]\.?$")

SUFFIX_TOKENS = {"JR", "SR", "II", "III", "IV", "JR.", "SR."}


def name_kind(full_name: Optional[str]) -> str:
    if full_name is None or not full_name.strip():
        return "Ambiguous"

    n = collapse_ws(full_name) or ""
    u = n.upper()

    if _ENTITY_SUFFIX_RE.search(u):  # change 2: a company even if it says "Trust"
        return "Business"
    if _TRUST_RE.search(_REAL_ESTATE_RE.sub("", u)):  # change 1: "Real Estate" isn't an estate
        return "TrustEstate"
    if _DBA_RE.search(u):
        return "Business"
    if re.match(r"^\d", n):
        return "Business"
    if _BIZ_RE.search(u):
        return "Business"

    tokens = [t for t in n.split(" ") if t]

    if len(tokens) == 1:
        return "Business"

    if _SUFFIX_RE.search(u):
        return "Individual"

    if 2 <= len(tokens) <= 6:
        all_name_chars = all(_NAME_TOKEN_RE.match(t) for t in tokens)
        if all_name_chars:
            if any(t.upper() in {"THE", "OF"} for t in tokens):
                return "Business"
            has_initial = any(_INITIAL_RE.match(t) for t in tokens)
            has_particle = any(t.upper().strip(".") in _PERSONAL_PARTICLES for t in tokens)
            if len(tokens) <= 4 or has_initial or has_particle:
                return "Individual"

    if re.search(r"[&/]", n):
        return "Ambiguous"

    return "Business"


def strong_business(name: Optional[str]) -> bool:
    """True only for POSITIVE business evidence (entity suffix, business word,
    DBA, leading digit) - not for name_kind's weak fallbacks such as "a single
    word is a business"."""
    u = (collapse_ws(name) or "").upper()
    if not u:
        return False
    return bool(
        _ENTITY_SUFFIX_RE.search(u) or _DBA_RE.search(u)
        or re.match(r"^\d", u) or _BIZ_RE.search(u)
    )


# Fillers the TNU Starter file puts in name fields when there is no value
# (real archive: Last Name 'NA' 50,378, 'N/A' 17,729, 'Doe' 14,723; Middle
# Name 'N/A' 16,535). Left in, they become "JOHN NA" / "JASON DOE" - and the
# '/' in 'N/A' made name_kind call 5,490 rows "Ambiguous" (joint names).
_PLACEHOLDERS = {"N/A", "NA", "N.A.", "NONE", "NULL", "NAN", "UNKNOWN", "-", "--"}


def is_placeholder(value: Optional[str], *, last_name: bool = False) -> bool:
    v = (collapse_ws(value) or "").upper()
    if not v:
        return False
    if v in _PLACEHOLDERS:
        return True
    return last_name and v == "DOE"  # 'John Doe' filler - only as the whole last name


def split_person_name(
    full_name: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Split a single 'First [Middle] Last [Suffix]' string.

    Returns (first, middle_initial, last). Suffixes are appended to *last*.
    """
    n = collapse_ws(full_name) or ""
    if not n:
        return None, None, None

    tokens = [t for t in n.split(" ") if t]
    suffix = None
    if tokens and tokens[-1].upper().rstrip(".") in {s.rstrip(".") for s in SUFFIX_TOKENS}:
        suffix = tokens.pop()

    if not tokens:
        return None, None, None
    if len(tokens) == 1:
        # lone token: treat as given name (individuals with one token are rare -
        # name_kind sends single-token names to Business before this is called)
        return tokens[0], None, (suffix or None)
    if len(tokens) == 2:
        first, last = tokens[0], tokens[1]
        return first, None, _join_suffix(last, suffix)
    else:
        first = tokens[0]
        middle = tokens[1]
        last = " ".join(tokens[2:])
        mi = middle[0].upper() if middle and middle[0].isalpha() else None
        return first, mi, _join_suffix(last, suffix)


def _join_suffix(last: str, suffix: Optional[str]) -> str:
    if suffix:
        return f"{last} {suffix}"
    return last


def middle_initial_of(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    return v[0].upper() if v[0].isalpha() else None


def assemble_name(*parts: Optional[str]) -> Optional[str]:
    joined = " ".join(p.strip() for p in parts if p and p.strip())
    return collapse_ws(joined)
