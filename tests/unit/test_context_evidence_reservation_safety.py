from __future__ import annotations

from infinity_context_core.application.context_evidence_reservation_safety import (
    evidence_reservation_candidate_is_eligible,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _item(*, diagnostics: dict[str, object]) -> ContextItem:
    return ContextItem(
        item_id="reservation-candidate",
        item_type="chunk",
        text="Morgan started watering the herb garden every morning.",
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv:1:session_1:D1:1:turn",
            ),
        ),
        diagnostics=diagnostics,
    )


def _scalar_telemetry(*, count: int = 128) -> dict[str, object]:
    return {f"producer_telemetry_{index}": index for index in range(count)}


def test_scalar_telemetry_does_not_consume_diagnostic_structure_budget() -> None:
    item = _item(
        diagnostics={
            "score_signals": {
                "query_expansion_reason": "decomposition_temporal_interval_endpoint_1",
                **_scalar_telemetry(),
            },
            "provenance": {
                "retrieval_source": "keyword_source_sibling_chunks",
                "candidate_rank": 26,
            },
        }
    )

    assert evidence_reservation_candidate_is_eligible(item) is True


def test_nested_conflict_aliases_after_scalar_telemetry_remain_fail_closed() -> None:
    for conflict_key in (
        "conflicting_fact_id",
        "conflict_fact_id",
        "possible_conflict_fact_id",
    ):
        diagnostics = {"score_signals": _scalar_telemetry()}
        diagnostics["provenance"] = {"audit": {conflict_key: "fact-123"}}

        assert evidence_reservation_candidate_is_eligible(_item(diagnostics=diagnostics)) is False


def test_nested_review_only_after_scalar_telemetry_remains_fail_closed() -> None:
    diagnostics = {"score_signals": _scalar_telemetry()}
    diagnostics["provenance"] = {"audit": {"review_only": True}}

    assert evidence_reservation_candidate_is_eligible(_item(diagnostics=diagnostics)) is False


def test_diagnostic_container_budget_allows_96_containers_and_rejects_97() -> None:
    at_limit = _item(diagnostics={"score_signals": [{} for _ in range(94)]})
    over_limit = _item(diagnostics={"score_signals": [{} for _ in range(95)]})

    assert evidence_reservation_candidate_is_eligible(at_limit) is True
    assert evidence_reservation_candidate_is_eligible(over_limit) is False


def test_oversized_diagnostic_mapping_and_sequence_remain_fail_closed() -> None:
    oversized_mapping = _item(
        diagnostics={"score_signals": _scalar_telemetry(count=513)}
    )
    oversized_sequence = _item(
        diagnostics={"score_signals": list(range(513))}
    )

    assert evidence_reservation_candidate_is_eligible(oversized_mapping) is False
    assert evidence_reservation_candidate_is_eligible(oversized_sequence) is False


def test_excessive_aggregate_diagnostic_members_remain_fail_closed() -> None:
    item = _item(
        diagnostics={
            "score_signals": _scalar_telemetry(count=512),
            "provenance": _scalar_telemetry(count=512),
        }
    )

    assert evidence_reservation_candidate_is_eligible(item) is False


def test_invalid_diagnostic_keys_and_cycles_remain_fail_closed() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    for diagnostics in (
        {1: "untyped diagnostic key"},
        {"x" * 513: "oversized diagnostic key"},
        {"provenance": cyclic},
    ):
        assert evidence_reservation_candidate_is_eligible(_item(diagnostics=diagnostics)) is False


def test_diagnostic_depth_counts_containers_but_not_scalar_leaves() -> None:
    nested: object = 1
    for index in range(5):
        nested = {f"layer_{index}": nested}

    assert evidence_reservation_candidate_is_eligible(
        _item(diagnostics={"provenance": nested})
    ) is True

    nested = 1
    for index in range(6):
        nested = {f"layer_{index}": nested}

    assert evidence_reservation_candidate_is_eligible(
        _item(diagnostics={"provenance": nested})
    ) is False
