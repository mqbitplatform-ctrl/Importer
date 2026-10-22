"""FAT selection criteria + SQL predicate builder.

From handoff section 16, the current manual FAT pull selects liens by:
  * user index 61379            -> the Zairmail customer (Free America Tax)
  * Federal lien                -> lien_filing_type = 'F'
  * Individual                  -> lien_entity_type = 'I'
  * lien amount >= $5,000       -> lien_amount >= 5000
  * not already assigned to FAT -> NOT EXISTS in liens_custom_data for
                                   lcdata_user_index = 61379

"The consolidated lien database should allow the same selection logic to
operate across the additional lien sources" - so by default no lien_source
filter is applied (LN + TN + ES all considered).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..config import FatConfig


@dataclass
class FatCriteria:
    user_index: str
    filing_type: str = "F"
    entity_type: str = "I"
    min_amount: Decimal = Decimal("5000")
    sources: list[str] = field(default_factory=list)  # empty = all
    exclude_assigned: bool = True

    @classmethod
    def from_config(cls, fc: FatConfig) -> "FatCriteria":
        return cls(
            user_index=fc.user_index,
            filing_type=fc.filing_type,
            entity_type=fc.entity_type,
            min_amount=Decimal(str(fc.min_amount)),
            sources=list(fc.sources),
        )

    def where(self, liens_alias: str = "l", assignment_table: str = "liens_custom_data"):
        """Return ``(sql_fragment, params)`` for a WHERE clause on the liens table.

        "Not already assigned" is checked against the EXISTING assignment
        table in zm_dba - ``liens_custom_data``, keyed by customer
        ``lcdata_user_index`` (61379 = Free America Tax). Verified on the live
        data: all 69,000 current FAT assignments live there, and every one is
        Federal / Individual / >= $5,000.
        """
        parts = [
            f"{liens_alias}.lien_filing_type = %s",
            f"{liens_alias}.lien_entity_type = %s",
            f"{liens_alias}.lien_amount >= %s",
        ]
        params: list = [self.filing_type, self.entity_type, str(self.min_amount)]

        if self.sources:
            placeholders = ",".join(["%s"] * len(self.sources))
            parts.append(f"{liens_alias}.lien_source IN ({placeholders})")
            params.extend(self.sources)

        if self.exclude_assigned:
            parts.append(
                f"NOT EXISTS (SELECT 1 FROM `{assignment_table}` a "
                f"WHERE a.lcdata_lien_source = {liens_alias}.lien_source "
                f"AND a.lcdata_lien_id = {liens_alias}.lien_id "
                f"AND a.lcdata_user_index = %s)"
            )
            params.append(int(self.user_index))
        return " AND ".join(parts), params

    def to_dict(self) -> dict:
        return {
            "user_index": self.user_index,
            "filing_type": self.filing_type,
            "entity_type": self.entity_type,
            "min_amount": str(self.min_amount),
            "sources": self.sources or "ALL",
            "exclude_assigned": self.exclude_assigned,
        }
