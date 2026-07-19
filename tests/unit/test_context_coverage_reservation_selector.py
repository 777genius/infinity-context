from infinity_context_core.features.context_building.application.coverage_reservation_selector import (  # noqa: E501
    CoverageReservationBudget,
    CoverageReservationCandidate,
    CoverageReservationSelector,
)
from infinity_context_core.features.context_building.domain.evidence_obligations import (
    EvidenceClaim,
    EvidenceObligation,
    EvidenceObligationConfidence,
    EvidenceObligationId,
)


def test_direct_obligation_selects_strongest_bounded_claim() -> None:
    obligation = _obligation("o-0")

    result = _select(
        (obligation,),
        (
            _candidate("early", "source-a", 0, ("o-0", 0.55)),
            _candidate("strong", "source-b", 4, ("o-0", 0.91)),
        ),
    )

    assert _selected_ids(result) == ("strong",)
    assert _obligation_ids(result) == ("o-0",)


def test_equal_claims_prefer_lower_cost_before_input_rank() -> None:
    obligation = _obligation("o-0")
    candidates = (
        _candidate(
            "higher-ranked",
            "source-a",
            0,
            ("o-0", 0.8),
            token_cost=20,
            character_cost=40,
        ),
        _candidate(
            "compact",
            "source-b",
            4,
            ("o-0", 0.8),
            token_cost=4,
            character_cost=8,
        ),
    )

    first = _select((obligation,), candidates)
    second = _select((obligation,), tuple(reversed(candidates)))

    assert _selected_ids(first) == ("compact",)
    assert first == second


def test_list_obligations_keep_marginal_claims_and_distinct_candidates() -> None:
    obligations = tuple(_obligation(f"o-{index}") for index in range(3))

    result = _select(
        obligations,
        (
            _candidate("shared", "source-a", 0, ("o-0", 0.9), ("o-1", 0.9)),
            _candidate("second", "source-b", 1, ("o-1", 0.8)),
            _candidate("third", "source-c", 2, ("o-2", 0.7)),
        ),
    )

    assert _selected_ids(result) == ("shared", "second", "third")


def test_count_obligations_obey_item_token_and_character_budgets() -> None:
    obligations = tuple(_obligation(f"o-{index}") for index in range(4))
    candidates = tuple(
        _candidate(
            f"candidate-{index}",
            f"source-{index}",
            index,
            (f"o-{index}", 0.8),
            token_cost=3,
            character_cost=5,
        )
        for index in range(4)
    )

    result = _select(
        obligations,
        candidates,
        budget=CoverageReservationBudget(
            max_items=3,
            token_budget=7,
            character_budget=11,
            max_items_per_source=2,
        ),
    )

    assert _selected_ids(result) == ("candidate-0", "candidate-1")


def test_comparison_obligations_prefer_unused_sources_deterministically() -> None:
    obligations = (_obligation("o-a"), _obligation("o-b"))
    candidates = (
        _candidate("left", "source-a", 0, ("o-a", 0.8)),
        _candidate("same-source", "source-a", 1, ("o-b", 0.9)),
        _candidate("other-source", "source-b", 2, ("o-b", 0.7)),
    )

    first = _select(obligations, candidates)
    second = _select(obligations, tuple(reversed(candidates)))

    assert _selected_ids(first) == ("left", "other-source")
    assert first == second


def test_selector_ignores_ineligible_and_non_high_confidence_claims() -> None:
    obligations = (
        _obligation("o-high"),
        EvidenceObligation(EvidenceObligationId("o-low"), EvidenceObligationConfidence.LOW),
    )

    result = _select(
        obligations,
        (
            _candidate("blocked", "source-a", 0, ("o-high", 1.0), eligible=False),
            _candidate("low", "source-b", 1, ("o-low", 1.0)),
        ),
    )

    assert result.reservations == ()
    assert tuple(map(str, result.eligible_obligation_ids)) == ("o-high",)


def test_opaque_ids_and_claim_strengths_reject_non_contract_values() -> None:
    for value in ("", "descriptive id", "o-UPPER", "source:123"):
        try:
            EvidenceObligationId(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted non-opaque id: {value}")

    for strength in (-0.01, 1.01, float("nan")):
        try:
            EvidenceClaim(EvidenceObligationId("o-valid"), strength)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid strength: {strength}")


def _select(
    obligations: tuple[EvidenceObligation, ...],
    candidates: tuple[CoverageReservationCandidate, ...],
    *,
    budget: CoverageReservationBudget | None = None,
):
    return CoverageReservationSelector().select(
        obligations=obligations,
        candidates=candidates,
        budget=budget
        or CoverageReservationBudget(
            max_items=8,
            token_budget=100,
            character_budget=100,
            max_items_per_source=2,
        ),
    )


def _obligation(value: str) -> EvidenceObligation:
    return EvidenceObligation(EvidenceObligationId(value), EvidenceObligationConfidence.HIGH)


def _candidate(
    candidate_id: str,
    source_key: str,
    rank: int,
    *claims: tuple[str, float],
    token_cost: int = 1,
    character_cost: int = 1,
    eligible: bool = True,
) -> CoverageReservationCandidate:
    return CoverageReservationCandidate(
        candidate_id=candidate_id,
        source_key=source_key,
        rank=rank,
        token_cost=token_cost,
        character_cost=character_cost,
        claims=tuple(
            EvidenceClaim(EvidenceObligationId(value), strength) for value, strength in claims
        ),
        eligible=eligible,
    )


def _selected_ids(result) -> tuple[str, ...]:
    return tuple(item.candidate_id for item in result.reservations)


def _obligation_ids(result) -> tuple[str, ...]:
    return tuple(str(item.obligation_id) for item in result.reservations)
