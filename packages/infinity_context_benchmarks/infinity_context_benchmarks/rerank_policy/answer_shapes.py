"""Benchmark-owned answer shapes scoring policy."""

from __future__ import annotations

from infinity_context_benchmarks.rerank_policy.common import (
    _has_missing_required_answer_evidence,
    _has_precise_or_unmeasured_source_provenance,
    _reason_codes,
)
from infinity_context_benchmarks.rerank_policy.contracts import (
    RerankPolicyContribution,
    RerankPolicyFeatures,
)

_COUNT_LIST_GENERIC_RELATION_TERMS = frozenset(
    {
        "amount",
        "count",
        "counts",
        "have",
        "had",
        "has",
        "how",
        "include",
        "included",
        "includes",
        "including",
        "item",
        "items",
        "list",
        "many",
        "much",
        "name",
        "named",
        "names",
        "number",
        "numbers",
        "quantity",
        "thing",
        "things",
        "time",
        "times",
        "total",
        "totals",
    }
)


class AnswerabilityPolicy:
    name = "AnswerabilityPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        eligible = _answerability_boost_eligible(features)
        boost = _answerability_boost(features.answerability_score) if eligible else 0.0
        return RerankPolicyContribution(
            policy=self.name,
            score=boost,
            signals={
                "benchmark_answerability_score": round(
                    features.answerability_score,
                    6,
                ),
                "benchmark_answerability_boost": round(boost, 6),
                "benchmark_answerability_boost_eligible": eligible,
                "benchmark_answerability_reason_codes": list(features.answerability_reason_codes),
            },
            reason_codes=tuple(
                reason
                for reason in features.answerability_reason_codes
                if reason
                in {
                    "high_answerability",
                    "medium_answerability",
                    "direct_provenance",
                    "source_provenance",
                    "intent_satisfied",
                    "intent_partial",
                }
            ),
        )


class ValueAnswerShapePolicy:
    name = "ValueAnswerShapePolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        value_needed = "value_support" in set(features.evidence_need)
        value_shape_hit = "quantity_dollar" in set(features.covered_answer_unit_shapes)
        grounded = bool(
            features.entity_hits
            or features.speaker_hits
            or len(features.overlap_terms) >= 2
            or not features.query_has_entities
        )
        precise_provenance = _has_precise_or_unmeasured_source_provenance(features)
        evidence_boost = (
            0.09 if value_needed and value_shape_hit and grounded and precise_provenance else 0.0
        )
        role_boost = (
            0.035 if evidence_boost > 0 and "value_support" in set(features.query_roles) else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=evidence_boost + role_boost,
            signals={
                "benchmark_value_answer_shape_boost": round(evidence_boost, 6),
                "benchmark_value_query_role_boost": round(role_boost, 6),
                "benchmark_value_answer_shape_hit": value_shape_hit,
                "benchmark_value_answer_grounded": grounded,
                "benchmark_value_precise_provenance": precise_provenance,
            },
            reason_codes=(
                *_reason_codes(("value_answer_shape", evidence_boost)),
                *_reason_codes(("value_query_role_support", role_boost)),
            ),
        )


class CountListAnswerShapePolicy:
    name = "CountListAnswerShapePolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        evidence_needs = set(features.evidence_need)
        query_roles = set(features.query_roles)
        grounded = bool(
            features.entity_hits
            or features.speaker_hits
            or len(features.overlap_terms) >= 2
            or not features.query_has_entities
        )
        precise_provenance = _has_precise_or_unmeasured_source_provenance(features)
        count_needed = "count_support" in evidence_needs
        list_needed = "list_support" in evidence_needs
        multi_item_evidence = features.list_item_count >= 2
        subject_grounded = _has_count_list_subject_grounding(features)
        count_evidence_boost = (
            0.09
            if count_needed
            and features.exact_count_evidence
            and grounded
            and subject_grounded
            and precise_provenance
            else 0.06
            if count_needed
            and multi_item_evidence
            and grounded
            and subject_grounded
            and precise_provenance
            else 0.0
        )
        list_evidence_boost = (
            0.09
            if list_needed
            and multi_item_evidence
            and grounded
            and subject_grounded
            and precise_provenance
            else 0.0
        )
        role_boost = (
            0.035
            if (
                (count_evidence_boost > 0 and "count_support" in query_roles)
                or (list_evidence_boost > 0 and "list_support" in query_roles)
            )
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=count_evidence_boost + list_evidence_boost + role_boost,
            signals={
                "benchmark_count_answer_shape_boost": round(
                    count_evidence_boost,
                    6,
                ),
                "benchmark_list_answer_shape_boost": round(list_evidence_boost, 6),
                "benchmark_count_list_query_role_boost": round(role_boost, 6),
                "benchmark_exact_count_evidence": features.exact_count_evidence,
                "benchmark_list_item_count": features.list_item_count,
                "benchmark_count_list_answer_grounded": grounded,
                "benchmark_count_list_subject_grounded": subject_grounded,
                "benchmark_count_list_precise_provenance": precise_provenance,
            },
            reason_codes=(
                *_reason_codes(("count_answer_shape", count_evidence_boost)),
                *_reason_codes(("list_answer_shape", list_evidence_boost)),
                *_reason_codes(("count_list_query_role_support", role_boost)),
            ),
        )


def _has_count_list_subject_grounding(features: RerankPolicyFeatures) -> bool:
    if not features.query_has_entities:
        return True
    if features.high_signal_relation_hit_count > 0:
        return True
    relation_hits = {
        hit.casefold()
        for hit in features.relation_hits
        if hit.casefold() not in _COUNT_LIST_GENERIC_RELATION_TERMS
    }
    if relation_hits:
        return True
    entity_hits = {hit.casefold() for hit in (*features.entity_hits, *features.speaker_hits)}
    target_overlap = {
        term.casefold()
        for term in features.overlap_terms
        if term.casefold() not in _COUNT_LIST_GENERIC_RELATION_TERMS
        and term.casefold() not in entity_hits
    }
    return bool(target_overlap)


def _answerability_boost(score: float) -> float:
    if score >= 0.86:
        return 0.1
    if score >= 0.74:
        return 0.07
    if score >= 0.58:
        return 0.035
    return 0.0


def _answerability_boost_eligible(features: RerankPolicyFeatures) -> bool:
    if _has_missing_required_answer_evidence(features):
        return False
    if not features.relation_terms:
        return True
    if _typed_category_answerability_grounded(features):
        return True
    return len(features.relation_hits) >= 2 or features.high_signal_relation_hit_count > 0


def _typed_category_answerability_grounded(features: RerankPolicyFeatures) -> bool:
    category_hits = set(features.relation_category_hits)
    if not category_hits:
        return False
    if "communication" in category_hits and features.query_has_entities:
        if features.speaker_hits:
            return True
        category_hits.discard("communication")
    if not category_hits:
        return False
    return bool(features.entity_hits or features.speaker_hits or not features.query_has_entities)
