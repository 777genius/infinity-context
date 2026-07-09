from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_answer_support_slots import (
    _book_reading_answer_content_rank,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _book_reading_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
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
                chunk_id=item_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "query_expansion_reason": "book_reading_list_bridge",
        },
    )


def test_context_packer_keeps_multiple_exact_book_reading_turns() -> None:
    broad_context = tuple(
        _book_reading_item(
            item_id=f"generic_reading_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            text=f"D{index}:2 Tim talked about books and reading as a broad interest.",
            score=0.99 - index * 0.001,
        )
        for index in range(1, 9)
    )
    exact_turns = (
        _book_reading_item(
            item_id="wrong_speaker_book",
            source_id="locomo:conv-fixture:session_10:D10:7:turn",
            text='D10:7 Alex: "Solaris" is great. It is a classic novel.',
            score=0.98,
        ),
        _book_reading_item(
            item_id="last_year_book",
            source_id="locomo:conv-fixture:session_11:D11:26:turn",
            text='D11:26 Tim: The book I read last year was "Station Eleven".',
            score=0.81,
        ),
        _book_reading_item(
            item_id="childhood_book",
            source_id="locomo:conv-fixture:session_22:D22:13:turn",
            text='D22:13 Tim: I loved reading "A Wrinkle in Time" as a kid.',
            score=0.80,
        ),
        _book_reading_item(
            item_id="favorite_book",
            source_id="locomo:conv-fixture:session_26:D26:36:turn",
            text='D26:36 Tim: My favorite book is "The Left Hand of Darkness".',
            score=0.79,
        ),
    )

    result = ContextPacker().pack(
        bundle_id="ctx_book_reading_inventory",
        items=(*broad_context, *exact_turns),
        token_budget=260,
        query="What books has Tim read?",
        max_rendered_chars=1400,
    )

    rendered = result.bundle.rendered_text
    assert "Station Eleven" in rendered
    assert "A Wrinkle in Time" in rendered
    assert "The Left Hand of Darkness" in rendered
    assert "Solaris" not in rendered
    assert rendered.count("broad interest") <= 1


def test_context_packer_keeps_named_work_affinity_as_book_reading_evidence() -> None:
    broad_context = tuple(
        _book_reading_item(
            item_id=f"generic_reading_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            text=f"D{index}:2 Tim talked about books and reading as a broad interest.",
            score=0.99 - index * 0.001,
        )
        for index in range(1, 8)
    )
    named_work_affinity = _book_reading_item(
        item_id="named_work_affinity",
        source_id="locomo:conv-fixture:session_4:D4:7:turn",
        text=(
            "D4:7 Tim: For sure! The River School and Moon Garden are amazing - "
            "I'm totally hooked! I could chat about them forever!"
        ),
        score=0.76,
    )
    wrong_speaker_affinity = _book_reading_item(
        item_id="wrong_speaker_affinity",
        source_id="locomo:conv-fixture:session_5:D5:7:turn",
        text=(
            "D5:7 Alex: The River School and Moon Garden are amazing - "
            "I'm totally hooked! I could chat about them forever!"
        ),
        score=0.98,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_named_work_affinity_book_reading",
        items=(*broad_context, wrong_speaker_affinity, named_work_affinity),
        token_budget=145,
        query="What books has Tim read?",
        max_rendered_chars=900,
    )

    rendered = result.bundle.rendered_text
    assert "Moon Garden are amazing" in rendered
    assert "D5:7 Alex" not in rendered
    assert rendered.count("broad interest") <= 1


def test_book_reading_rank_requires_title_case_for_reading_title_patterns() -> None:
    assert (
        _book_reading_answer_content_rank(
            'D4:7 Tim: I loved reading "The River Name" as a kid.'
        )
        == 0
    )
    assert (
        _book_reading_answer_content_rank(
            "D7:9 Tim: Books guide me, motivate me and help me discover who I am. "
            "They are a huge part of my journey and keep me going."
        )
        == 0
    )
    assert (
        _book_reading_answer_content_rank(
            "D4:7 Tim: For sure! The River School and Moon Garden are amazing - "
            "I'm totally hooked! I could chat about them forever!"
        )
        == 0
    )
    assert (
        _book_reading_answer_content_rank(
            "D27:15 Tim: I will always love reading, personally."
        )
        > 1
    )
    assert (
        _book_reading_answer_content_rank(
            "D8:12 Tim: I've been reading a bunch of fantasy books."
        )
        > 1
    )
