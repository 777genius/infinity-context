import pytest
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_person_activity_exact_turns import (
    exact_person_activity_turn_candidates,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _turn(
    marker: str,
    *,
    speaker: str = "Avery",
    body: str,
    score: float = 0.9,
) -> ContextItem:
    session, turn = marker[1:].split(":")
    return ContextItem(
        item_id=f"family_activity_{session}_{turn}",
        item_type="chunk",
        text=f"{marker} {speaker}: {body}",
        score=score,
        source_refs=(
            SourceRef(
                source_type="dialogue_turn",
                source_id=(f"conversation:family:session_{session}:{marker}:turn"),
            ),
        ),
    )


def _selected_markers(items: tuple[ContextItem, ...]) -> list[str]:
    return [item.text.split(maxsplit=1)[0] for item in items]


def test_family_activity_turns_reserve_diverse_activity_source_groups() -> None:
    museum_visit = _turn(
        "D1:3",
        body="Yesterday I took the children to the history museum.",
        score=0.99,
    )
    same_session_museum_visit = _turn(
        "D1:5",
        body="I also took the kids to an art museum later that week.",
        score=0.98,
    )
    swimming_trip = _turn(
        "D2:7",
        body="I'm off to go swimming with the kids this afternoon.",
        score=0.8,
    )

    selected = exact_person_activity_turn_candidates(
        (museum_visit, same_session_museum_visit, swimming_trip),
        query="What activities has Avery done with her family?",
        limit=2,
    )

    assert _selected_markers(selected) == ["D1:3", "D2:7"]


@pytest.mark.parametrize("family_term", ["family", "kids", "children"])
def test_family_activity_query_terms_enable_direct_exact_turns(family_term: str) -> None:
    swimming_trip = _turn(
        "D4:2",
        body="We went swimming with our children at the community pool.",
    )

    selected = exact_person_activity_turn_candidates(
        (swimming_trip,),
        query=f"What activities has Avery done with the {family_term}?",
    )

    assert selected == (swimming_trip,)


@pytest.mark.parametrize(
    ("speaker", "body"),
    [
        ("Avery", "I heard Morgan took the children to the museum."),
        ("Avery", "I took pictures while my kids were swimming in the pool."),
        ("Morgan", "We visited the aquarium with the kids."),
        ("Avery", "My kids love swimming at the neighborhood pool."),
    ],
)
def test_family_activity_turns_reject_non_participant_evidence(
    speaker: str,
    body: str,
) -> None:
    item = _turn("D3:8", speaker=speaker, body=body)

    assert (
        exact_person_activity_turn_candidates(
            (item,),
            query="What activities has Avery done with her family?",
        )
        == ()
    )


@pytest.mark.parametrize(
    "body",
    [
        "I went swimming this morning. My kids stayed home.",
        "I went swimming at the community pool. My family did not join me.",
        "I went swimming alone while my children were at home.",
        "I went swimming without my family.",
        "I visited the science museum. Later, I picked up my kids from school.",
    ],
)
def test_family_activity_turns_reject_unbound_or_negative_family_clauses(
    body: str,
) -> None:
    item = _turn("D5:4", body=body)

    assert (
        exact_person_activity_turn_candidates(
            (item,),
            query="What activities has Avery done with her family?",
        )
        == ()
    )


def test_family_activity_turns_allow_joint_activity_when_other_family_stayed_home() -> None:
    item = _turn(
        "D5:5",
        body="I went swimming with my kids while my husband stayed home.",
    )

    selected = exact_person_activity_turn_candidates(
        (item,),
        query="What activities has Avery done with her family?",
    )

    assert selected == (item,)


def test_family_activity_turns_remain_bounded_to_eight() -> None:
    items = tuple(
        _turn(
            f"D{index}:1",
            body="I took my family to the science museum.",
            score=1.0 - index * 0.01,
        )
        for index in range(1, 11)
    )

    selected = exact_person_activity_turn_candidates(
        items,
        query="What activities has Avery done with her family?",
        limit=20,
    )

    assert len(selected) == 8


def test_context_packer_reserves_family_activity_turns_before_char_cap_noise() -> None:
    museum_visit = _turn(
        "D6:2",
        body=(
            "Yesterday I took the kids to the natural history museum, where we "
            "spent the afternoon exploring the exhibits together."
        ),
        score=0.7,
    )
    swimming_trip = _turn(
        "D1:9",
        body=("I'm off to go swimming with the children at the community pool before dinner."),
        score=0.69,
    )
    high_score_noise = tuple(
        _turn(
            f"D9:{index}",
            body=(
                "My kids enjoy hearing about community events, but this note "
                "does not describe an activity I joined."
            ),
            score=0.99 - index * 0.001,
        )
        for index in range(1, 9)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_family_activity_char_cap",
        items=(*high_score_noise, museum_visit, swimming_trip),
        query="What activities has Avery done with her family?",
        token_budget=2000,
        max_rendered_chars=1200,
    )

    selected_source_ids = {
        str(ref.source_id) for item in result.bundle.items for ref in item.source_refs
    }
    assert str(museum_visit.source_refs[0].source_id) in selected_source_ids
    assert str(swimming_trip.source_refs[0].source_id) in selected_source_ids
    assert len(result.bundle.rendered_text) <= 1200
