from infinity_context_core.application.context_packer import (
    ContextPacker,
    _answer_support_diversity_candidates,
    _answer_support_diversity_family,
    _ordered_answer_support_families_for_query,
    _precise_answer_content_rank,
)
from infinity_context_core.application.context_packer_answer_support import _answer_object_rank
from infinity_context_core.application.context_packer_answer_support_slots import (
    _general_activity_answer_slot_for_text,
)
from infinity_context_core.application.context_query_expansion import build_query_expansion_plan
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _activity_item(
    item_id: str,
    text: str,
    *,
    query_reason: str = "family_activity_bridge",
    source_id: str,
    score: float = 0.9,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_source": "keyword_chunks",
            "score_signals": {"query_expansion_reason": query_reason},
        },
    )


def test_parent_childhood_activity_query_expands_without_specific_answer() -> None:
    plan = build_query_expansion_plan("What activity did Caroline used to do with her dad?")
    expansions = {exp.reason: exp.query for exp in plan.expansions}

    bridge = expansions["family_activity_bridge"]
    assert "dad father parent childhood" in bridge
    assert "used to go" in bridge
    assert "horseback" not in bridge


def test_parent_childhood_activity_gets_direct_activity_slot_and_rank() -> None:
    direct = _activity_item(
        "direct_parent_activity",
        (
            "D13:7 Caroline: I used to go riding with my dad when I was a kid, "
            "and it was special."
        ),
        source_id="locomo:conv-fixture:session_13:D13:7:turn",
    )
    generic = _activity_item(
        "generic_family_activity",
        "D5:4 Caroline: I did a creative class with family last weekend.",
        source_id="locomo:conv-fixture:session_5:D5:4:turn",
        score=0.99,
    )

    assert _general_activity_answer_slot_for_text(direct.text.casefold()) == (
        "childhood_parent_activity"
    )
    assert _answer_object_rank(direct, query_reason="family_activity_bridge") == 0
    assert _precise_answer_content_rank(
        _activity_item(
            "direct_decomposition",
            direct.text,
            query_reason="decomposition_activity_participation",
            source_id="locomo:conv-fixture:session_13:D13:7:turn",
        ),
        query_reason="decomposition_activity_participation",
    ) == 0

    candidates = _answer_support_diversity_candidates([generic, direct])
    ordered = _ordered_answer_support_families_for_query(
        candidates,
        query="What activity did Caroline used to do with her dad?",
    )

    assert "childhood-parent-activity" in _answer_support_diversity_family(direct)
    assert candidates[ordered[0]].item_id == "direct_parent_activity"


def test_context_packer_keeps_parent_childhood_activity_turn_before_noise() -> None:
    direct = _activity_item(
        "direct_parent_activity",
        (
            "D13:7 Caroline: I used to go riding with my dad when I was a kid, "
            "and it was special."
        ),
        source_id="locomo:conv-fixture:session_13:D13:7:turn",
        score=0.86,
    )
    noise = tuple(
        _activity_item(
            f"activity_noise_{index}",
            (
                f"D{index}:4 Melanie: We did pottery, camping, painting, "
                "and other creative family activities."
            ),
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:4:turn",
            score=0.99 - index * 0.001,
        )
        for index in range(1, 9)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_parent_childhood_activity",
        items=(*noise, direct),
        query="What activity did Caroline used to do with her dad?",
        token_budget=900,
        max_rendered_chars=1400,
    )

    assert "D13:7 Caroline: I used to go riding with my dad" in result.bundle.rendered_text
