"""Review-gated semantic linking policy."""

from __future__ import annotations

from dataclasses import dataclass, replace

from memo_stack_core.application.dto import ContextLinkCandidate

POLICY_VERSION = "context-link-policy-v1"
MAX_SUGGESTIONS_PER_SOURCE = 10
MIN_REVIEW_SCORE = 40.0
AUTO_APPROVE_ELIGIBLE_SCORE = 92.0
MAX_DENIED_DIAGNOSTIC_ITEMS = 8

_AUTO_APPROVE_TARGET_TYPES = frozenset({"anchor", "fact", "episode", "document", "chunk"})
_REVIEW_BLOCKED_TARGET_TYPES = frozenset({"suggestion"})


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
    denied_reason_counts: dict[str, int] = {}
    denied_candidates: list[dict[str, object]] = []

    for candidate in candidates:
        decision = decide_context_link_candidate(candidate)
        if decision.outcome == "deny":
            denied_count += 1
            for code in decision.reason_codes:
                denied_reason_counts[code] = denied_reason_counts.get(code, 0) + 1
            if len(denied_candidates) < MAX_DENIED_DIAGNOSTIC_ITEMS:
                denied_candidates.append(
                    {
                        "target_type": candidate.target_type,
                        "target_id": candidate.target_id,
                        "score": candidate.score,
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
        if len(accepted) >= max_suggestions:
            break

    return ContextLinkPolicyResult(
        candidates=tuple(accepted),
        diagnostics={
            "link_policy_version": POLICY_VERSION,
            "link_policy_candidates_considered": len(candidates),
            "link_policy_candidates_returned": len(accepted),
            "link_policy_denied_count": denied_count,
            "link_policy_duplicate_suppressed_count": duplicate_count,
            "link_policy_auto_approve_eligible_count": auto_eligible_count,
            "link_policy_needs_review_count": needs_review_count,
            "link_policy_max_suggestions_per_source": max_suggestions,
            "link_policy_denied_reason_counts": denied_reason_counts,
            "link_policy_denied_candidates": denied_candidates,
        },
    )


def decide_context_link_candidate(candidate: ContextLinkCandidate) -> ContextLinkPolicyDecision:
    reason_codes = _reason_codes(candidate)
    deny_codes = _deny_reason_codes(candidate, reason_codes)
    if deny_codes:
        return ContextLinkPolicyDecision(
            outcome="deny",
            relation_type="related_to",
            confidence="low",
            reason_codes=deny_codes,
            requires_review=True,
            auto_approve_eligible=False,
        )

    confidence = _confidence_for_score(candidate.score)
    auto_approve_eligible = (
        candidate.score >= AUTO_APPROVE_ELIGIBLE_SCORE
        and candidate.target_type in _AUTO_APPROVE_TARGET_TYPES
        and "text_match" in reason_codes
        and "recent_context" not in reason_codes
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
    if auto_approve_eligible and not review_blocked:
        decision_codes.append("auto_approve_eligible")
    else:
        decision_codes.append("review_required")
    return ContextLinkPolicyDecision(
        outcome=outcome,
        relation_type="related_to",
        confidence=confidence,
        reason_codes=tuple(dict.fromkeys(decision_codes)),
        requires_review=True,
        auto_approve_eligible=auto_approve_eligible and not review_blocked,
    )


def policy_confidence_for_candidate(candidate: ContextLinkCandidate) -> str | None:
    metadata = candidate.metadata or {}
    value = metadata.get("policy_confidence")
    return str(value) if value in {"low", "medium", "high"} else None


def _with_policy_metadata(
    candidate: ContextLinkCandidate,
    decision: ContextLinkPolicyDecision,
) -> ContextLinkCandidate:
    metadata = dict(candidate.metadata or {})
    metadata.update(
        {
            "suggestion_policy_version": POLICY_VERSION,
            "policy_decision": decision.outcome,
            "policy_relation_type": decision.relation_type,
            "policy_confidence": decision.confidence,
            "policy_reason_codes": list(decision.reason_codes),
            "review_gate": "required",
            "auto_approve_eligible": decision.auto_approve_eligible,
        }
    )
    return replace(candidate, metadata=metadata)


def _deny_reason_codes(
    candidate: ContextLinkCandidate,
    reason_codes: tuple[str, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    if candidate.score < MIN_REVIEW_SCORE:
        codes.append("score_below_review_threshold")
    if not reason_codes:
        codes.append("missing_reason_codes")
    if reason_codes == ("recent_context",):
        codes.append("recent_context_only")
    return tuple(codes)


def _reason_codes(candidate: ContextLinkCandidate) -> tuple[str, ...]:
    metadata = candidate.metadata or {}
    raw_codes = metadata.get("reason_codes")
    if isinstance(raw_codes, list):
        return tuple(str(code) for code in raw_codes if str(code).strip())
    if isinstance(raw_codes, tuple):
        return tuple(str(code) for code in raw_codes if str(code).strip())
    return ()


def _confidence_for_score(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"
