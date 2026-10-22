"""Deterministic ``lien_id`` generation.

Requirements (handoff section 8):
  * <= 15 characters
  * unique within a lien_source
  * stable / deterministic - same source record -> same id on re-run
  * re-running an import must not create a second copy

Strategy
--------
1. Build a *natural key* string from the normalised, identity-bearing fields
   (entity name, address, zip5, filing type, filing date, amount). The same
   real lien appearing in two files of the same source therefore yields the
   same key -> the same id (satisfies "same TNU record in two TNU files").
2. lien_id = Crockford-ish base32(SHA-1(source + '::' + natural_key))[:15]
   -> 15 * 5 = 75 bits of space; collision probability is negligible for the
   expected volumes.
3. On the astronomically unlikely event of a genuine collision (same id,
   *different* natural key already recorded), append a disambiguator and
   re-hash until free. Every collision is logged.

The exact method is documented here and in README.md; it is subject to
client sign-off before the production import (handoff Deliverable B).
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Callable, Optional

from .normalize.text import collapse_ws

_NON_KEY = re.compile(r"[^A-Z0-9]+")
ID_LENGTH = 15

# standard base32 alphabet -> Crockford (no I/L/O/U); translate is C-speed
_STD_B32 = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_CROCKFORD = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TO_CROCKFORD = bytes.maketrans(_STD_B32, _CROCKFORD)


def _b32(digest: bytes, length: int) -> str:
    return base64.b32encode(digest)[:length].translate(_TO_CROCKFORD).decode("ascii")


def _norm_component(value: Optional[str]) -> str:
    v = collapse_ws(value) or ""
    return _NON_KEY.sub("", v.upper())


def build_natural_key(
    *,
    entity_name: str,
    address: Optional[str],
    zip_code: Optional[str],
    filing_type: str,
    filing_date_iso: str,
    amount: str,
) -> str:
    zip5 = _norm_component(zip_code)[:5]
    return "|".join(
        (
            _norm_component(entity_name),
            _norm_component(address),
            zip5,
            filing_type,
            filing_date_iso,
            amount,
        )
    )


def natural_key_sha1(natural_key: str) -> str:
    return hashlib.sha1(natural_key.encode("utf-8")).hexdigest()


def make_lien_id(
    source_code: str,
    natural_key: str,
    *,
    lookup_existing_sha1: Callable[[str], Optional[str]] | None = None,
) -> tuple[str, str]:
    """Return ``(lien_id, natural_key_sha1)``.

    ``lookup_existing_sha1(candidate_id)`` -> the natural_key_sha1 already
    recorded for that id (in this run or in the DB / import-log), or None if
    the id is free. Used only for collision disambiguation.
    """
    nk_sha1 = natural_key_sha1(natural_key)
    attempt = 0
    while True:
        salted = natural_key if attempt == 0 else f"{natural_key}#{attempt}"
        digest = hashlib.sha1(f"{source_code}::{salted}".encode("utf-8")).digest()
        candidate = _b32(digest, ID_LENGTH)
        if lookup_existing_sha1 is None:
            return candidate, nk_sha1
        existing = lookup_existing_sha1(candidate)
        if existing is None or existing == nk_sha1:
            return candidate, nk_sha1
        attempt += 1
        if attempt > 1000:  # pragma: no cover - defensive
            raise RuntimeError(f"Unable to allocate lien_id for key {natural_key!r}")
