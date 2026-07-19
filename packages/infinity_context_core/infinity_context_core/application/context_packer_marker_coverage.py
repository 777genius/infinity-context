"""Related-marker and source-neighbor packing prepasses."""

from __future__ import annotations

import re
from dataclasses import replace

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_packer_answer_support import (
    _activity_competition_visual_answer_rank,
    _answer_support_diversity_family,
    _answer_support_family_item_key_for_query,
    _answer_support_query_reason,
    _diagnostic_score_signals,
    _has_any_exact_turn_source_ref,
    _is_activity_participation_answer_reason,
    _is_inventory_list_reason,
    _numeric_signal,
    _precise_answer_content_rank,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_packer_exact_turn_utils import (
    _canonical_dialogue_marker,
    _dialogue_marker_pattern,
    _primary_exact_turn_marker,
)
from infinity_context_core.application.context_packer_selection import (
    _SelectionState,
    _try_select_item,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_MAX_RELATED_MARKER_COVERAGE_TURN_ITEMS = 3
_RELATED_MARKER_COVERAGE_TURN_WINDOW = 4
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+[:-]\d+\b")
_GIFT_JOY_OBJECT_EVIDENCE_RE = re.compile(
    r"\b(?:gift(?:ed)?|gave|given|present(?:ed)?|stuffed\s+animal|"
    r"toy|keepsake|named|for\s+you)\b",
    re.IGNORECASE,
)
_GIFT_JOY_EFFECT_EVIDENCE_RE = re.compile(
    r"\b(?:brings?\s+(?:her|him|them|me|you)?\s*(?:a\s+lot\s+of\s+)?joy|"
    r"joy|happy|happiness|cheer(?:s|ed)?|comfort|cherish(?:ed)?|"
    r"focus(?:ed)?|remind(?:s|ed)?|good\s+vibes?)\b",
    re.IGNORECASE,
)


def _select_related_marker_coverage_turn_items(
    state: _SelectionState,
    *,
    answer_support_families: dict[str, ContextItem],
    ordered_answer_support_families: tuple[str, ...],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    selected_markers = tuple(
        marker for item in state.selected if (marker := _primary_exact_turn_marker(item))
    )
    if not selected_markers:
        return 0
    remaining = (
        _MAX_RELATED_MARKER_COVERAGE_TURN_ITEMS
        - _selected_related_marker_coverage_turn_count(state)
    )
    if remaining <= 0:
        return 0
    selected_marker_set = set(selected_markers)
    selected_pottery_sessions = _selected_pottery_answer_source_sessions(state)
    selected_pottery_companion_sessions = _selected_pottery_marker_coverage_companion_sessions(
        state
    )
    selected_anchor_sessions = tuple(
        dict.fromkeys(
            session
            for item in state.selected
            if _primary_exact_turn_marker(item)
            if (session := _source_session_identity(_primary_exact_turn_source_id(item)))
        )
    )
    selected_anchor_session_order = {
        session: index for index, session in enumerate(selected_anchor_sessions)
    }
    covered_marker_sessions = _selected_marker_coverage_sessions(state)
    best_ranked_by_session: dict[str, tuple[tuple[object, ...], ContextItem]] = {}
    fallback_ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for family in ordered_answer_support_families:
        if not family.startswith("query_reason_marker_coverage_source_group:"):
            continue
        item = answer_support_families[family]
        query_reason = _answer_support_query_reason(item)
        if not (
            _is_inventory_list_reason(query_reason)
            or _is_activity_participation_answer_reason(query_reason)
            or _is_pottery_type_query_reason(query_reason)
        ):
            continue
        marker_refs = tuple(
            ref for ref in item.source_refs if str(ref.source_id).casefold().endswith(":turn")
        )
        for ref in marker_refs:
            marker = _source_ref_marker(ref)
            if marker in selected_marker_set:
                continue
            focused_item = _focused_marker_coverage_turn_item(item, ref=ref)
            session = _source_session_identity(str(ref.source_id))
            is_pottery_companion = _is_pottery_marker_coverage_companion_turn(
                focused_item,
                query_reason=query_reason,
                session=session,
                selected_pottery_sessions=selected_pottery_sessions,
                selected_pottery_companion_sessions=selected_pottery_companion_sessions,
            )
            distance = _nearest_dialogue_marker_distance(marker, selected_markers)
            if not is_pottery_companion and (
                distance is None or distance > _RELATED_MARKER_COVERAGE_TURN_WINDOW
            ):
                continue
            coverage_rank = 0 if session and session not in covered_marker_sessions else 1
            anchor_rank = _marker_coverage_anchor_rank(item.text, marker=marker)
            activity_competition_direct_rank = 1
            if query_reason == "activity_competition_evidence_bridge":
                activity_competition_direct_rank = _activity_competition_visual_answer_rank(
                    focused_item,
                    query=query,
                    query_reason=query_reason,
                )
                if activity_competition_direct_rank > 0:
                    continue
            rank_key = (
                activity_competition_direct_rank,
                coverage_rank,
                0 if is_pottery_companion else 1,
                (
                    _precise_answer_content_rank(
                        focused_item,
                        query_reason="pottery_type_bridge",
                    )
                    if is_pottery_companion
                    else 0
                ),
                anchor_rank,
                distance if distance is not None else _RELATED_MARKER_COVERAGE_TURN_WINDOW + 1,
                selected_anchor_session_order.get(session, len(selected_anchor_session_order)),
                _answer_support_family_item_key_for_query(item, query=""),
                context_rank_key(item),
            )
            if session and session in selected_anchor_session_order:
                existing = best_ranked_by_session.get(session)
                if existing is None or rank_key < existing[0]:
                    best_ranked_by_session[session] = (rank_key, focused_item)
                continue
            fallback_ranked.append((rank_key, focused_item))

    ranked = tuple(best_ranked_by_session.values()) + tuple(fallback_ranked)
    selected = 0
    selected_markers_seen: set[str] = set()
    selected_pottery_companion_sessions_seen: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= remaining:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers_seen:
            continue
        pottery_companion_session = _pottery_marker_coverage_companion_session(item)
        if (
            pottery_companion_session
            and pottery_companion_session in selected_pottery_companion_sessions_seen
        ):
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers_seen.add(marker)
            if pottery_companion_session:
                selected_pottery_companion_sessions_seen.add(pottery_companion_session)
    return selected


def _selected_related_marker_coverage_turn_count(state: _SelectionState) -> int:
    return sum(
        1
        for item in state.selected
        if _numeric_signal(_diagnostic_score_signals(item).get("related_marker_coverage_turn")) > 0
    )


def _selected_marker_coverage_sessions(state: _SelectionState) -> frozenset[str]:
    sessions: set[str] = set()
    for item in state.selected:
        family = _answer_support_diversity_family(item)
        score_signals = _diagnostic_score_signals(item)
        if not (
            family.startswith("query_reason_marker_coverage_source_group:")
            or _numeric_signal(score_signals.get("related_marker_coverage_turn")) > 0
        ):
            continue
        for ref in item.source_refs:
            session = _source_session_identity(str(ref.source_id))
            if session:
                sessions.add(session)
    return frozenset(sessions)


def _selected_pottery_answer_source_sessions(state: _SelectionState) -> frozenset[str]:
    sessions: set[str] = set()
    for item in state.selected:
        family = _answer_support_diversity_family(item)
        if family.startswith("query_reason_marker_coverage_source_group:"):
            continue
        if _numeric_signal(_diagnostic_score_signals(item).get("related_marker_coverage_turn")) > 0:
            continue
        if not _is_pottery_type_query_reason(_answer_support_query_reason(item)):
            continue
        for ref in item.source_refs:
            session = _source_session_identity(str(ref.source_id))
            if session:
                sessions.add(session)
    return frozenset(sessions)


def _selected_pottery_marker_coverage_companion_sessions(
    state: _SelectionState,
) -> frozenset[str]:
    sessions: set[str] = set()
    for item in state.selected:
        session = _pottery_marker_coverage_companion_session(item)
        if session:
            sessions.add(session)
    return frozenset(sessions)


def _pottery_marker_coverage_companion_session(item: ContextItem) -> str:
    if not _is_pottery_type_query_reason(_answer_support_query_reason(item)):
        return ""
    if _numeric_signal(_diagnostic_score_signals(item).get("related_marker_coverage_turn")) <= 0:
        return ""
    for ref in item.source_refs:
        session = _source_session_identity(str(ref.source_id))
        if session:
            return session
    return ""


def _is_pottery_marker_coverage_companion_turn(
    item: ContextItem,
    *,
    query_reason: str,
    session: str,
    selected_pottery_sessions: frozenset[str],
    selected_pottery_companion_sessions: frozenset[str],
) -> bool:
    if not session or session not in selected_pottery_sessions:
        return False
    if session in selected_pottery_companion_sessions:
        return False
    if not _is_pottery_type_query_reason(query_reason):
        return False
    content_rank = _precise_answer_content_rank(
        item,
        query_reason="pottery_type_bridge",
    )
    return content_rank in {1, 2}


def _is_pottery_type_query_reason(query_reason: str) -> bool:
    return query_reason.replace("_", "-") == "pottery-type-bridge"


def _source_ref_marker(ref: SourceRef) -> str:
    match = _DIALOGUE_MARKER_RE.search(str(ref.source_id))
    return _canonical_dialogue_marker(match.group(0)) if match is not None else ""


def _source_session_identity(source_id: str) -> str:
    parts = str(source_id or "").split(":")
    if len(parts) >= 6 and parts[-1] == "turn" and parts[-3].startswith("D"):
        return ":".join(parts[:-3])
    if len(parts) >= 5 and parts[-1] == "turn" and re.fullmatch(r"D\d+-\d+", parts[-2]):
        return ":".join(parts[:-2])
    if len(parts) >= 4 and parts[-1] in {"events", "observation", "summary"}:
        return ":".join(parts[:-1])
    return ""


def _marker_coverage_anchor_rank(text: str, *, marker: str) -> int:
    marker_matches = tuple(re.finditer(_dialogue_marker_pattern(marker), text))
    if not marker_matches:
        return 3
    all_markers = tuple(_DIALOGUE_MARKER_RE.finditer(text))
    if all_markers and _canonical_dialogue_marker(all_markers[0].group(0)) == marker:
        return 0
    for marker_match in marker_matches:
        segment_start = marker_match.start()
        segment_end = len(text)
        for candidate in all_markers:
            if candidate.start() < marker_match.start():
                segment_start = candidate.start()
                continue
            if candidate.start() > marker_match.start():
                segment_end = candidate.start()
                break
        segment = text[segment_start:segment_end]
        related_turns_index = segment.casefold().find("related turns:")
        marker_index = marker_match.start() - segment_start
        if related_turns_index < 0 or marker_index < related_turns_index:
            return 1
    return 2


def _nearest_dialogue_marker_distance(
    marker: str,
    selected_markers: tuple[str, ...],
) -> int | None:
    marker_parts = _dialogue_marker_parts(marker)
    if marker_parts is None:
        return None
    distances: list[int] = []
    for selected_marker in selected_markers:
        selected_parts = _dialogue_marker_parts(selected_marker)
        if selected_parts is None or selected_parts[0] != marker_parts[0]:
            continue
        distances.append(abs(selected_parts[1] - marker_parts[1]))
    return min(distances) if distances else None


def _dialogue_marker_parts(marker: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"D(\d+)[:-](\d+)", marker)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _focused_marker_coverage_turn_item(item: ContextItem, *, ref: SourceRef) -> ContextItem:
    source_id = str(ref.source_id)
    focused_text = _focused_turn_text(text=item.text, source_id=source_id)
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["related_marker_coverage_turn"] = 1
    diagnostics["score_signals"] = score_signal_dict
    return replace(
        item,
        item_id=f"{item.item_id}:related_marker:{_safe_source_id_suffix(source_id)}",
        text=focused_text,
        source_refs=(ref,),
        diagnostics=diagnostics,
    )


def _focused_turn_text(*, text: str, source_id: str) -> str:
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return text
    marker = _canonical_dialogue_marker(marker_match.group(0))
    matches = tuple(re.finditer(_dialogue_marker_pattern(marker), text))
    if not matches:
        return text
    text_match = matches[0]
    for match in matches:
        following = text[match.end() : match.end() + 48]
        if re.match(r"\s+[A-Z][^:\n]{0,40}:", following):
            text_match = match
            break
    next_match = _DIALOGUE_MARKER_RE.search(text[text_match.end() :])
    end = text_match.end() + next_match.start() if next_match is not None else len(text)
    return text[text_match.start() : end].strip() or text


def _safe_source_id_suffix(source_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", source_id).strip("_").casefold()


def _is_gift_joy_source_group_answer_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason not in {
        "decomposition_action_role",
        "possession_gift_object_bridge",
    }:
        return False
    if not item.source_refs or not _has_any_exact_turn_source_ref(item):
        return False
    text = item.text
    return (
        _GIFT_JOY_OBJECT_EVIDENCE_RE.search(text) is not None
        and _GIFT_JOY_EFFECT_EVIDENCE_RE.search(text) is not None
    )


def _gift_joy_source_group_rank(item: ContextItem) -> tuple[int, int, int]:
    source_ids = tuple(str(ref.source_id or "") for ref in item.source_refs)
    has_source_group_ref = any(
        source_id.endswith(":observation") or source_id.endswith(":summary")
        for source_id in source_ids
    )
    has_related_turns = "related turns" in item.text.casefold()
    return (
        0 if has_source_group_ref else 1,
        0 if has_related_turns else 1,
        -len(source_ids),
    )
