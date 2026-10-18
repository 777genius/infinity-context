"""Unit tests for union-preserving new-source displacement under char pressure."""

from infinity_context_core.application.context_packer_selection import (
    _rendered_char_count,
    _select_item,
    _SelectionState,
    _try_new_source_displacement,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _item(*, item_id: str, source_id: str, text: str, score: float) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id=source_id, chunk_id=item_id),
        ),
        diagnostics={"memory_scope_id": "memory_scope_default"},
    )


def _state(items: tuple[ContextItem, ...]) -> _SelectionState:
    state = _SelectionState(
        selected=[],
        selected_keys=set(),
        selected_answer_support_families=set(),
        selected_chunks_by_source={},
        selected_source_capped_items_by_source={},
        selected_art_style_items_by_source_group={},
    )
    for item in items:
        _select_item(state, item=item, item_tokens=1)
    return state


def _filled(*, with_ids: tuple[str, ...], items: dict[str, ContextItem]) -> _SelectionState:
    return _state(tuple(items[item_id] for item_id in with_ids))


def test_displaces_duplicate_source_item_for_unseen_source() -> None:
    items = {
        "a1": _item(item_id="a1", source_id="src-a", text="alpha best " * 20, score=0.9),
        "a2": _item(item_id="a2", source_id="src-a", text="alpha dup " * 40, score=0.5),
        "b1": _item(item_id="b1", source_id="src-b", text="beta only " * 20, score=0.8),
    }
    state = _filled(with_ids=("a1", "a2", "b1"), items=items)
    incoming = _item(item_id="c1", source_id="src-c", text="gamma new " * 15, score=0.4)
    char_budget = _rendered_char_count(tuple(state.selected)) + 50

    assert _try_new_source_displacement(
        state,
        item=incoming,
        budget=10_000,
        char_budget=char_budget,
        protected_keys=frozenset(),
    )

    kept = {item.item_id for item in state.selected}
    assert kept == {"a1", "b1", "c1"}
    sources = {ref.source_id for item in state.selected for ref in item.source_refs}
    assert sources == {"src-a", "src-b", "src-c"}


def test_rejects_incoming_item_covering_only_known_sources() -> None:
    items = {
        "a1": _item(item_id="a1", source_id="src-a", text="alpha best " * 20, score=0.9),
        "a2": _item(item_id="a2", source_id="src-a", text="alpha dup " * 40, score=0.5),
    }
    state = _filled(with_ids=("a1", "a2"), items=items)
    incoming = _item(item_id="a3", source_id="src-a", text="alpha third " * 10, score=0.4)
    char_budget = _rendered_char_count(tuple(state.selected)) + 50

    assert not _try_new_source_displacement(
        state,
        item=incoming,
        budget=10_000,
        char_budget=char_budget,
        protected_keys=frozenset(),
    )
    assert {item.item_id for item in state.selected} == {"a1", "a2"}


def test_never_drops_last_item_covering_a_source() -> None:
    items = {
        "a1": _item(item_id="a1", source_id="src-a", text="alpha best " * 20, score=0.9),
        "b1": _item(item_id="b1", source_id="src-b", text="beta unique " * 40, score=0.5),
    }
    state = _filled(with_ids=("a1", "b1"), items=items)
    incoming = _item(item_id="c1", source_id="src-c", text="gamma new " * 15, score=0.4)
    char_budget = _rendered_char_count(tuple(state.selected)) + 50

    assert not _try_new_source_displacement(
        state,
        item=incoming,
        budget=10_000,
        char_budget=char_budget,
        protected_keys=frozenset(),
    )
    assert {item.item_id for item in state.selected} == {"a1", "b1"}


def test_drops_two_duplicate_items_when_one_does_not_free_enough() -> None:
    items = {
        "a1": _item(item_id="a1", source_id="src-a", text="alpha best " * 20, score=0.9),
        "a2": _item(item_id="a2", source_id="src-a", text="alpha dup2 " * 10, score=0.5),
        "a3": _item(item_id="a3", source_id="src-a", text="alpha dup3 " * 10, score=0.4),
        "b1": _item(item_id="b1", source_id="src-b", text="beta only " * 20, score=0.8),
    }
    state = _filled(with_ids=("a1", "a2", "a3", "b1"), items=items)
    incoming = _item(item_id="c1", source_id="src-c", text="gamma new " * 30, score=0.3)
    char_budget = _rendered_char_count(tuple(state.selected)) + 50

    assert _try_new_source_displacement(
        state,
        item=incoming,
        budget=10_000,
        char_budget=char_budget,
        protected_keys=frozenset(),
    )

    kept = {item.item_id for item in state.selected}
    assert "c1" in kept
    assert "a1" in kept
    assert "b1" in kept
    assert not {"a2", "a3"} <= kept
    sources = {ref.source_id for item in state.selected for ref in item.source_refs}
    assert sources == {"src-a", "src-b", "src-c"}


def test_respects_protected_keys() -> None:
    items = {
        "a1": _item(item_id="a1", source_id="src-a", text="alpha best " * 20, score=0.9),
        "a2": _item(item_id="a2", source_id="src-a", text="alpha dup " * 40, score=0.5),
    }
    state = _filled(with_ids=("a1", "a2"), items=items)
    incoming = _item(item_id="c1", source_id="src-c", text="gamma new " * 15, score=0.4)
    char_budget = _rendered_char_count(tuple(state.selected)) + 50
    protected = frozenset(
        {next(key for key in state.selected_keys if key[1] == "a2")},
    )

    assert not _try_new_source_displacement(
        state,
        item=incoming,
        budget=10_000,
        char_budget=char_budget,
        protected_keys=protected,
    )
    assert {item.item_id for item in state.selected} == {"a1", "a2"}
