from memo_stack_core.application.context_link_policy import (
    MAX_SUGGESTIONS_PER_SOURCE,
    apply_context_link_policy,
    decide_context_link_candidate,
)
from memo_stack_core.application.dto import ContextLinkCandidate


def _candidate(
    *,
    target_id: str,
    score: float,
    reason_codes: list[str] | None = None,
    target_type: str = "fact",
) -> ContextLinkCandidate:
    return ContextLinkCandidate(
        target_type=target_type,
        target_id=target_id,
        label=target_id,
        preview=f"preview {target_id}",
        score=score,
        tier="likely" if score >= 75 else "possible" if score >= 55 else "weak",
        reasons=("matching text",),
        metadata={"reason_codes": reason_codes or ["text_match"]},
    )


def test_policy_denies_weak_recent_only_candidate() -> None:
    candidate = _candidate(target_id="recent", score=39.9, reason_codes=["recent_context"])
    decision = decide_context_link_candidate(candidate)
    result = apply_context_link_policy((candidate,), limit=10, persist=False)

    assert decision.outcome == "deny"
    assert "score_below_review_threshold" in decision.reason_codes
    assert "recent_context_only" in decision.reason_codes
    assert decision.auto_approve_eligible is False
    assert result.diagnostics["link_policy_denied_candidates"] == [
        {
            "target_type": "fact",
            "target_id": "recent",
            "score": 39.9,
            "reason_codes": ["score_below_review_threshold", "recent_context_only"],
        }
    ]


def test_policy_marks_strong_text_match_as_auto_approve_eligible_but_review_gated() -> None:
    decision = decide_context_link_candidate(_candidate(target_id="strong", score=94))

    assert decision.outcome == "auto_approve_candidate"
    assert decision.confidence == "high"
    assert decision.requires_review is True
    assert decision.auto_approve_eligible is True
    assert "auto_approve_eligible" in decision.reason_codes


def test_policy_applies_metadata_caps_and_duplicate_suppression() -> None:
    candidates = tuple(
        [_candidate(target_id="same", score=96), _candidate(target_id="same", score=95)]
        + [_candidate(target_id=f"target_{index}", score=80) for index in range(20)]
    )

    result = apply_context_link_policy(candidates, limit=30, persist=True)

    assert len(result.candidates) == MAX_SUGGESTIONS_PER_SOURCE
    assert result.diagnostics["link_policy_duplicate_suppressed_count"] == 1
    assert result.diagnostics["link_policy_max_suggestions_per_source"] == (
        MAX_SUGGESTIONS_PER_SOURCE
    )
    first_metadata = result.candidates[0].metadata or {}
    assert first_metadata["policy_decision"] == "auto_approve_candidate"
    assert first_metadata["review_gate"] == "required"
    assert first_metadata["auto_approve_eligible"] is True
    assert first_metadata["policy_confidence"] == "high"
