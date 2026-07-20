"""Shared source-sibling evidence classifiers."""

from __future__ import annotations

import re

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_packer_inventory_slots import (
    _game_inventory_answer_directness_rank,
)
from infinity_context_core.application.context_source_sibling_patterns import (
    _ACTIVITY_COMPANION_ACTIVITY_SOURCE_SIBLING_RE,
    _ACTIVITY_COMPANION_QUERY_RE,
    _ACTIVITY_COMPANION_SOURCE_SIBLING_REASONS,
    _ACTIVITY_COMPANION_WITH_SOURCE_SIBLING_RE,
    _BOARD_GAME_SOURCE_SIBLING_QUERY_RE,
    _BOARD_GAME_SOURCE_SIBLING_REASONS,
    _CAUSE_AWARENESS_EVENT_SOURCE_SIBLING_RE,
    _CHILDREN_PREFERENCE_SOURCE_SIBLING_RE,
    _CLASSICAL_MUSIC_PREFERENCE_SOURCE_SIBLING_RE,
    _COLLECTIBLE_OBJECT_SOURCE_SIBLING_QUERY_RE,
    _COLLECTIBLE_OBJECT_SOURCE_SIBLING_RE,
    _COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE,
    _COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE,
    _COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE,
    _COMMON_INTEREST_ANSWER_SLOT_QUERY,
    _COMMON_INTEREST_SOURCE_SIBLING_QUERY_RE,
    _COMMON_INTEREST_SOURCE_SIBLING_REASONS,
    _GAMING_MEDIUM_DIRECT_SOURCE_SIBLING_RE,
    _GAMING_MEDIUM_SOURCE_SIBLING_QUERY_RE,
    _GAMING_MEDIUM_SOURCE_SIBLING_REASONS,
    _MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE,
    _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE,
    _OUTDOOR_ACTIVITY_VISUAL_COMPANION_SOURCE_SIBLING_RE,
    _OUTDOOR_PREFERENCE_SOURCE_SIBLING_RE,
    _PET_ACQUISITION_DATE_ANCHOR_RE,
    _PET_ACQUISITION_SOURCE_SIBLING_RE,
    _PRECISE_TURN_RETRIEVAL_TEXT_RE,
    _SENTIMENTAL_REMINDER_SOURCE_SIBLING_RE,
    _TEMPORAL_DIRECT_SOURCE_SIBLING_RE,
    _TEMPORAL_EVENT_ACTION_SOURCE_SIBLING_RE,
    _TEMPORAL_EVENT_QUERY_STOPWORDS,
    _TEMPORAL_EVENT_QUERY_TOKEN_RE,
    _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE,
)
from infinity_context_core.application.context_temporal_answer_grounding import (
    has_grounded_temporal_text_answer_evidence,
)


def _is_activity_companion_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if (
        expansion_reason not in _ACTIVITY_COMPANION_SOURCE_SIBLING_REASONS
        and not _ACTIVITY_COMPANION_QUERY_RE.search(expansion_query)
    ):
        return False
    return (
        _ACTIVITY_COMPANION_ACTIVITY_SOURCE_SIBLING_RE.search(text) is not None
        and _ACTIVITY_COMPANION_WITH_SOURCE_SIBLING_RE.search(text) is not None
    )


def _query_person_matches_text(*, expansion_query: str, text: str) -> bool:
    names = tuple(
        dict.fromkeys(
            match.group(0)
            for match in re.finditer(r"\b[A-Z][a-z]{2,}\b", expansion_query)
            if match.group(0)
            not in {
                "What",
                "Which",
                "Where",
                "When",
                "Who",
                "Whom",
                "Whose",
                "Why",
                "How",
            }
        )
    )
    if not names:
        return True
    text_casefold = text.casefold()
    return any(
        re.search(rf"\b{re.escape(name)}\s*:", text) is not None
        or re.search(rf"\b{re.escape(name.casefold())}\b", text_casefold) is not None
        for name in names
    )


def _is_precise_turn_retrieval_text(text: str) -> bool:
    return _PRECISE_TURN_RETRIEVAL_TEXT_RE.search(text) is not None


def _is_common_interest_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if _is_movie_seen_direct_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_common_interest_animal_affinity_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_common_interest_animal_affinity_window_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    return (
        _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and _common_interest_answer_slot_count(text) > 0
    )


def _is_common_interest_animal_affinity_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and (
            _COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
            or _COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE.search(text) is not None
        )
    )


def _is_common_interest_animal_affinity_window_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_common_interest_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _COMMON_INTEREST_ANIMAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _COMMON_INTEREST_ANIMAL_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        and _COMMON_INTEREST_AFFINITY_REPLY_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_movie_seen_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in _COMMON_INTEREST_SOURCE_SIBLING_REASONS
        and _MOVIE_SEEN_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _is_precise_turn_retrieval_text(text)
        and _MOVIE_SEEN_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_board_game_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_board_game_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and _game_inventory_answer_directness_rank(text) == 0
    )


def _is_gaming_medium_direct_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        _is_gaming_medium_source_sibling_scope(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
        )
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and _is_precise_turn_retrieval_text(text)
        and _GAMING_MEDIUM_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_gaming_medium_source_sibling_scope(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _GAMING_MEDIUM_SOURCE_SIBLING_REASONS
        or _GAMING_MEDIUM_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _is_board_game_source_sibling_scope(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _BOARD_GAME_SOURCE_SIBLING_REASONS
        or _BOARD_GAME_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _is_common_interest_source_sibling_scope(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _COMMON_INTEREST_SOURCE_SIBLING_REASONS
        or _COMMON_INTEREST_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )


def _common_interest_answer_slot_count(text: str) -> int:
    return aggregation_answer_slot_count(
        query=_COMMON_INTEREST_ANSWER_SLOT_QUERY,
        text=text,
    )


def _is_temporal_source_sibling_strong(*, expansion_query: str, text: str) -> bool:
    return (
        _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
        and _TEMPORAL_DIRECT_SOURCE_SIBLING_RE.search(text) is not None
        and _query_person_matches_text(expansion_query=expansion_query, text=text)
        and has_grounded_temporal_text_answer_evidence(query=expansion_query, text=text)
    )


def _is_temporal_event_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "temporal_event_detail_bridge":
        return False
    if _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None:
        return False
    if _TEMPORAL_EVENT_ACTION_SOURCE_SIBLING_RE.search(text) is None:
        return False
    query_tokens = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TEMPORAL_EVENT_QUERY_TOKEN_RE.findall(expansion_query)
            if len(token) >= 3
            and token.casefold() not in _TEMPORAL_EVENT_QUERY_STOPWORDS
            and not token[:1].isupper()
        )
    )
    if len(query_tokens) < 4:
        return False
    text_casefold = text.casefold()
    hits = sum(
        1
        for token in query_tokens
        if re.search(rf"\b{re.escape(token)}\b", text_casefold) is not None
    )
    return hits >= 4


def _is_pet_acquisition_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason != "pet_acquisition_date_bridge":
        return False
    if _TEMPORAL_QUESTION_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None:
        return False
    if _PET_ACQUISITION_SOURCE_SIBLING_RE.search(text) is None:
        return _is_pet_acquisition_date_anchor(
            expansion_query=expansion_query,
            text=text,
        )
    query_terms = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TEMPORAL_EVENT_QUERY_TOKEN_RE.findall(expansion_query)
            if len(token) >= 3
            and token.casefold()
            not in {
                *_TEMPORAL_EVENT_QUERY_STOPWORDS,
                "adopt",
                "adopted",
                "get",
                "got",
            }
        )
    )
    if not query_terms:
        return True
    text_casefold = text.casefold()
    return any(
        re.search(rf"\b{re.escape(term)}\b", text_casefold) is not None for term in query_terms
    )


def _is_pet_acquisition_date_anchor(*, expansion_query: str, text: str) -> bool:
    if _PET_ACQUISITION_DATE_ANCHOR_RE.search(text) is None:
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    query_terms = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TEMPORAL_EVENT_QUERY_TOKEN_RE.findall(expansion_query)
            if len(token) >= 3 and token[:1].isupper()
        )
    )
    if len(query_terms) < 2:
        return False
    text_casefold = text.casefold()
    hits = sum(
        1 for term in query_terms if re.search(rf"\b{re.escape(term)}\b", text_casefold) is not None
    )
    return hits >= 2


def _is_cause_awareness_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "cause_awareness_event_bridge"
        and _CAUSE_AWARENESS_EVENT_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_classical_music_preference_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "classical_music_preference_bridge"
        and _CLASSICAL_MUSIC_PREFERENCE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_sentimental_reminder_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "sentimental_reminder_bridge"
        and _SENTIMENTAL_REMINDER_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_collectible_object_source_sibling_answer_evidence(
    *,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if expansion_reason not in {
        "decomposition_collectible_object",
        "decomposition_commonality",
        "decomposition_activity_participation",
        "decomposition_followup_task",
        "original_query",
    }:
        return False
    if _COLLECTIBLE_OBJECT_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is None:
        return False
    if not _query_person_matches_text(expansion_query=expansion_query, text=text):
        return False
    return _COLLECTIBLE_OBJECT_SOURCE_SIBLING_RE.search(text) is not None


def _is_outdoor_preference_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason in {"outdoor_preference_bridge", "outdoor_nature_memory_bridge"}
        and _OUTDOOR_PREFERENCE_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "outdoor_activity_inventory_bridge"
        and _OUTDOOR_ACTIVITY_VISUAL_COMPANION_SOURCE_SIBLING_RE.search(text) is not None
    )


def _is_children_preference_source_sibling_strong_for_reason(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        expansion_reason == "children_preference_bridge"
        and _CHILDREN_PREFERENCE_SOURCE_SIBLING_RE.search(text) is not None
    )
