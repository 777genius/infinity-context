"""Requirement coverage signals for deterministic context ranking."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem


@dataclass(frozen=True)
class RequirementCoverageSignals:
    ratio: float
    requested_anchor_kinds: frozenset[str]
    covered_anchor_kinds: frozenset[str]
    missing_anchor_kinds: frozenset[str]
    requested_modalities: frozenset[str]
    missing_modalities: frozenset[str]
    requested_evidence_features: frozenset[str]
    missing_evidence_features: frozenset[str]
    requested_answer_shapes: frozenset[str]
    covered_answer_shapes: frozenset[str]
    missing_answer_shapes: frozenset[str]

    @property
    def answer_shape_ratio(self) -> float:
        if not self.requested_answer_shapes:
            return 0.0
        return len(self.covered_answer_shapes) / len(self.requested_answer_shapes)


def item_requirement_coverage_signals(
    item: ContextItem,
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    requested_total: int,
) -> RequirementCoverageSignals:
    if requested_total <= 0:
        return RequirementCoverageSignals(
            ratio=0.0,
            requested_anchor_kinds=frozenset(),
            covered_anchor_kinds=frozenset(),
            missing_anchor_kinds=frozenset(),
            requested_modalities=frozenset(),
            missing_modalities=frozenset(),
            requested_evidence_features=frozenset(),
            missing_evidence_features=frozenset(),
            requested_answer_shapes=frozenset(),
            covered_answer_shapes=frozenset(),
            missing_answer_shapes=frozenset(),
        )
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(item,),
    )
    requested_anchor_kinds = _coverage_value_set(coverage.get("requested_anchor_kinds"))
    covered_anchor_kinds = _coverage_value_set(coverage.get("covered_anchor_kinds"))
    missing_anchor_kinds = _coverage_value_set(coverage.get("missing_anchor_kinds"))
    requested_modalities = _coverage_value_set(coverage.get("requested_modalities"))
    missing_modalities = _coverage_value_set(coverage.get("missing_modalities"))
    requested_evidence_features = _coverage_value_set(
        coverage.get("requested_evidence_features")
    )
    missing_evidence_features = _coverage_value_set(coverage.get("missing_evidence_features"))
    requested_answer_shapes = _coverage_value_set(coverage.get("requested_answer_shapes"))
    covered_answer_shapes = _coverage_value_set(coverage.get("covered_answer_shapes"))
    missing_answer_shapes = _coverage_value_set(coverage.get("missing_answer_shapes"))
    return RequirementCoverageSignals(
        ratio=_coverage_ratio(coverage.get("coverage_ratio")),
        requested_anchor_kinds=requested_anchor_kinds,
        covered_anchor_kinds=requested_anchor_kinds & covered_anchor_kinds,
        missing_anchor_kinds=requested_anchor_kinds & missing_anchor_kinds,
        requested_modalities=requested_modalities,
        missing_modalities=requested_modalities & missing_modalities,
        requested_evidence_features=requested_evidence_features,
        missing_evidence_features=requested_evidence_features & missing_evidence_features,
        requested_answer_shapes=requested_answer_shapes,
        covered_answer_shapes=requested_answer_shapes & covered_answer_shapes,
        missing_answer_shapes=requested_answer_shapes & missing_answer_shapes,
    )


def _coverage_ratio(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return min(1.0, max(0.0, float(value)))
    return 0.0


def _coverage_value_set(value: object) -> frozenset[str]:
    if not isinstance(value, list | tuple):
        return frozenset()
    return frozenset(
        text for item in value if isinstance(item, str) and (text := item.strip().casefold())
    )
