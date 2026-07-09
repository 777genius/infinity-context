"""English exact-turn support for book-author preference inference."""

from __future__ import annotations

import re
from collections.abc import Iterable

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_query_reason,
    _diagnostic_score_signals,
    _has_any_exact_turn_source_ref,
    _numeric_signal,
)
from infinity_context_core.application.dto import ContextItem

_MAX_EXACT_BOOK_AUTHOR_PREFERENCE_TURNS = 4
_BOOK_AUTHOR_WORLD_SIGNAL = "book_author_preference_world_evidence"
_BOOK_AUTHOR_REASONS = frozenset(
    {"book_suggestion_bridge", "book_reading_list_bridge"}
)
_TURN_SOURCE_ID_RE = re.compile(r"^(?P<group>.+):D\d+:\d+:turn$")


def exact_book_author_preference_turn_candidates(
    items: Iterable[ContextItem],
    *,
    query: str,
    limit: int = _MAX_EXACT_BOOK_AUTHOR_PREFERENCE_TURNS,
) -> tuple[ContextItem, ...]:
    """Return exact turns that support thematic fit for book-author questions."""

    del query
    if limit <= 0:
        return ()

    candidates = tuple(item for item in items if _is_book_author_world_evidence(item))
    source_group_counts: dict[str, int] = {}
    for item in candidates:
        group = _source_group(item)
        if group:
            source_group_counts[group] = source_group_counts.get(group, 0) + 1

    ranked = sorted(
        candidates,
        key=lambda item: (
            -source_group_counts.get(_source_group(item), 0),
            _book_author_world_turn_rank(item.text),
            -_book_author_world_signal(item),
            context_rank_key(item),
        ),
    )
    selected: list[ContextItem] = []
    selected_sources: set[str] = set()
    for item in ranked:
        source_id = _primary_source_id(item)
        if source_id in selected_sources:
            continue
        selected.append(item)
        selected_sources.add(source_id)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _is_book_author_world_evidence(item: ContextItem) -> bool:
    if _answer_support_query_reason(item) not in _BOOK_AUTHOR_REASONS:
        return False
    return _has_any_exact_turn_source_ref(item) and _book_author_world_signal(item) >= 3.0


def _book_author_world_signal(item: ContextItem) -> float:
    return _numeric_signal(
        _diagnostic_score_signals(item).get(_BOOK_AUTHOR_WORLD_SIGNAL)
    )


def _book_author_world_turn_rank(text: str) -> int:
    lowered = text.casefold()
    if any(
        phrase in lowered
        for phrase in (
            "magical world",
            "wizarding world",
            "characters, spells",
            "magical creatures",
        )
    ):
        return 0
    if any(
        phrase in lowered
        for phrase in ("movie", "tour", "places", "locations", "world", "universe")
    ):
        return 1
    if "fantasy" in lowered:
        return 2
    return 3


def _primary_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if source_id.casefold().endswith(":turn"):
            return source_id
    return str(item.source_refs[0].source_id) if item.source_refs else item.item_id


def _source_group(item: ContextItem) -> str:
    match = _TURN_SOURCE_ID_RE.match(_primary_source_id(item))
    return match.group("group") if match is not None else ""
