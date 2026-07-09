"""DTO contracts for query anchor intent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_core.application.context_query_intent_common import _bounded_unique
from infinity_context_core.application.context_query_intent_keys import (
    _event_type_identity_keys,
    _temporal_identity_keys,
)
from infinity_context_core.domain.entities import MemoryAnchorKind


@dataclass(frozen=True)
class QueryAnchorHint:
    kind: MemoryAnchorKind
    canonical_key: str
    label: str
    reason: str
    metadata: Mapping[str, object]

@dataclass(frozen=True)
class QueryAnchorIntent:
    hints: tuple[QueryAnchorHint, ...]

    @property
    def empty(self) -> bool:
        return not self.hints

    def keys_for_kind(self, kind: MemoryAnchorKind) -> frozenset[str]:
        return frozenset(hint.canonical_key for hint in self.hints if hint.kind == kind)

    def temporal_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hint in self.hints:
            if hint.kind != MemoryAnchorKind.EVENT:
                continue
            keys.update(_temporal_identity_keys(hint.metadata))
        return frozenset(keys)

    def event_type_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hint in self.hints:
            if hint.kind != MemoryAnchorKind.EVENT:
                continue
            keys.update(_event_type_identity_keys(hint.metadata))
        return frozenset(keys)

    def diagnostics(self) -> dict[str, object]:
        counts = {
            kind.value: sum(1 for hint in self.hints if hint.kind == kind)
            for kind in MemoryAnchorKind
        }
        return {
            "query_anchor_intent_status": "empty" if self.empty else "available",
            "query_anchor_hint_count": len(self.hints),
            "query_anchor_person_hint_count": counts[MemoryAnchorKind.PERSON.value],
            "query_anchor_event_hint_count": counts[MemoryAnchorKind.EVENT.value],
            "query_anchor_project_hint_count": counts[MemoryAnchorKind.PROJECT.value],
            "query_anchor_organization_hint_count": counts[MemoryAnchorKind.ORGANIZATION.value],
            "query_anchor_temporal_hint_count": len(self.temporal_keys()),
            "query_anchor_event_type_hint_count": len(self.event_type_keys()),
            "query_anchor_hint_reasons": _bounded_unique(hint.reason for hint in self.hints),
        }

@dataclass(frozen=True)
class QueryAnchorMatch:
    score_boost: float
    reasons: tuple[str, ...]
    matched_keys: tuple[str, ...]

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_anchor_match_score_boost": self.score_boost,
            "query_anchor_match_reasons": list(self.reasons),
            "query_anchor_match_keys": list(self.matched_keys),
        }

@dataclass(frozen=True)
class QueryAnchorLookupKey:
    kind: MemoryAnchorKind
    normalized_key: str
