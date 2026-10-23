"""Benchmark-owned temporal scoring policy."""

from __future__ import annotations

from collections.abc import Sequence

from infinity_context_benchmarks.rerank_policy.common import _reason_codes
from infinity_context_benchmarks.rerank_policy.contracts import (
    RerankPolicyContribution,
    RerankPolicyFeatures,
)


class TemporalPolicy:
    name = "TemporalPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        stale_only_current_state = _stale_only_current_state_evidence(features)
        sequence_direction = _temporal_sequence_direction(features)
        sequence_query_direction = _temporal_sequence_query_direction(features.temporal_query_terms)
        sequence_direction_conflict = _temporal_sequence_direction_conflict(
            query_direction=sequence_query_direction,
            evidence_direction=sequence_direction,
        )
        temporal_boost, temporal_reason = _typed_temporal_boost(features)
        sequence_boost = (
            0.055
            if features.is_temporal_query
            and features.has_temporal_sequence_surface
            and not sequence_direction_conflict
            else 0.0
        )
        sequence_penalty = -0.045 if sequence_direction_conflict else 0.0
        currentness_boost = (
            0.04
            if features.is_temporal_query
            and features.currentness_surface
            and (features.entity_hits or features.relation_hits)
            else 0.0
        )
        role_support_boost = 0.055 if _temporal_role_support_eligible(features) else 0.0
        return RerankPolicyContribution(
            policy=self.name,
            score=(
                temporal_boost
                + sequence_boost
                + currentness_boost
                + role_support_boost
                + sequence_penalty
            ),
            signals={
                "benchmark_time_intent_kind": features.time_intent_kind,
                "benchmark_temporal_query_roles": list(features.query_roles),
                "benchmark_temporal_query_terms": list(features.temporal_query_terms),
                "benchmark_temporal_sequence_query_direction": (sequence_query_direction),
                "benchmark_temporal_sequence_direction": sequence_direction,
                "benchmark_temporal_sequence_direction_conflict": (sequence_direction_conflict),
                "benchmark_temporal_sequence_direction_penalty": round(
                    sequence_penalty,
                    6,
                ),
                "benchmark_current_state_query": features.current_state_query,
                "benchmark_stale_only_current_state_evidence": (stale_only_current_state),
                "benchmark_temporal_text_boost": round(temporal_boost, 6),
                "benchmark_temporal_sequence_boost": round(sequence_boost, 6),
                "benchmark_currentness_support_boost": round(
                    currentness_boost,
                    6,
                ),
                "benchmark_temporal_role_support_boost": round(
                    role_support_boost,
                    6,
                ),
                "benchmark_typed_temporal_reason": temporal_reason,
                "benchmark_has_duration_surface": features.has_duration_surface,
                "benchmark_has_relative_time_surface": (features.has_relative_time_surface),
                "benchmark_has_explicit_time_surface": (features.has_explicit_time_surface),
                "benchmark_has_explicit_time_content_surface": (
                    features.has_explicit_time_content_surface
                ),
                "benchmark_has_temporal_sequence_surface": (features.has_temporal_sequence_surface),
            },
            reason_codes=(
                *_reason_codes(
                    (temporal_reason, temporal_boost),
                    (
                        f"time_intent:{features.time_intent_kind}",
                        float(
                            features.is_temporal_query
                            and bool(features.time_intent_kind)
                            and features.time_intent_kind != "none"
                        ),
                    ),
                ),
                *_reason_codes(
                    ("temporal_sequence", sequence_boost),
                    ("currentness_support", currentness_boost),
                    ("temporal_query_role_support", role_support_boost),
                ),
                *(("temporal_sequence_direction_conflict",) if sequence_direction_conflict else ()),
            ),
        )


def _typed_temporal_boost(features: RerankPolicyFeatures) -> tuple[float, str]:
    if not features.is_temporal_query:
        return 0.0, "not_temporal_query"
    if _stale_only_current_state_evidence(features):
        return 0.0, "stale_only_current_state_evidence"
    generic_temporal = _has_content_temporal_evidence(features)
    time_kind = features.time_intent_kind
    if time_kind == "duration":
        if features.has_duration_surface:
            return 0.085, "duration_temporal_evidence"
        return (
            (0.025, "duration_temporal_evidence_partial")
            if generic_temporal
            else (
                0.0,
                "missing_duration_temporal_evidence",
            )
        )
    if time_kind == "relative_time":
        if features.has_relative_time_surface:
            return 0.08, "relative_temporal_evidence"
        if features.has_explicit_time_content_surface:
            return 0.08, "relative_temporal_explicit_answer_evidence"
        return (
            (0.03, "relative_temporal_evidence_partial")
            if generic_temporal
            else (
                0.0,
                "missing_relative_temporal_evidence",
            )
        )
    if time_kind == "explicit_time":
        if features.has_explicit_time_content_surface:
            return 0.08, "explicit_temporal_evidence"
        return (
            (0.03, "explicit_temporal_evidence_partial")
            if generic_temporal
            else (
                0.0,
                "missing_explicit_temporal_evidence",
            )
        )
    if time_kind == "temporal_sequence":
        if _temporal_sequence_direction_conflict(
            query_direction=_temporal_sequence_query_direction(features.temporal_query_terms),
            evidence_direction=_temporal_sequence_direction(features),
        ):
            return 0.0, "conflicting_sequence_temporal_evidence"
        if features.has_temporal_sequence_surface:
            return 0.08, "sequence_temporal_evidence"
        return (
            (0.025, "sequence_temporal_evidence_partial")
            if generic_temporal
            else (
                0.0,
                "missing_sequence_temporal_evidence",
            )
        )
    if generic_temporal:
        return 0.07, "generic_temporal_evidence"
    return 0.0, "missing_temporal_evidence"


def _temporal_sequence_direction(features: RerankPolicyFeatures) -> str:
    direction = str(getattr(features, "temporal_sequence_direction", "") or "")
    return direction.casefold().strip()


def _temporal_sequence_query_direction(temporal_query_terms: Sequence[str]) -> str:
    terms = {
        str(term).casefold().strip()
        for term in temporal_query_terms
        if str(term).casefold().strip()
    }
    if terms & {"after", "afterward", "afterwards", "since"}:
        return "after"
    if terms & {"before", "beforehand", "until", "prior"}:
        return "before"
    return ""


def _temporal_sequence_direction_conflict(
    *,
    query_direction: str,
    evidence_direction: str,
) -> bool:
    return bool(
        query_direction in {"before", "after"}
        and evidence_direction in {"before", "after"}
        and query_direction != evidence_direction
    )


def _temporal_role_support_eligible(features: RerankPolicyFeatures) -> bool:
    if not features.is_temporal_query:
        return False
    if _stale_only_current_state_evidence(features):
        return False
    if _temporal_sequence_direction_conflict(
        query_direction=_temporal_sequence_query_direction(features.temporal_query_terms),
        evidence_direction=_temporal_sequence_direction(features),
    ):
        return False
    if not _has_temporal_query_role(features.query_roles):
        return False
    if not (features.entity_hits or features.speaker_hits or len(features.overlap_terms) >= 2):
        return False
    return bool(
        features.has_duration_surface
        or features.has_relative_time_surface
        or features.has_explicit_time_content_surface
        or features.has_temporal_sequence_surface
    )


def _has_content_temporal_evidence(features: RerankPolicyFeatures) -> bool:
    return bool(
        features.has_duration_surface
        or features.has_relative_time_surface
        or features.has_explicit_time_content_surface
        or features.has_temporal_sequence_surface
    )


def _stale_only_current_state_evidence(features: RerankPolicyFeatures) -> bool:
    return bool(
        features.current_state_query and features.stale_surface and not features.currentness_surface
    )


def _has_temporal_query_role(query_roles: Sequence[str]) -> bool:
    return any(
        role
        in {
            "temporal_support",
            "duration_temporal_support",
            "explicit_temporal_support",
            "relative_temporal_support",
            "temporal_sequence_support",
            "visual_temporal_support",
        }
        for role in query_roles
    )
