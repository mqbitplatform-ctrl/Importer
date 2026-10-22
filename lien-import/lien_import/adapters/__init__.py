"""Source-format adapters. Add a new CSV format by adding one module here
and registering its class in ``REGISTRY``."""

from __future__ import annotations

from .att_ess import AttEssAdapter
from .base import SourceAdapter, find_adapter
from .tnu_combined import TnuCombinedAdapter
from .tnu_starter import TnuStarterAdapter

REGISTRY: list[type[SourceAdapter]] = [
    AttEssAdapter,
    TnuStarterAdapter,
    TnuCombinedAdapter,
]

__all__ = [
    "SourceAdapter",
    "REGISTRY",
    "find_adapter",
    "AttEssAdapter",
    "TnuCombinedAdapter",
    "TnuStarterAdapter",
]
