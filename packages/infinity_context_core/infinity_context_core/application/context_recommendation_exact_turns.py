"""Exact-turn candidates for recommendation-list answer support."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_packer_answer_support_utils import (
    _diagnostic_signal_text,
)
from infinity_context_core.application.context_recommendation_answer_support import (
    is_recommendation_list_reason,
    recommendation_list_answer_kind,
    recommendation_list_answer_support_rank,
    recommendation_role_alignment_rank,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_ANAPHORIC_RECOMMENDATION_RE = re.compile(
    r"\brecommend(?:ed|ing|s)?\s+it\b(?!\s+as\b)|"
    r"\brecommend(?:ed|ing|s)?\s+that\b|"
    r"\brecommend(?:ed|ing|s)?\s+this\b(?!\s+\w)|"
    r"\b(?:it|that|this)\b(?=.{0,80}\brecommend(?:ed|ing|s)?\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOMMENDATION_SETUP_TURN_RE = re.compile(
    r"\b(?:any\s+(?:pointers?|recommendations?|suggestions?)|"
    r"do\s+you\s+think|how\s+about|should(?:n't)?\s+i|"
    r"what\s+(?:about|should)|would\s+you|could\s+i)\b",
    re.IGNORECASE | re.DOTALL,
)
_MAX_RECOMMENDATION_EXACT_TURN_CANDIDATES = 12


def exact_recommendation_list_turn_candidates(
    candidates: Mapping[str, ContextItem],
    *,
    query: str,
    ordered_families: tuple[str, ...] = (),
    limit: int = _MAX_RECOMMENDATION_EXACT_TURN_CANDIDATES,
) -> tuple[ContextItem, ...]:
    """Return focused exact turns that answer recommendation-list queries."""

    if limit <= 0:
        return ()
    family_order = {family: index for index, family in enumerate(ordered_families)}
    ranked_by_source_id: dict[str, tuple[tuple[object, ...], ContextItem]] = {}
    for family, item in _candidate_items(candidates, ordered_families=ordered_families):
        query_reason = _recommendation_query_reason(item)
        if not is_recommendation_list_reason(query_reason):
            continue
        for turn in _focused_recommendation_turns(item, query_reason=query_reason):
            answer_rank = recommendation_list_answer_support_rank(
                text=turn.text,
                query_reason=query_reason,
            )
            if answer_rank > 2:
                continue
            role_rank = recommendation_role_alignment_rank(
                text=turn.text,
                query=query,
                query_reason=query_reason,
            )
            if role_rank > 1:
                continue
            source_id = _primary_exact_turn_source_id(turn)
            rank_key = (
                answer_rank,
                role_rank,
                0 if len(turn.source_refs) > 1 else 1,
                family_order.get(family, len(family_order)),
                context_rank_key(turn),
            )
            existing = ranked_by_source_id.get(source_id)
            if existing is None or rank_key < existing[0]:
                ranked_by_source_id[source_id] = (rank_key, turn)
    return tuple(
        item for _, item in sorted(ranked_by_source_id.values(), key=lambda value: value[0])
    )[:limit]


def _candidate_items(
    candidates: Mapping[str, ContextItem],
    *,
    ordered_families: tuple[str, ...],
) -> tuple[tuple[str, ContextItem], ...]:
    if not ordered_families:
        return tuple(candidates.items())
    ordered = [
        (family, candidates[family]) for family in ordered_families if family in candidates
    ]
    seen = {family for family, _ in ordered}
    ordered.extend((family, item) for family, item in candidates.items() if family not in seen)
    return tuple(ordered)


def _focused_recommendation_turns(
    item: ContextItem,
    *,
    query_reason: str,
) -> tuple[ContextItem, ...]:
    focused: list[ContextItem] = []
    for ref in _exact_turn_refs(item):
        focused_text = _focused_turn_text(text=item.text, source_id=str(ref.source_id))
        if not focused_text:
            continue
        paired = _focused_recommendation_pair_candidate(
            item,
            current_ref=ref,
            focused_text=focused_text,
            query_reason=query_reason,
        )
        if paired is not None:
            previous_source_id = str(paired.source_refs[0].source_id)
            focused = [
                existing
                for existing in focused
                if _primary_exact_turn_source_id(existing) != previous_source_id
            ]
            focused.append(paired)
            continue
        if (
            len(item.source_refs) == 1
            and str(item.source_refs[0].source_id) == str(ref.source_id)
            and focused_text == item.text
        ):
            focused.append(item)
            continue
        focused.append(
            replace(
                item,
                item_id=(
                    f"{item.item_id}:recommendation_exact:"
                    f"{_safe_source_id_suffix(str(ref.source_id))}"
                ),
                text=focused_text,
                source_refs=(ref,),
                diagnostics=_recommendation_exact_turn_diagnostics(
                    item,
                    query_reason=query_reason,
                ),
            )
        )
    return tuple(focused)


def _focused_recommendation_pair_candidate(
    item: ContextItem,
    *,
    current_ref: SourceRef,
    focused_text: str,
    query_reason: str,
) -> ContextItem | None:
    kind = recommendation_list_answer_kind(
        text=focused_text,
        query_reason=query_reason,
    )
    if kind == "confirmation":
        should_pair = True
    else:
        should_pair = (
            kind == "direct"
            and _ANAPHORIC_RECOMMENDATION_RE.search(focused_text) is not None
        )
    if not should_pair:
        return None
    previous_ref = _previous_exact_turn_ref(item, current_ref=current_ref)
    if previous_ref is None:
        previous_ref = _previous_exact_turn_ref_from_source_id(current_ref)
        if previous_ref is None:
            return None
        return replace(
            item,
            item_id=(
                f"{item.item_id}:recommendation_pair:"
                f"{_safe_source_id_suffix(str(previous_ref.source_id))}:"
                f"{_safe_source_id_suffix(str(current_ref.source_id))}"
            ),
            text=focused_text,
            source_refs=(previous_ref, current_ref),
            diagnostics=_recommendation_exact_turn_diagnostics(
                item,
                query_reason=query_reason,
                paired=True,
            ),
        )
    previous_text = _focused_turn_text(
        text=item.text,
        source_id=str(previous_ref.source_id),
    )
    if _RECOMMENDATION_SETUP_TURN_RE.search(previous_text) is None:
        return None
    pair_text = _focused_turn_pair_text(
        text=item.text,
        first_source_id=str(previous_ref.source_id),
        second_source_id=str(current_ref.source_id),
    )
    if not pair_text:
        return None
    if (
        recommendation_list_answer_support_rank(
            text=pair_text,
            query_reason=query_reason,
        )
        > 2
    ):
        return None
    return replace(
        item,
        item_id=(
            f"{item.item_id}:recommendation_pair:"
            f"{_safe_source_id_suffix(str(previous_ref.source_id))}:"
            f"{_safe_source_id_suffix(str(current_ref.source_id))}"
        ),
        text=pair_text,
        source_refs=(previous_ref, current_ref),
        diagnostics=_recommendation_exact_turn_diagnostics(
            item,
            query_reason=query_reason,
            paired=True,
        ),
    )


def _recommendation_query_reason(item: ContextItem) -> str:
    return (
        _diagnostic_signal_text(item, "query_expansion_reason")
        or _diagnostic_signal_text(item, "bm25_lexical_query_reason")
        or _diagnostic_signal_text(item, "deterministic_rerank_query_reason")
    )


def _exact_turn_refs(item: ContextItem) -> tuple[SourceRef, ...]:
    return tuple(
        ref for ref in item.source_refs if str(ref.source_id).casefold().endswith(":turn")
    )


def _primary_exact_turn_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if source_id.casefold().endswith(":turn"):
            return source_id
    return ""


def _focused_turn_text(*, text: str, source_id: str) -> str:
    span = _focused_turn_span(text=text, source_id=source_id)
    if span is None:
        return ""
    start, end = span
    return text[start:end].strip()


def _focused_turn_span(*, text: str, source_id: str) -> tuple[int, int] | None:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return (0, len(text)) if text else None
    marker = marker_match.group(0)
    matches = tuple(re.finditer(rf"\b{re.escape(marker)}\b", text))
    if not matches:
        return None
    text_match = matches[0]
    for match in matches:
        following = text[match.end() : match.end() + 48]
        if re.match(r"\s+(?!D\d+:)[A-Z][A-Za-z'. -]{0,40}:", following):
            text_match = match
            break
    next_match = _DIALOGUE_MARKER_RE.search(text[text_match.end() :])
    end = text_match.end() + next_match.start() if next_match is not None else len(text)
    return (text_match.start(), end)


def _focused_turn_pair_text(
    *,
    text: str,
    first_source_id: str,
    second_source_id: str,
) -> str:
    first_span = _focused_turn_span(text=text, source_id=first_source_id)
    second_span = _focused_turn_span(text=text, source_id=second_source_id)
    if first_span is None or second_span is None:
        return ""
    start = min(first_span[0], second_span[0])
    end = max(first_span[1], second_span[1])
    return text[start:end].strip()


def _previous_exact_turn_ref(
    item: ContextItem,
    *,
    current_ref: SourceRef,
) -> SourceRef | None:
    refs_by_marker = {
        marker: ref
        for ref in _exact_turn_refs(item)
        if (marker := _source_id_dialogue_marker(str(ref.source_id)))
    }
    current_marker = _source_id_dialogue_marker(str(current_ref.source_id))
    if not current_marker:
        return None
    markers: list[str] = []
    for match in _DIALOGUE_MARKER_RE.finditer(item.text):
        marker = match.group(0)
        if marker in refs_by_marker and marker not in markers:
            markers.append(marker)
    try:
        index = markers.index(current_marker)
    except ValueError:
        return None
    if index <= 0:
        return None
    return refs_by_marker.get(markers[index - 1])


def _previous_exact_turn_ref_from_source_id(current_ref: SourceRef) -> SourceRef | None:
    source_id = str(current_ref.source_id)
    marker_match = re.search(r"\bD(?P<session>\d+):(?P<turn>\d+)(?=:turn$)", source_id)
    if marker_match is None:
        return None
    turn = int(marker_match.group("turn"))
    if turn <= 1:
        return None
    previous_marker = f"D{marker_match.group('session')}:{turn - 1}"
    previous_source_id = (
        f"{source_id[: marker_match.start()]}"
        f"{previous_marker}"
        f"{source_id[marker_match.end():]}"
    )
    return replace(current_ref, source_id=previous_source_id)


def _source_id_dialogue_marker(source_id: str) -> str:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    return marker_match.group(0) if marker_match is not None else ""


def _safe_source_id_suffix(source_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", source_id).strip("_").casefold()


def _recommendation_exact_turn_diagnostics(
    item: ContextItem,
    *,
    query_reason: str,
    paired: bool = False,
) -> dict[str, object]:
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["query_expansion_reason"] = query_reason
    score_signal_dict["recommendation_list_exact_turn"] = 1
    if paired:
        score_signal_dict["recommendation_list_exact_turn_pair"] = 1
    diagnostics["score_signals"] = score_signal_dict
    return diagnostics
