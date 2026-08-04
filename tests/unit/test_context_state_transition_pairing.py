from __future__ import annotations

import pytest
from infinity_context_core.application.context_state_transition_pairing import (
    StateTransitionPairCandidate,
    infer_state_transition_roles,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_QUERY = "For the coffee-to-water ratio, did I switch to more water per spoon of coffee, or less?"
_OLDER_TEXT = "I use 1 tablespoon of coffee per 6 ounces of water."
_CURRENT_TEXT = "I use 1 tablespoon of coffee per 5 ounces of water."


def _infer(*candidates: StateTransitionPairCandidate) -> dict[int, str]:
    return infer_state_transition_roles(query=_QUERY, candidates=candidates)


def _candidate(
    *,
    item_index: int,
    source_identity: str,
    source_id: str,
    text: str,
    diagnostics: dict[str, object] | None = None,
    quote_preview: str | None = None,
    extra_refs: tuple[SourceRef, ...] = (),
) -> StateTransitionPairCandidate:
    return StateTransitionPairCandidate(
        item_index=item_index,
        source_identity=source_identity,
        item=ContextItem(
            item_id=f"item-{item_index}",
            item_type="chunk",
            text=text,
            score=0.5,
            source_refs=(
                SourceRef(
                    source_type="episode",
                    source_id=source_id,
                    quote_preview=quote_preview,
                ),
                *extra_refs,
            ),
            diagnostics=diagnostics,
        ),
    )


def test_infers_previous_and_current_from_anchored_source_quote_dates() -> None:
    result = _infer(
        _candidate(
            item_index=4,
            source_identity="session-older",
            source_id="benchmark/answer_older",
            quote_preview="answer_older date: 2023/02/11: 1 tbsp coffee per 6 oz water.",
            text=_OLDER_TEXT,
        ),
        _candidate(
            item_index=9,
            source_identity="session-current",
            source_id="benchmark/answer_current",
            quote_preview="answer_current date: 2023/06/30: 1 tbsp coffee per 5 oz water.",
            text=_CURRENT_TEXT,
        ),
    )

    assert result == {4: "previous_state", 9: "current_state"}


def test_accepts_real_for_every_measurement_shape() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="older",
            source_id="benchmark:older",
            text="I use 1 tablespoon of coffee for every 6 ounces of water.",
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="current",
            source_id="benchmark:current",
            text="I use 1 tablespoon of coffee for every 5 ounces of water.",
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {1: "previous_state", 2: "current_state"}


def test_uses_the_latest_two_measurements_when_three_are_unambiguous() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="first",
            source_id="benchmark:first",
            text="I use 1 tablespoon of coffee per 7 ounces of water.",
            diagnostics={"event_date": "2023-01-01"},
        ),
        _candidate(
            item_index=2,
            source_identity="second",
            source_id="benchmark:second",
            text=_OLDER_TEXT,
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=3,
            source_identity="third",
            source_id="benchmark:third",
            text=_CURRENT_TEXT,
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {2: "previous_state", 3: "current_state"}


def test_collapses_identical_source_mirrors_before_selecting_a_pair() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="older",
            source_id="benchmark:older-a",
            text=_OLDER_TEXT,
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="OLDER",
            source_id="benchmark:older-b",
            text=_OLDER_TEXT,
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=3,
            source_identity="current",
            source_id="benchmark:current",
            text=_CURRENT_TEXT,
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {1: "previous_state", 3: "current_state"}


def test_fails_closed_for_conflicting_same_source_mirror() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="older",
            source_id="benchmark:older-a",
            text=_OLDER_TEXT,
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="older",
            source_id="benchmark:older-b",
            text="I use 1 tablespoon of coffee per 7 ounces of water.",
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=3,
            source_identity="current",
            source_id="benchmark:current",
            text=_CURRENT_TEXT,
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {}


@pytest.mark.parametrize(
    ("older", "current"),
    [
        (
            _candidate(
                item_index=1,
                source_identity="older",
                source_id="benchmark:older",
                text=f"{_OLDER_TEXT} It was noted on 2023/02/11.",
                diagnostics={"created_at": "2023-02-11"},
            ),
            _candidate(
                item_index=2,
                source_identity="current",
                source_id="benchmark:current",
                text=_CURRENT_TEXT,
                diagnostics={"event_date": "2023-06-30"},
            ),
        ),
        (
            _candidate(
                item_index=1,
                source_identity="older",
                source_id="benchmark:older",
                text=_OLDER_TEXT,
                diagnostics={"event_valid_from": "2023-02-11"},
            ),
            _candidate(
                item_index=2,
                source_identity="current",
                source_id="benchmark:current",
                text=_CURRENT_TEXT,
                diagnostics={"event_date": "2023-02-11"},
            ),
        ),
        (
            _candidate(
                item_index=1,
                source_identity="older",
                source_id="benchmark:older",
                text=_OLDER_TEXT,
                extra_refs=(
                    SourceRef(
                        source_type="episode",
                        source_id="benchmark/older_second",
                        quote_preview="older_second date: 2023/02/12: alternate source.",
                    ),
                ),
                quote_preview="older date: 2023/02/11: first source.",
            ),
            _candidate(
                item_index=2,
                source_identity="current",
                source_id="benchmark:current",
                text=_CURRENT_TEXT,
                diagnostics={"event_date": "2023-06-30"},
            ),
        ),
    ],
    ids=("missing", "equal", "ambiguous"),
)
def test_fails_closed_for_missing_equal_or_ambiguous_dates(
    older: StateTransitionPairCandidate,
    current: StateTransitionPairCandidate,
) -> None:
    assert _infer(older, current) == {}


def test_fails_closed_when_matching_measurements_share_one_source_identity() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="same-source",
            source_id="benchmark:older",
            text=_OLDER_TEXT,
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="same-source",
            source_id="benchmark:current",
            text=_CURRENT_TEXT,
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {}


def test_fails_closed_when_matching_measurements_have_the_same_value() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="older",
            source_id="benchmark:older",
            text=_OLDER_TEXT,
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="current",
            source_id="benchmark:current",
            text="I use one tablespoon of coffee per six oz of water.",
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {}


def test_ignores_unrelated_measurements_outside_the_relation_span() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="older",
            source_id="benchmark:older",
            text=(
                "I bought 2 cups, but I use 1 tablespoon of coffee per 6 ounces of water."
            ),
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="current",
            source_id="benchmark:current",
            text=(
                "I bought 3 cups, but I use 1 tablespoon of coffee per 6 ounces of water."
            ),
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {}


def test_rejects_measurements_for_an_unrelated_query_relation() -> None:
    result = _infer(
        _candidate(
            item_index=1,
            source_identity="tea",
            source_id="benchmark:tea",
            text="I use 1 spoon of tea per 6 ounces of water.",
            diagnostics={"event_date": "2023-02-11"},
        ),
        _candidate(
            item_index=2,
            source_identity="milk",
            source_id="benchmark:milk",
            text="I use 1 spoon of coffee per 5 ounces of milk.",
            diagnostics={"event_date": "2023-06-30"},
        ),
    )

    assert result == {}
