from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_answer_context_backfill_prefers_compact_source_refs_for_same_role() -> None:
    memories = (
        _memory(
            "primary",
            "D2:10 Morgan: The community event was important.",
            ("D2:10",),
        ),
        _memory(
            "diffuse-event",
            "D2:9 Morgan mentioned the event near other unrelated turns.",
            ("D2:9", "D2:11", "D2:40"),
            relation_category_hits=("participation_event",),
        ),
        _memory(
            "compact-event",
            "D2:12 Morgan described attending the event.",
            ("D2:12",),
            relation_category_hits=("participation_event",),
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=3,
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "compact-event",
        "diffuse-event",
    ]
    assert "source_proximity_support" in context.memories[1].metadata[
        "answer_context_reason_codes"
    ]


def test_answer_context_backfill_counts_candidates_skipped_by_target_limit() -> None:
    memories = (
        _memory(
            "primary",
            "D2:10 Morgan: The community event was important.",
            ("D2:10",),
        ),
        *(
            _memory(
                f"event-{turn}",
                f"D2:{turn} Morgan added event detail {turn}.",
                (f"D2:{turn}",),
                relation_category_hits=("participation_event",),
            )
            for turn in range(11, 19)
        ),
    )

    context = answer_context_from_evidence_bundle(
        memories,
        {
            "role_requirement_complete": False,
            "missing_required_roles": ["event_support"],
            "items": [{"id": "primary", "retrieval_order": 1, "role": "primary"}],
        },
        cutoff=len(memories),
    )

    assert [memory.item_id for memory in context.memories] == [
        "primary",
        "event-11",
        "event-12",
        "event-13",
        "event-14",
        "event-15",
    ]
    assert context.backfilled_retrieval_item_count == 5
    assert context.skipped_target_limit_backfill_count == 3
    assert context.memories[0].metadata[
        "answer_context_skipped_target_limit_backfill_count"
    ] == 3
    diagnostics = context.to_diagnostics()
    assert diagnostics["skipped_target_limit_backfill_count"] == 3
    assert "risk:skipped_target_limit_backfill" in diagnostics["risk_reason_codes"]


def _memory(
    item_id: str,
    text: str,
    source_refs: tuple[str, ...],
    *,
    relation_category_hits: tuple[str, ...] = (),
) -> RetrievedMemory:
    return RetrievedMemory(
        text=text,
        rank=1,
        item_id=item_id,
        source_refs=source_refs,
        metadata={
            "diagnostics": {
                "benchmark_candidate_features": {
                    "answerability_score": 0.9,
                    "source_locality_score": 0.9,
                    "query_roles": ["event_support"],
                    "relation_category_hits": list(relation_category_hits),
                    "entity_hits": ["morgan"],
                    "speaker_hits": ["morgan"],
                }
            }
        },
    )
