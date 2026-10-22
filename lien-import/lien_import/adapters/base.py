"""Adapter contract + resolver."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..models import MappedRow
from ..normalize.text import canon_header


class SourceAdapter(ABC):
    #: 'ES' or 'TN'
    source_code: str = ""
    #: stable short name, e.g. 'att_ess'
    format_name: str = ""
    #: canonical headers that must all be present for this adapter to claim a file
    required_headers: frozenset[str] = frozenset()
    #: canonical headers that must NOT be present (disambiguates same-source formats)
    forbidden_headers: frozenset[str] = frozenset()

    @classmethod
    def matches(cls, canon_headers: Iterable[str]) -> bool:
        hs = set(canon_headers)
        if not cls.required_headers.issubset(hs):
            return False
        if cls.forbidden_headers & hs:
            return False
        return True

    @abstractmethod
    def map_row(self, canon: dict[str, str], file: str, row_num: int, raw: dict[str, str]) -> MappedRow:
        """Extract raw candidate values from one canonicalised CSV row."""


def _canon_headers(headers: Iterable[str]) -> set[str]:
    return {canon_header(h) for h in headers if h}


def find_adapter(
    source_code: str,
    headers: Iterable[str],
    registry: list[type[SourceAdapter]],
) -> SourceAdapter | None:
    """Return an adapter instance for *source_code* whose signature matches
    *headers*, or None."""
    canon = _canon_headers(headers)
    for cls in registry:
        if cls.source_code != source_code:
            continue
        if cls.matches(canon):
            return cls()
    return None
