from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_state_residence_packing_keeps_exact_geo_map_evidence_under_tight_budget() -> None:
    generic_pet_park = _state_residence_item(
        "generic_pet_park",
        (
            "D7:3 Andrew: I took the dogs to a local park after work. "
            "They enjoyed the grass and played for a while."
        ),
        score=0.99,
        source_ids=("locomo:conv-fixture:session_7:D7:3:turn",),
    )
    broad_pet_housing = _state_residence_item(
        "broad_pet_housing",
        (
            "D5:5 Andrew: Finding a pet-friendly place to live has been tough. "
            "I am checking neighborhoods and landlords."
        ),
        score=0.98,
        source_ids=("locomo:conv-fixture:session_5:D5:5:turn",),
    )
    trail_map = _state_residence_item(
        "trail_map",
        (
            "D11:7 Andrew: We should find a safe trail for the dogs. "
            "D11:9 Andrew: Here's the map for the trail. image caption: "
            "a photo of a map of a park with trees. visual query: hiking "
            "trails map perfect spot."
        ),
        score=0.72,
        source_ids=(
            "locomo:conv-fixture:session_11",
            "locomo:conv-fixture:session_11:D11:7:turn",
            "locomo:conv-fixture:session_11:D11:9:turn",
        ),
    )

    result = ContextPacker().pack(
        bundle_id="ctx_state_residence",
        items=(generic_pet_park, broad_pet_housing, trail_map),
        query="Which US state do Riley and Casey potentially live in?",
        token_budget=240,
        max_rendered_chars=680,
    )

    assert "D11:9 Andrew: Here's the map for the trail" in result.bundle.rendered_text


def _state_residence_item(
    item_id: str,
    text: str,
    *,
    score: float,
    source_ids: tuple[str, ...],
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=tuple(
            SourceRef(source_type="locomo_turn", source_id=source_id)
            for source_id in source_ids
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "state_residence_inference_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": 6,
            },
        },
    )
