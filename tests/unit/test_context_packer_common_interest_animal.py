from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_candidates,
    _answer_support_family_item_key_for_query,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _common_interest_item(item_id: str, text: str, source_id: str, *, score: float) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {"query_expansion_reason": "commonality_interest_bridge"},
        },
    )


def test_common_interest_answer_support_preserves_animal_affinity_turns() -> None:
    nate_affinity = _common_interest_item(
        "nate_turtle_affinity",
        (
            "D5:6 Nate: I'm drawn to turtles. They're unique and their slow "
            "pace is a nice change from the rush of life. They're also "
            "low-maintenance and calming."
        ),
        "locomo:conv-fixture:session_5:D5:6:turn",
        score=0.2,
    )
    joanna_affinity_reply = _common_interest_item(
        "joanna_turtle_affinity_reply",
        (
            "D26:9 Joanna: Thanks, Nate! They make me think of strength and "
            "perseverance. They help motivate me in tough times - glad you "
            "find that inspiring!"
        ),
        "locomo:conv-fixture:session_26:D26:9:turn",
        score=0.19,
    )
    movie_noise = _common_interest_item(
        "movie_noise",
        "D1:10 Joanna: Besides writing, I enjoy watching movies and reading.",
        "locomo:conv-fixture:session_1:D1:10:turn",
        score=0.99,
    )
    dessert_noise = _common_interest_item(
        "dessert_noise",
        "D10:9 Joanna: I have been testing out dairy-free dessert recipes.",
        "locomo:conv-fixture:session_10:D10:9:turn",
        score=0.98,
    )
    weak_animal_noise = _common_interest_item(
        "weak_animal_noise",
        (
            "D5:12 Nate: Maybe there are other animals Joanna could consider. "
            "I can send more pictures of my turtles if that helps."
        ),
        "locomo:conv-fixture:session_5:D5:12:turn",
        score=0.99,
    )
    query = "What animal do Nate and Joanna both like?"

    candidates = _answer_support_diversity_candidates(
        [
            movie_noise,
            dessert_noise,
            weak_animal_noise,
            nate_affinity,
            joanna_affinity_reply,
        ],
        query=query,
    )
    families = set(candidates)
    result = ContextPacker().pack(
        bundle_id="ctx_common_interest_animal_affinity",
        items=(
            movie_noise,
            dessert_noise,
            weak_animal_noise,
            nate_affinity,
            joanna_affinity_reply,
        ),
        query=query,
        token_budget=1000,
        max_rendered_chars=4000,
    )

    assert any("common-interest-animal-affinity" in family for family in families)
    assert any("common-interest-affinity-reason" in family for family in families)
    assert _answer_support_family_item_key_for_query(
        nate_affinity,
        query=query,
    ) < _answer_support_family_item_key_for_query(weak_animal_noise, query=query)
    assert "D5:6 Nate: I'm drawn to turtles" in result.bundle.rendered_text
    assert "D26:9 Joanna: Thanks, Nate!" in result.bundle.rendered_text
