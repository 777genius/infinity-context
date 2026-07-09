from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_travel_hobby_writing_evidence import (
    travel_hobby_writing_answer_slot,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _writing_inventory_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
    distinctive_term_hits: int = 6,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {
                "query_expansion_reason": "creative_writing_inventory_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_distinct_writing_kinds() -> None:
    filler_items = tuple(
        _writing_inventory_item(
            item_id=f"writing_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:4:turn",
            text=f"D{index}:4 Dana said writing has been on her mind lately.",
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 9)
    )
    screenplay = _writing_inventory_item(
        item_id="screenplay",
        source_id="locomo:conv-fixture:session_2:D2:3:turn",
        text="D2:3 Dana finished her first full screenplay and printed it.",
        score=0.85,
    )
    book = _writing_inventory_item(
        item_id="book",
        source_id="locomo:conv-fixture:session_17:D17:14:turn",
        text="D17:14 Dana started on a book recently after her movie did well.",
        score=0.84,
    )
    journal = _writing_inventory_item(
        item_id="journal",
        source_id="locomo:conv-fixture:session_18:D18:1:turn",
        text="D18:1 Dana has writing projects and says her journal is her rock.",
        score=0.83,
    )
    blog = _writing_inventory_item(
        item_id="blog",
        source_id="locomo:conv-fixture:session_18:D18:5:turn",
        text="D18:5 Dana made an online blog post about a hard moment.",
        score=0.82,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_writing_inventory",
        items=(*filler_items, screenplay, book, journal, blog),
        token_budget=2600,
        query="What kinds of writing does Dana do?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_2:D2:3:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_17:D17:14:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_18:D18:1:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_18:D18:5:turn" in selected_source_ids


def _travel_hobby_writing_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
    distinctive_term_hits: int = 7,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "travel_hobby_writing_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_travel_hobby_writing_slots_separate_publication_and_story_sharing() -> None:
    assert (
        travel_hobby_writing_answer_slot(
            "Avery is writing essays for an online magazine about the books she loves."
        )
        == "creative_writing_publication"
    )
    assert (
        travel_hobby_writing_answer_slot(
            "Avery has been writing more articles because it lets her combine "
            "her love for reading with sharing great stories."
        )
        == "creative_writing_story_sharing"
    )


def test_context_packer_keeps_travel_hobby_writing_and_travel_facets() -> None:
    filler_items = tuple(
        _travel_hobby_writing_item(
            item_id=f"travel_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            text=f"D{index}:2 Avery mentions a hobby and travel in passing.",
            score=0.99 - index * 0.001,
            distinctive_term_hits=7,
        )
        for index in range(1, 8)
    )
    first_article = _travel_hobby_writing_item(
        item_id="first_article",
        source_id="locomo:conv-fixture:session_20:D20:1:turn",
        text=(
            "D20:1 Avery: I am writing articles about fantasy novels for "
            "an online magazine, and it is so rewarding."
        ),
        score=0.84,
    )
    more_articles = _travel_hobby_writing_item(
        item_id="more_articles",
        source_id="locomo:conv-fixture:session_21:D21:6:turn",
        text=(
            "D21:6 Avery: I have been writing more articles because it lets "
            "me combine my love for reading with sharing great stories."
        ),
        score=0.83,
    )
    travel_interest = _travel_hobby_writing_item(
        item_id="travel_interest",
        source_id="locomo:conv-fixture:session_22:D22:3:turn",
        text=(
            "D22:3 Avery: I love traveling too. Have you been to Paris? "
            "The tower there looks incredible."
        ),
        score=0.82,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_travel_hobby_writing",
        items=(*filler_items, first_article, more_articles, travel_interest),
        token_budget=2600,
        query="What would be a good hobby related to Avery's travel dreams?",
    )

    selected_source_ids = {
        ref.source_id for selected in result.bundle.items for ref in selected.source_refs
    }
    assert "locomo:conv-fixture:session_20:D20:1:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_21:D21:6:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_22:D22:3:turn" in selected_source_ids
