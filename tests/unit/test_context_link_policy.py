from memo_stack_core.application.context_link_policy import (
    MAX_DENIED_DIAGNOSTIC_ITEMS,
    MAX_POLICY_CANDIDATES_CONSIDERED,
    MAX_REASON_CODES,
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
    metadata: dict[str, object] | None = None,
) -> ContextLinkCandidate:
    candidate_metadata = {"reason_codes": reason_codes or ["text_match"]}
    if metadata:
        candidate_metadata.update(metadata)
    return ContextLinkCandidate(
        target_type=target_type,
        target_id=target_id,
        label=target_id,
        preview=f"preview {target_id}",
        score=score,
        tier="likely" if score >= 75 else "possible" if score >= 55 else "weak",
        reasons=("matching text",),
        metadata=candidate_metadata,
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


def test_policy_denies_low_score_without_strong_link_signal() -> None:
    candidate = _candidate(target_id="weak-thread", score=54.9, reason_codes=["same_thread"])
    decision = decide_context_link_candidate(candidate)
    result = apply_context_link_policy((candidate,), limit=10, persist=True)

    assert decision.outcome == "deny"
    assert decision.reason_codes == ("weak_signal_below_review_threshold",)
    assert result.candidates == ()
    assert result.diagnostics["link_policy_denied_reason_counts"] == {
        "weak_signal_below_review_threshold": 1
    }
    assert result.diagnostics["link_policy_decision_counts"] == {
        "deny": 1,
        "duplicate_suppressed": 0,
        "auto_approve_candidate": 0,
        "pending_review": 0,
        "needs_review": 0,
    }


def test_policy_redacts_denied_candidate_diagnostics() -> None:
    candidate = _candidate(
        target_id="fact sk-proj-secretvalue123456",
        score=39.0,
        reason_codes=["recent_context"],
    )

    result = apply_context_link_policy((candidate,), limit=10, persist=True)

    diagnostics = result.diagnostics
    serialized = repr(diagnostics)
    assert "sk-proj-secretvalue123456" not in serialized
    assert diagnostics["link_policy_denied_candidates"] == [
        {
            "target_type": "fact",
            "target_id": "fact [redacted]",
            "score": 39.0,
            "reason_codes": ["score_below_review_threshold", "recent_context_only"],
        }
    ]


def test_policy_allows_low_score_with_strong_temporal_signal_for_review() -> None:
    candidate = _candidate(
        target_id="temporal",
        score=45.0,
        reason_codes=["temporal_intent_match"],
    )
    decision = decide_context_link_candidate(candidate)
    result = apply_context_link_policy((candidate,), limit=10, persist=True)

    assert decision.outcome == "needs_review"
    assert decision.requires_review is True
    assert result.candidates[0].target_id == "temporal"
    assert result.candidates[0].metadata["policy_decision"] == "needs_review"
    assert result.candidates[0].metadata["policy_decision_canonical"] == "pending_review"


def test_policy_keeps_single_signal_high_score_candidate_review_only() -> None:
    decision = decide_context_link_candidate(_candidate(target_id="strong", score=94))

    assert decision.outcome == "needs_review"
    assert decision.confidence == "high"
    assert decision.requires_review is True
    assert decision.auto_approve_eligible is False
    assert "insufficient_independent_signals" in decision.reason_codes
    assert "auto_approve_eligible" not in decision.reason_codes


def test_policy_marks_two_signal_text_match_as_auto_approve_eligible_but_review_gated() -> None:
    decision = decide_context_link_candidate(
        _candidate(
            target_id="strong",
            score=94,
            reason_codes=["text_match", "explicit_project_reference"],
        )
    )

    assert decision.outcome == "auto_approve_candidate"
    assert decision.confidence == "high"
    assert decision.requires_review is True
    assert decision.auto_approve_eligible is True
    assert "auto_approve_eligible" in decision.reason_codes


def test_policy_keeps_suggestion_targets_review_only_even_with_high_score() -> None:
    suggestion_target = _candidate(
        target_id="suggestion_candidate",
        target_type="suggestion",
        score=98,
    )

    decision = decide_context_link_candidate(suggestion_target)
    result = apply_context_link_policy((suggestion_target,), limit=10, persist=True)

    assert decision.outcome == "needs_review"
    assert decision.requires_review is True
    assert decision.auto_approve_eligible is False
    assert "review_required_target_type" in decision.reason_codes
    assert result.candidates[0].metadata["review_gate"] == "required"
    assert result.candidates[0].metadata["auto_approve_eligible"] is False


def test_policy_applies_metadata_caps_and_duplicate_suppression() -> None:
    candidates = tuple(
        [
            _candidate(
                target_id="same",
                score=96,
                reason_codes=["text_match", "explicit_project_reference"],
            ),
            _candidate(
                target_id="same",
                score=95,
                reason_codes=["text_match", "explicit_project_reference"],
            ),
        ]
        + [_candidate(target_id=f"target_{index}", score=80) for index in range(20)]
    )

    result = apply_context_link_policy(candidates, limit=30, persist=True)

    assert len(result.candidates) == MAX_SUGGESTIONS_PER_SOURCE
    assert result.diagnostics["link_policy_duplicate_suppressed_count"] == 1
    assert result.diagnostics["link_policy_decision_counts"] == {
        "deny": 0,
        "duplicate_suppressed": 1,
        "auto_approve_candidate": 1,
        "pending_review": MAX_SUGGESTIONS_PER_SOURCE - 1,
        "needs_review": MAX_SUGGESTIONS_PER_SOURCE - 1,
    }
    assert result.diagnostics["link_policy_max_suggestions_per_source"] == (
        MAX_SUGGESTIONS_PER_SOURCE
    )
    first_metadata = result.candidates[0].metadata or {}
    assert first_metadata["policy_decision"] == "auto_approve_candidate"
    assert first_metadata["policy_decision_canonical"] == "auto_approve_candidate"
    assert first_metadata["review_gate"] == "required"
    assert first_metadata["auto_approve_eligible"] is True
    assert first_metadata["policy_confidence"] == "high"
    assert result.diagnostics["link_policy_pending_review_count"] == (
        MAX_SUGGESTIONS_PER_SOURCE - 1
    )


def test_policy_diagnostics_report_actual_candidates_processed_before_limit() -> None:
    candidates = tuple(
        _candidate(target_id=f"strong_{index}", score=96)
        for index in range(MAX_SUGGESTIONS_PER_SOURCE + 25)
    )

    result = apply_context_link_policy(candidates, limit=100, persist=True)

    assert len(result.candidates) == MAX_SUGGESTIONS_PER_SOURCE
    assert result.diagnostics["link_policy_candidates_received"] == (
        MAX_SUGGESTIONS_PER_SOURCE + 25
    )
    assert result.diagnostics["link_policy_candidate_pool_size"] == (
        MAX_SUGGESTIONS_PER_SOURCE + 25
    )
    assert result.diagnostics["link_policy_candidates_considered"] == (MAX_SUGGESTIONS_PER_SOURCE)
    assert result.diagnostics["link_policy_candidates_unprocessed_after_limit"] == 25
    assert result.diagnostics["link_policy_stopped_after_return_limit"] is True


def test_policy_keeps_allowed_relation_type_and_dedupes_per_relation() -> None:
    related = _candidate(target_id="same", score=90)
    supporting = _candidate(
        target_id="same",
        score=89,
        metadata={"relation_type": "supports"},
    )

    result = apply_context_link_policy((related, supporting), limit=10, persist=True)

    assert len(result.candidates) == 2
    assert result.diagnostics["link_policy_duplicate_suppressed_count"] == 0
    relation_types = {
        item.metadata["policy_relation_type"] for item in result.candidates if item.metadata
    }
    assert relation_types == {"related_to", "supports"}


def test_policy_denies_unsupported_relation_type() -> None:
    candidate = _candidate(
        target_id="unsafe-relation",
        score=95,
        metadata={"relation_type": "delete_target"},
    )

    decision = decide_context_link_candidate(candidate)
    result = apply_context_link_policy((candidate,), limit=10, persist=True)

    assert decision.outcome == "deny"
    assert decision.reason_codes == ("unsupported_relation_type",)
    assert result.candidates == ()


def test_policy_blocks_high_impact_relation_without_explicit_signal() -> None:
    weak_supersedes = _candidate(
        target_id="old-fact",
        score=96,
        metadata={"relation_type": "supersedes"},
    )
    explicit_supersedes = _candidate(
        target_id="old-fact",
        score=96,
        reason_codes=["temporal_intent_match"],
        metadata={"relation_type": "supersedes"},
    )

    weak_decision = decide_context_link_candidate(weak_supersedes)
    explicit_decision = decide_context_link_candidate(explicit_supersedes)
    result = apply_context_link_policy(
        (weak_supersedes, explicit_supersedes),
        limit=10,
        persist=True,
    )

    assert weak_decision.outcome == "deny"
    assert weak_decision.reason_codes == ("high_impact_relation_requires_explicit_signal",)
    assert explicit_decision.outcome == "needs_review"
    assert explicit_decision.relation_type == "supersedes"
    assert explicit_decision.auto_approve_eligible is False
    assert result.candidates[0].metadata["policy_relation_type"] == "supersedes"
    assert result.candidates[0].metadata["review_gate"] == "required"


def test_policy_blocks_contradicts_relation_without_explicit_signal() -> None:
    weak_contradicts = _candidate(
        target_id="disputed-fact",
        score=96,
        metadata={"relation_type": "contradicts"},
    )
    explicit_contradicts = _candidate(
        target_id="disputed-fact",
        score=96,
        reason_codes=["explicit_correction"],
        metadata={"relation_type": "contradicts"},
    )

    weak_decision = decide_context_link_candidate(weak_contradicts)
    explicit_decision = decide_context_link_candidate(explicit_contradicts)
    result = apply_context_link_policy(
        (weak_contradicts, explicit_contradicts),
        limit=10,
        persist=True,
    )

    assert weak_decision.outcome == "deny"
    assert weak_decision.reason_codes == ("high_impact_relation_requires_explicit_signal",)
    assert explicit_decision.outcome == "needs_review"
    assert explicit_decision.relation_type == "contradicts"
    assert explicit_decision.auto_approve_eligible is False
    assert result.candidates[0].metadata["policy_relation_type"] == "contradicts"
    assert result.candidates[0].metadata["review_gate"] == "required"


def test_policy_caps_candidates_considered_before_review_decisions() -> None:
    candidates = tuple(
        _candidate(
            target_id=f"denied_{index}",
            score=39,
            reason_codes=["recent_context"],
        )
        for index in range(MAX_POLICY_CANDIDATES_CONSIDERED + 25)
    )

    result = apply_context_link_policy(candidates, limit=10, persist=True)

    assert result.candidates == ()
    assert result.diagnostics["link_policy_candidates_received"] == (
        MAX_POLICY_CANDIDATES_CONSIDERED + 25
    )
    assert (
        result.diagnostics["link_policy_candidates_considered"] == MAX_POLICY_CANDIDATES_CONSIDERED
    )
    assert result.diagnostics["link_policy_candidate_considered_cap"] == (
        MAX_POLICY_CANDIDATES_CONSIDERED
    )
    assert result.diagnostics["link_policy_candidates_truncated"] is True
    assert result.diagnostics["link_policy_denied_count"] == MAX_POLICY_CANDIDATES_CONSIDERED
    assert len(result.diagnostics["link_policy_denied_candidates"]) == MAX_DENIED_DIAGNOSTIC_ITEMS
    assert f"denied_{MAX_POLICY_CANDIDATES_CONSIDERED + 24}" not in repr(result.diagnostics)


def test_policy_normalizes_reason_codes_without_raw_text_or_secrets() -> None:
    candidate = _candidate(
        target_id="unsafe",
        score=80,
        reason_codes=[
            "text-match",
            "Authorization: Bearer sk-proj-secret-value",
            "raw person Alex private note",
            "x" * 80,
            "text_match",
            "recent-context",
        ],
    )

    decision = decide_context_link_candidate(candidate)
    result = apply_context_link_policy((candidate,), limit=10, persist=True)

    assert decision.reason_codes == (
        "score_threshold_met",
        "text_match",
        "recent_context",
        "review_required",
    )
    metadata = result.candidates[0].metadata or {}
    assert metadata["policy_reason_codes"] == [
        "score_threshold_met",
        "text_match",
        "recent_context",
        "review_required",
    ]


def test_policy_caps_reason_codes_before_public_metadata() -> None:
    candidate = _candidate(
        target_id="many-reasons",
        score=80,
        reason_codes=[f"custom_signal_{index}" for index in range(MAX_REASON_CODES + 5)],
    )

    decision = decide_context_link_candidate(candidate)

    assert len(decision.reason_codes) == MAX_REASON_CODES + 2
    assert decision.reason_codes[:2] == ("score_threshold_met", "custom_signal_0")
    assert decision.reason_codes[-1] == "review_required"
