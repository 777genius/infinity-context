"""Review-gated semantic linking policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from memo_stack_core.application.dto import ContextLinkCandidate
from memo_stack_core.application.safe_payload import safe_metadata_text

POLICY_VERSION = "context-link-policy-v1"
MAX_SUGGESTIONS_PER_SOURCE = 10
MIN_REVIEW_SCORE = 40.0
MIN_STRONG_SIGNAL_REVIEW_SCORE = 55.0
AUTO_APPROVE_ELIGIBLE_SCORE = 92.0
MAX_POLICY_CANDIDATES_CONSIDERED = 120
MAX_DENIED_DIAGNOSTIC_ITEMS = 8
MAX_REASON_CODES = 12
MAX_DENIED_DIAGNOSTIC_TEXT_CHARS = 160

_AUTO_APPROVE_TARGET_TYPES = frozenset({"anchor", "fact", "episode", "document", "chunk"})
_REVIEW_BLOCKED_TARGET_TYPES = frozenset({"suggestion"})
_ALLOWED_RELATION_TYPES = frozenset(
    {
        "related_to",
        "supports",
        "mentions",
        "evidence_of",
        "duplicates",
        "supersedes",
        "contradicts",
    }
)
_HIGH_IMPACT_RELATION_TYPES = frozenset({"supersedes", "contradicts", "duplicates"})
_EVIDENCE_RELATION_TYPES = frozenset({"supports", "evidence_of"})
_REASON_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_BASE_STRONG_REVIEW_SIGNAL_CODES = frozenset(
    {
        "text_match",
        "temporal_intent_match",
        "explicit_project_reference",
        "known_project_tool_reference",
        "event_phrase",
        "person_name",
        "organization_reference",
        "rule_signal",
    }
)
_HIGH_IMPACT_RELATION_SIGNAL_CODES = {
    "supersedes": frozenset(
        {
            "temporal_intent_match",
            "supersedes_signal",
            "explicit_user_update",
        }
    ),
    "contradicts": frozenset(
        {
            "contradicts_signal",
            "explicit_correction",
        }
    ),
    "duplicates": frozenset(
        {
            "duplicates_signal",
            "exact_duplicate",
            "semantic_duplicate",
            "same_kind",
            "same_source_hash",
            "equivalent_text",
        }
    ),
}
_HIGH_IMPACT_SIGNAL_CODES = frozenset(
    code
    for relation_signal_codes in _HIGH_IMPACT_RELATION_SIGNAL_CODES.values()
    for code in relation_signal_codes
)
_STRONG_REVIEW_SIGNAL_CODES = _BASE_STRONG_REVIEW_SIGNAL_CODES | _HIGH_IMPACT_SIGNAL_CODES
_AUTO_APPROVE_SIGNAL_CODES = _STRONG_REVIEW_SIGNAL_CODES - frozenset({"recent_context"})
_MENTION_RELATION_SIGNAL_CODES = frozenset(
    {
        "text_match",
        "person_name",
        "organization_reference",
        "explicit_project_reference",
        "known_project_tool_reference",
        "event_phrase",
    }
)
MIN_AUTO_APPROVE_INDEPENDENT_SIGNALS = 2


@dataclass(frozen=True)
class ContextLinkPolicyDecision:
    outcome: str
    relation_type: str
    confidence: str
    reason_codes: tuple[str, ...]
    requires_review: bool
    auto_approve_eligible: bool


@dataclass(frozen=True)
class ContextLinkPolicyResult:
    candidates: tuple[ContextLinkCandidate, ...]
    diagnostics: dict[str, object]


def apply_context_link_policy(
    candidates: tuple[ContextLinkCandidate, ...],
    *,
    limit: int,
    persist: bool,
) -> ContextLinkPolicyResult:
    max_suggestions = min(max(1, limit), MAX_SUGGESTIONS_PER_SOURCE if persist else max(1, limit))
    accepted: list[ContextLinkCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    denied_count = 0
    duplicate_count = 0
    auto_eligible_count = 0
    needs_review_count = 0
    source_risk_review_count = 0
    denied_reason_counts: dict[str, int] = {}
    denied_candidates: list[dict[str, object]] = []
    candidate_pool = candidates[:MAX_POLICY_CANDIDATES_CONSIDERED]
    processed_count = 0

    for candidate in candidate_pool:
        processed_count += 1
        decision = decide_context_link_candidate(candidate)
        if decision.outcome == "deny":
            denied_count += 1
            for code in decision.reason_codes:
                denied_reason_counts[code] = denied_reason_counts.get(code, 0) + 1
            if len(denied_candidates) < MAX_DENIED_DIAGNOSTIC_ITEMS:
                denied_candidates.append(
                    {
                        "target_type": _safe_denied_diagnostic_text(candidate.target_type),
                        "target_id": _safe_denied_diagnostic_text(candidate.target_id),
                        "score": round(candidate.score, 2),
                        "reason_codes": list(decision.reason_codes),
                    }
                )
            continue
        key = (candidate.target_type, candidate.target_id, decision.relation_type)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        accepted.append(_with_policy_metadata(candidate, decision))
        if decision.auto_approve_eligible:
            auto_eligible_count += 1
        else:
            needs_review_count += 1
        if _requires_source_risk_review(candidate):
            source_risk_review_count += 1
        if len(accepted) >= max_suggestions:
            break

    return ContextLinkPolicyResult(
        candidates=tuple(accepted),
        diagnostics={
            "link_policy_version": POLICY_VERSION,
            "link_policy_candidates_received": len(candidates),
            "link_policy_candidates_considered": processed_count,
            "link_policy_candidate_pool_size": len(candidate_pool),
            "link_policy_candidate_considered_cap": MAX_POLICY_CANDIDATES_CONSIDERED,
            "link_policy_candidates_truncated": len(candidate_pool) < len(candidates),
            "link_policy_candidates_unprocessed_after_limit": max(
                0,
                len(candidate_pool) - processed_count,
            ),
            "link_policy_stopped_after_return_limit": (
                processed_count < len(candidate_pool) and len(accepted) >= max_suggestions
            ),
            "link_policy_candidates_returned": len(accepted),
            "link_policy_denied_count": denied_count,
            "link_policy_duplicate_suppressed_count": duplicate_count,
            "link_policy_auto_approve_eligible_count": auto_eligible_count,
            "link_policy_needs_review_count": needs_review_count,
            "link_policy_pending_review_count": needs_review_count,
            "link_policy_source_risk_review_count": source_risk_review_count,
            "link_policy_decision_counts": {
                "deny": denied_count,
                "duplicate_suppressed": duplicate_count,
                "auto_approve_candidate": auto_eligible_count,
                "pending_review": needs_review_count,
                "needs_review": needs_review_count,
            },
            "link_policy_max_suggestions_per_source": max_suggestions,
            "link_policy_denied_reason_counts": denied_reason_counts,
            "link_policy_denied_candidates": denied_candidates,
        },
    )


def decide_context_link_candidate(candidate: ContextLinkCandidate) -> ContextLinkPolicyDecision:
    reason_codes = _reason_codes(candidate)
    relation_type, relation_error = _relation_type_for_candidate(candidate)
    deny_codes = _deny_reason_codes(candidate, reason_codes, relation_type, relation_error)
    if deny_codes:
        return ContextLinkPolicyDecision(
            outcome="deny",
            relation_type=relation_type,
            confidence="low",
            reason_codes=deny_codes,
            requires_review=True,
            auto_approve_eligible=False,
        )

    source_risk_review = _requires_source_risk_review(candidate)
    confidence = _confidence_for_score(candidate.score)
    if source_risk_review and confidence == "high":
        confidence = "medium"
    auto_approve_signal_count = _auto_approve_signal_count(reason_codes)
    auto_approve_eligible = (
        not source_risk_review
        and candidate.score >= AUTO_APPROVE_ELIGIBLE_SCORE
        and candidate.target_type in _AUTO_APPROVE_TARGET_TYPES
        and relation_type not in _HIGH_IMPACT_RELATION_TYPES
        and "text_match" in reason_codes
        and "recent_context" not in reason_codes
        and auto_approve_signal_count >= MIN_AUTO_APPROVE_INDEPENDENT_SIGNALS
    )
    review_blocked = candidate.target_type in _REVIEW_BLOCKED_TARGET_TYPES
    outcome = (
        "auto_approve_candidate"
        if auto_approve_eligible and not review_blocked
        else "needs_review"
    )
    decision_codes = ["score_threshold_met", *reason_codes]
    if review_blocked:
        decision_codes.append("review_required_target_type")
    if (
        candidate.score >= AUTO_APPROVE_ELIGIBLE_SCORE
        and candidate.target_type in _AUTO_APPROVE_TARGET_TYPES
        and relation_type not in _HIGH_IMPACT_RELATION_TYPES
        and "text_match" in reason_codes
        and "recent_context" not in reason_codes
        and auto_approve_signal_count < MIN_AUTO_APPROVE_INDEPENDENT_SIGNALS
    ):
        decision_codes.append("insufficient_independent_signals")
    if auto_approve_eligible and not review_blocked:
        decision_codes.append("auto_approve_eligible")
    else:
        decision_codes.append("review_required")
    for review_reason in _source_review_gate_reasons(candidate):
        decision_codes.append(_source_review_reason_code(review_reason))
    return ContextLinkPolicyDecision(
        outcome=outcome,
        relation_type=relation_type,
        confidence=confidence,
        reason_codes=tuple(dict.fromkeys(decision_codes)),
        requires_review=True,
        auto_approve_eligible=auto_approve_eligible and not review_blocked,
    )


def policy_confidence_for_candidate(candidate: ContextLinkCandidate) -> str | None:
    metadata = candidate.metadata or {}
    value = metadata.get("policy_confidence")
    return str(value) if value in {"low", "medium", "high"} else None


def policy_relation_type_for_candidate(candidate: ContextLinkCandidate) -> str | None:
    metadata = candidate.metadata or {}
    value = metadata.get("policy_relation_type")
    return str(value) if value in _ALLOWED_RELATION_TYPES else None


def _with_policy_metadata(
    candidate: ContextLinkCandidate,
    decision: ContextLinkPolicyDecision,
) -> ContextLinkCandidate:
    metadata = dict(candidate.metadata or {})
    policy_metadata: dict[str, object] = {
        "suggestion_policy_version": POLICY_VERSION,
        "policy_decision": decision.outcome,
        "policy_decision_canonical": _canonical_policy_decision(decision.outcome),
        "policy_relation_type": decision.relation_type,
        "policy_confidence": decision.confidence,
        "policy_reason_codes": list(decision.reason_codes),
        "review_gate": "required",
        "auto_approve_eligible": decision.auto_approve_eligible,
    }
    review_gate_reasons = _source_review_gate_reasons(candidate)
    if review_gate_reasons:
        policy_metadata["review_gate_reason"] = review_gate_reasons[0]
        policy_metadata["review_gate_reasons"] = list(review_gate_reasons)
    metadata.update(policy_metadata)
    return replace(candidate, metadata=metadata)


def _canonical_policy_decision(outcome: str) -> str:
    return "pending_review" if outcome == "needs_review" else outcome


def _deny_reason_codes(
    candidate: ContextLinkCandidate,
    reason_codes: tuple[str, ...],
    relation_type: str,
    relation_error: str | None,
) -> tuple[str, ...]:
    codes: list[str] = []
    if relation_error is not None:
        codes.append(relation_error)
    if candidate.score < MIN_REVIEW_SCORE:
        codes.append("score_below_review_threshold")
    if not reason_codes:
        codes.append("missing_reason_codes")
    if reason_codes == ("recent_context",):
        codes.append("recent_context_only")
    if (
        MIN_REVIEW_SCORE <= candidate.score < MIN_STRONG_SIGNAL_REVIEW_SCORE
        and reason_codes
        and not _STRONG_REVIEW_SIGNAL_CODES.intersection(reason_codes)
    ):
        codes.append("weak_signal_below_review_threshold")
    if relation_type in _HIGH_IMPACT_RELATION_TYPES and not _has_high_impact_signal(
        relation_type,
        reason_codes,
    ):
        codes.append("high_impact_relation_requires_explicit_signal")
    if relation_type in _EVIDENCE_RELATION_TYPES and not _has_evidence_relation_signal(
        candidate,
        reason_codes,
    ):
        codes.append("evidence_relation_requires_source_signal")
    if relation_type == "mentions" and not _MENTION_RELATION_SIGNAL_CODES.intersection(
        reason_codes
    ):
        codes.append("mentions_relation_requires_entity_signal")
    return tuple(codes)


def _has_high_impact_signal(relation_type: str, reason_codes: tuple[str, ...]) -> bool:
    signal_codes = _HIGH_IMPACT_RELATION_SIGNAL_CODES.get(relation_type, frozenset())
    return bool(signal_codes.intersection(reason_codes))


def _has_evidence_relation_signal(
    candidate: ContextLinkCandidate,
    reason_codes: tuple[str, ...],
) -> bool:
    if "text_match" in reason_codes:
        return True
    metadata = candidate.metadata or {}
    evidence_ref_count = metadata.get("evidence_source_ref_count")
    if isinstance(evidence_ref_count, int) and evidence_ref_count > 0:
        return True
    evidence_refs = metadata.get("evidence_refs")
    if isinstance(evidence_refs, (list, tuple)) and evidence_refs:
        return True
    for key in (
        "evidence_has_page_ref",
        "evidence_has_bbox_ref",
        "evidence_has_time_range_ref",
    ):
        if metadata.get(key) is True:
            return True
    evidence_modalities = metadata.get("evidence_modalities")
    return isinstance(evidence_modalities, (list, tuple)) and bool(evidence_modalities)


def _requires_source_risk_review(candidate: ContextLinkCandidate) -> bool:
    return bool(_source_review_gate_reasons(candidate))


def _source_review_gate_reasons(candidate: ContextLinkCandidate) -> tuple[str, ...]:
    metadata = candidate.metadata or {}
    reasons: list[str] = []
    if metadata.get("prompt_injection_signals_detected") is True:
        reasons.append("prompt_injection_evidence")
    if metadata.get("mime_content_type_mismatch") is True:
        reasons.append("mime_content_type_mismatch")
    return tuple(reasons)


def _source_review_reason_code(review_reason: str) -> str:
    return {
        "prompt_injection_evidence": "prompt_injection_evidence_review_required",
        "mime_content_type_mismatch": "source_mime_mismatch_review_required",
    }.get(review_reason, "source_risk_review_required")


def _auto_approve_signal_count(reason_codes: tuple[str, ...]) -> int:
    return len(_AUTO_APPROVE_SIGNAL_CODES.intersection(reason_codes))


def _relation_type_for_candidate(candidate: ContextLinkCandidate) -> tuple[str, str | None]:
    metadata = candidate.metadata or {}
    raw_relation = metadata.get("relation_type", metadata.get("suggested_relation_type"))
    if raw_relation is None:
        return "related_to", None
    relation_type = _normalize_relation_type(raw_relation)
    if relation_type:
        return relation_type, None
    return "related_to", "unsupported_relation_type"


def _normalize_relation_type(value: object) -> str:
    raw = str(value).strip().lower().replace("-", "_")
    if not _REASON_CODE_PATTERN.fullmatch(raw):
        return ""
    return raw if raw in _ALLOWED_RELATION_TYPES else ""


def _reason_codes(candidate: ContextLinkCandidate) -> tuple[str, ...]:
    metadata = candidate.metadata or {}
    raw_codes = metadata.get("reason_codes")
    if not isinstance(raw_codes, (list, tuple)):
        return ()
    codes: list[str] = []
    for raw_code in raw_codes:
        code = _normalize_reason_code(raw_code)
        if code and code not in codes:
            codes.append(code)
        if len(codes) >= MAX_REASON_CODES:
            break
    return tuple(codes)


def _normalize_reason_code(value: object) -> str:
    raw = str(value).strip()
    if not _REASON_CODE_PATTERN.fullmatch(raw):
        return ""
    return raw.lower().replace("-", "_")


def _confidence_for_score(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _safe_denied_diagnostic_text(value: object) -> str:
    return safe_metadata_text(str(value), limit=MAX_DENIED_DIAGNOSTIC_TEXT_CHARS).strip()
