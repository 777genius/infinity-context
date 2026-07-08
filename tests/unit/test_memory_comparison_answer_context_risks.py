from infinity_context_server.memory_comparison_answer_context_risks import (
    add_answer_context_risk_codes,
    backfill_risk_reason_codes,
    context_risk_reason_codes,
    is_measured_low_answerability,
    is_measured_weak_source_locality,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_context_risk_reason_codes_dedupes_in_contract_order() -> None:
    codes = context_risk_reason_codes(
        bundle_risk_reason_codes=(
            "risk:retrieval_backfill",
            "risk:bundle_specific",
            "raw bundle note must stay out",
        ),
        skipped_duplicate_source_bundle_item_count=1,
        skipped_noisy_overlap_bundle_item_count=1,
        backfilled_retrieval_item_count=1,
        skipped_redundant_risky_backfill_count=1,
        skipped_redundant_source_backfill_count=1,
        skipped_redundant_role_backfill_count=1,
        backfill_risk_stats={
            "backfilled_broad_summary_count": 1,
            "backfilled_conflict_or_stale_count": "2",
            "backfilled_low_answerability_count": 1,
            "backfilled_weak_source_locality_count": 1,
        },
        memory_metadata=(
            {
                "answer_context_risk_reason_codes": (
                    "risk:bundle_specific",
                    "risk:memory_specific",
                    "raw memory note must stay out",
                )
            },
            {"answer_context_risk_reason_codes": "risk:memory_string"},
            {"answer_context_risk_reason_codes": "raw memory string must stay out"},
        ),
    )

    assert codes == (
        "risk:retrieval_backfill",
        "risk:bundle_specific",
        "risk:skipped_duplicate_source_bundle_item",
        "risk:skipped_noisy_overlap_bundle_item",
        "risk:backfilled_broad_summary",
        "risk:backfilled_conflict_or_stale",
        "risk:backfilled_low_answerability",
        "risk:backfilled_weak_source_locality",
        "risk:skipped_redundant_risky_backfill",
        "risk:skipped_redundant_source_backfill",
        "risk:skipped_redundant_role_backfill",
        "risk:memory_specific",
        "risk:memory_string",
    )


def test_answer_context_risk_codes_ignore_non_risk_metadata() -> None:
    metadata: dict[str, object] = {}

    add_answer_context_risk_codes(
        metadata,
        ("not_a_risk", " raw provider payload ", "risk:kept"),
    )

    assert metadata == {
        "answer_context_risk_reason_codes": ("risk:kept",),
    }


def test_add_answer_context_risk_codes_merges_existing_metadata_in_order() -> None:
    metadata: dict[str, object] = {
        "kept": True,
        "answer_context_risk_reason_codes": (
            "risk:existing",
            "risk:duplicate",
            "unsafe existing note",
        ),
    }

    add_answer_context_risk_codes(
        metadata,
        ("risk:duplicate", "risk:new", ""),
    )

    assert metadata == {
        "kept": True,
        "answer_context_risk_reason_codes": (
            "risk:existing",
            "risk:duplicate",
            "risk:new",
        ),
    }


def test_measured_low_answerability_threshold_contract() -> None:
    assert is_measured_low_answerability(0.54) is True
    assert is_measured_low_answerability("0.549") is True
    assert is_measured_low_answerability(0) is False
    assert is_measured_low_answerability(-0.1) is False
    assert is_measured_low_answerability(0.55) is False
    assert is_measured_low_answerability(True) is False
    assert is_measured_low_answerability("not-a-score") is False


def test_measured_weak_source_locality_threshold_contract() -> None:
    assert is_measured_weak_source_locality(0.44) is True
    assert is_measured_weak_source_locality("0.449") is True
    assert is_measured_weak_source_locality(0) is False
    assert is_measured_weak_source_locality(-0.1) is False
    assert is_measured_weak_source_locality(0.45) is False
    assert is_measured_weak_source_locality(False) is False
    assert is_measured_weak_source_locality("not-a-score") is False


def test_backfill_risk_reason_codes_propagate_candidate_risks() -> None:
    memory = RetrievedMemory(
        text="Conversation summary: D1:1 and D1:2 have competing details.",
        rank=2,
    )

    codes = backfill_risk_reason_codes(
        memory,
        {
            "broad_summary": True,
            "conflict_or_stale": True,
            "answerability_score": 0.54,
            "source_locality_score": 0.44,
            "identity_confusion_reason_codes": (
                "source_identity:cross_session_source_identity",
                "person_identity:target_mismatch:status_profile",
                "speaker_identity:first_person_profile_relation:alias_profile",
            ),
            "risk_reason_codes": ("risk:candidate_specific", "not_a_risk"),
        },
    )

    assert codes == (
        "risk:retrieval_backfill",
        "risk:backfilled_broad_summary",
        "risk:backfilled_conflict_or_stale",
        "risk:backfilled_low_answerability",
        "risk:backfilled_weak_source_locality",
        "risk:backfilled_identity_confusion",
        "risk:backfilled_source_identity_confusion",
        "risk:backfilled_person_identity_confusion",
        "risk:backfilled_speaker_identity_confusion",
        "risk:candidate_specific",
    )


def test_backfill_risk_reason_codes_ignore_non_identity_confusion_values() -> None:
    memory = RetrievedMemory(text="D1:1 Alex: I moved last year.", rank=1)

    codes = backfill_risk_reason_codes(
        memory,
        {
            "identity_confusion_reason_codes": (
                "",
                "source_identity_gap_without_confusion",
            ),
        },
    )

    assert codes == ("risk:retrieval_backfill",)
