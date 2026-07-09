"""Query decomposition DTO contracts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryDecomposition:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryDecompositionPlan:
    original_query: str
    decompositions: tuple[QueryDecomposition, ...]

    @property
    def empty(self) -> bool:
        return not self.decompositions

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_decomposition_status": "empty" if self.empty else "available",
            "query_decomposition_count": len(self.decompositions),
            "query_decomposition_reasons": [item.reason for item in self.decompositions],
        }
