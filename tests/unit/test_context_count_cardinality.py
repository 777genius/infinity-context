from __future__ import annotations

from infinity_context_core.application.context_count_cardinality import (
    has_exact_count_cardinality_evidence,
)


def test_count_cardinality_treats_both_pair_as_exact_count() -> None:
    assert has_exact_count_cardinality_evidence("Both Mia and Ana joined the class.")
    assert has_exact_count_cardinality_evidence("The answer is both Max and Luna.")


def test_count_cardinality_does_not_treat_temporal_both_as_count() -> None:
    assert not has_exact_count_cardinality_evidence(
        "Mia practiced both before and after class."
    )
