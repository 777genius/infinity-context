"""Source-turn order helpers for temporal context retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping

from infinity_context_core.application.context_diagnostics import safe_diagnostic_mapping
from infinity_context_core.application.context_temporal_source_identity import (
    conversation_source_scope_identity_from_label,
    direct_source_scope_identity_from_label,
    explicit_ordinal_session_scope_identity_from_value,
    explicit_session_scope_identity_from_value,
    source_identity_from_label,
    source_identity_matches,
    source_scope_identity_from_label,
    source_scope_identity_from_mapping,
)
from infinity_context_core.application.context_temporal_source_turn_labels import (
    SOURCE_TURN_LABEL_NUMBER_PATTERN,
    canonicalize_natural_source_turn_labels,
    source_turn_label_number_value,
)
from infinity_context_core.application.context_temporal_source_turn_patterns import (
    _AFTER_SCOPED_SOURCE_TURN_RE,
    _AFTER_SOURCE_TURN_RE,
    _BEFORE_SCOPED_SOURCE_TURN_RE,
    _BEFORE_SOURCE_TURN_RE,
    _BETWEEN_SCOPED_SOURCE_TURN_RE,
    _BETWEEN_SOURCE_TURN_RE,
    _COMPACT_RANGE_SOURCE_TURN_RE,
    _IMPLICIT_RANGE_SOURCE_TURN_RE,
    _NEAR_SCOPED_SOURCE_TURN_RE,
    _NEAR_SOURCE_TURN_RE,
    _NEXT_AFTER_SCOPED_SOURCE_TURN_RE,
    _NEXT_AFTER_SOURCE_TURN_RE,
    _NEXT_ONE_AFTER_SCOPED_SOURCE_TURN_RE,
    _NEXT_ONE_AFTER_SOURCE_TURN_RE,
    _PREVIOUS_BEFORE_SCOPED_SOURCE_TURN_RE,
    _PREVIOUS_BEFORE_SOURCE_TURN_RE,
    _PREVIOUS_ONE_BEFORE_SCOPED_SOURCE_TURN_RE,
    _PREVIOUS_ONE_BEFORE_SOURCE_TURN_RE,
    _QUERY_DIRECT_SOURCE_SCOPE_RE,
    _QUERY_SOURCE_SCOPE_RE,
    _SAME_DIALOGUE_RANGE_SOURCE_TURN_RE,
    _SOURCE_TURN_RE,
    _WITHIN_AFTER_SCOPED_SOURCE_TURN_RE,
    _WITHIN_AFTER_SOURCE_TURN_RE,
    _WITHIN_BEFORE_SCOPED_SOURCE_TURN_RE,
    _WITHIN_BEFORE_SOURCE_TURN_RE,
    _WITHIN_SCOPED_SOURCE_TURN_RE,
    _WITHIN_SOURCE_TURN_RE,
)
from infinity_context_core.application.context_temporal_source_turn_types import (
    SourceTurnRef,
    SourceTurnSequenceRequest,
    SourceTurnSequenceSignal,
)
from infinity_context_core.application.dto import ContextItem

_OPTIONAL_NUMBER_LABEL_PATTERN = r"(?:(?:number|no\.?)[_:\-\s#]+)?"
_QUERY_NATURAL_DIALOGUE_SCOPE_RE = re.compile(
    r"\b(?:in|from|for|within)\s+(?:the\s+)?"
    r"(?:(?:source\s+)?(?:ref|reference)|source|conversation|conv)?\s*"
    r"(?:locomo\s+)?(?:session|conversation|conv|dialogue|dialog|dia)\s+"
    rf"#?\s*(?P<scope>{SOURCE_TURN_LABEL_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)
_QUERY_EXPLICIT_NATURAL_DIALOGUE_SCOPE_RE = re.compile(
    r"\b(?:in|from|for|within)\s+(?:the\s+)?"
    r"(?:(?:source\s+)?(?:ref|reference)|source)\s+"
    r"(?:locomo\s+)?(?:session|conversation|conv|dialogue|dialog|dia)\s+"
    rf"#?\s*(?P<scope>{SOURCE_TURN_LABEL_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)
_QUERY_BARE_EXPLICIT_NATURAL_DIALOGUE_SCOPE_RE = re.compile(
    r"\b(?:(?:source\s+)?(?:ref|reference)|source)\s+"
    r"(?:locomo\s+)?(?:session|conversation|conv|dialogue|dialog|dia)\s+"
    rf"#?\s*(?P<scope>{SOURCE_TURN_LABEL_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)


def source_turn_sequence_request(query: str) -> SourceTurnSequenceRequest:
    """Return explicit before/after source-turn boundaries from a query."""

    query_scope_identity = _query_explicit_natural_source_scope_identity(query)
    query = canonicalize_natural_source_turn_labels(query)
    query_scope_identity = query_scope_identity or _query_source_scope_identity(query)
    between_after, between_before = _source_turn_pairs_for_regex(
        _BETWEEN_SOURCE_TURN_RE,
        query,
    )
    implicit_range_after, implicit_range_before = _source_turn_pairs_for_regex(
        _IMPLICIT_RANGE_SOURCE_TURN_RE,
        query,
    )
    compact_range_after, compact_range_before = _source_turn_pairs_for_regex(
        _COMPACT_RANGE_SOURCE_TURN_RE,
        query,
    )
    same_dialogue_range_after, same_dialogue_range_before = (
        _same_dialogue_source_turn_pairs_for_regex(
            _SAME_DIALOGUE_RANGE_SOURCE_TURN_RE,
            query,
        )
    )
    scoped_between_after, scoped_between_before = _source_turn_pairs_with_scope_for_regex(
        _BETWEEN_SCOPED_SOURCE_TURN_RE,
        query,
    )
    within_turns, within_radius = _source_turns_and_radius_for_regex(
        _WITHIN_SOURCE_TURN_RE,
        query,
    )
    scoped_within_turns, scoped_within_radius = (
        _source_turns_and_radius_with_scope_for_regex(
            _WITHIN_SCOPED_SOURCE_TURN_RE,
            query,
        )
    )
    within_after_turns, within_after_radius = _source_turns_and_radius_for_regex(
        _WITHIN_AFTER_SOURCE_TURN_RE,
        query,
        default_radius=0,
    )
    scoped_within_after_turns, scoped_within_after_radius = (
        _source_turns_and_radius_with_scope_for_regex(
            _WITHIN_AFTER_SCOPED_SOURCE_TURN_RE,
            query,
            default_radius=0,
        )
    )
    next_after_turns, next_after_radius = _source_turns_and_radius_for_regex(
        _NEXT_AFTER_SOURCE_TURN_RE,
        query,
        default_radius=0,
    )
    scoped_next_after_turns, scoped_next_after_radius = (
        _source_turns_and_radius_with_scope_for_regex(
            _NEXT_AFTER_SCOPED_SOURCE_TURN_RE,
            query,
            default_radius=0,
        )
    )
    next_one_after_turns, next_one_after_radius = _source_turns_for_regex_with_radius(
        _NEXT_ONE_AFTER_SOURCE_TURN_RE,
        query,
        radius=1,
    )
    scoped_next_one_after_turns, scoped_next_one_after_radius = (
        _source_turns_with_scope_for_regex_with_radius(
            _NEXT_ONE_AFTER_SCOPED_SOURCE_TURN_RE,
            query,
            radius=1,
        )
    )
    within_before_turns, within_before_radius = _source_turns_and_radius_for_regex(
        _WITHIN_BEFORE_SOURCE_TURN_RE,
        query,
        default_radius=0,
    )
    scoped_within_before_turns, scoped_within_before_radius = (
        _source_turns_and_radius_with_scope_for_regex(
            _WITHIN_BEFORE_SCOPED_SOURCE_TURN_RE,
            query,
            default_radius=0,
        )
    )
    previous_before_turns, previous_before_radius = _source_turns_and_radius_for_regex(
        _PREVIOUS_BEFORE_SOURCE_TURN_RE,
        query,
        default_radius=0,
    )
    scoped_previous_before_turns, scoped_previous_before_radius = (
        _source_turns_and_radius_with_scope_for_regex(
            _PREVIOUS_BEFORE_SCOPED_SOURCE_TURN_RE,
            query,
            default_radius=0,
        )
    )
    previous_one_before_turns, previous_one_before_radius = (
        _source_turns_for_regex_with_radius(
            _PREVIOUS_ONE_BEFORE_SOURCE_TURN_RE,
            query,
            radius=1,
        )
    )
    scoped_previous_one_before_turns, scoped_previous_one_before_radius = (
        _source_turns_with_scope_for_regex_with_radius(
            _PREVIOUS_ONE_BEFORE_SCOPED_SOURCE_TURN_RE,
            query,
            radius=1,
        )
    )
    scoped_after_turns = _source_turns_with_scope_for_regex(
        _AFTER_SCOPED_SOURCE_TURN_RE,
        query,
    )
    scoped_before_turns = _source_turns_with_scope_for_regex(
        _BEFORE_SCOPED_SOURCE_TURN_RE,
        query,
    )
    scoped_near_turns = _source_turns_with_scope_for_regex(
        _NEAR_SCOPED_SOURCE_TURN_RE,
        query,
    )
    shared_source_identity = _shared_source_identity(
        query_scope_identity,
        (
            *between_after,
            *implicit_range_after,
            *compact_range_after,
            *same_dialogue_range_after,
            *scoped_between_after,
            *within_after_turns,
            *scoped_within_after_turns,
            *next_after_turns,
            *scoped_next_after_turns,
            *next_one_after_turns,
            *scoped_next_one_after_turns,
            *scoped_after_turns,
            *_source_turns_for_regex(_AFTER_SOURCE_TURN_RE, query),
            *between_before,
            *implicit_range_before,
            *compact_range_before,
            *same_dialogue_range_before,
            *scoped_between_before,
            *within_before_turns,
            *scoped_within_before_turns,
            *previous_before_turns,
            *scoped_previous_before_turns,
            *previous_one_before_turns,
            *scoped_previous_one_before_turns,
            *scoped_before_turns,
            *_source_turns_for_regex(_BEFORE_SOURCE_TURN_RE, query),
            *within_turns,
            *scoped_within_turns,
            *scoped_near_turns,
            *_source_turns_for_regex(_NEAR_SOURCE_TURN_RE, query),
        ),
    )
    return SourceTurnSequenceRequest(
        after_turns=_dedupe_source_turns(
            _source_turns_with_query_scope(
                (
                    *between_after,
                    *implicit_range_after,
                    *compact_range_after,
                    *same_dialogue_range_after,
                    *scoped_between_after,
                    *within_after_turns,
                    *scoped_within_after_turns,
                    *next_after_turns,
                    *scoped_next_after_turns,
                    *next_one_after_turns,
                    *scoped_next_one_after_turns,
                    *scoped_after_turns,
                    *_source_turns_for_regex(_AFTER_SOURCE_TURN_RE, query),
                ),
                shared_source_identity,
            )
        ),
        before_turns=_dedupe_source_turns(
            _source_turns_with_query_scope(
                (
                    *between_before,
                    *implicit_range_before,
                    *compact_range_before,
                    *same_dialogue_range_before,
                    *scoped_between_before,
                    *within_before_turns,
                    *scoped_within_before_turns,
                    *previous_before_turns,
                    *scoped_previous_before_turns,
                    *previous_one_before_turns,
                    *scoped_previous_one_before_turns,
                    *scoped_before_turns,
                    *_source_turns_for_regex(_BEFORE_SOURCE_TURN_RE, query),
                ),
                shared_source_identity,
            )
        ),
        near_turns=_dedupe_source_turns(
            _source_turns_with_query_scope(
                (
                    *within_turns,
                    *scoped_within_turns,
                    *scoped_near_turns,
                    *_source_turns_for_regex(_NEAR_SOURCE_TURN_RE, query),
                ),
                shared_source_identity,
            )
        ),
        after_turn_radius=max(
            within_after_radius,
            scoped_within_after_radius,
            next_after_radius,
            scoped_next_after_radius,
            next_one_after_radius,
            scoped_next_one_after_radius,
        ),
        before_turn_radius=max(
            within_before_radius,
            scoped_within_before_radius,
            previous_before_radius,
            scoped_previous_before_radius,
            previous_one_before_radius,
            scoped_previous_one_before_radius,
        ),
        near_turn_radius=max(within_radius, scoped_within_radius),
    )


def _shared_source_identity(
    query_scope_identity: str,
    source_turns: tuple[SourceTurnRef, ...],
) -> str:
    identities: list[str] = []
    if query_scope_identity:
        identities.append(query_scope_identity)
    for source_turn in source_turns:
        if source_turn.source_identity and source_turn.source_identity not in identities:
            identities.append(source_turn.source_identity)
    if not identities:
        return ""
    first_identity = identities[0]
    if not all(source_identity_matches(identity, first_identity) for identity in identities[1:]):
        return ""
    return first_identity


def _query_source_scope_identity(query: str) -> str:
    scope_identities: dict[str, None] = {}
    for match in _QUERY_NATURAL_DIALOGUE_SCOPE_RE.finditer(query):
        if scope_identity := source_scope_identity_from_label(
            _dialogue_scope_label(match.group("scope"))
        ):
            scope_identities.setdefault(scope_identity, None)
    for match in _QUERY_SOURCE_SCOPE_RE.finditer(query):
        if scope_identity := source_scope_identity_from_label(match.group("scope")):
            scope_identities.setdefault(scope_identity, None)
    for match in _QUERY_DIRECT_SOURCE_SCOPE_RE.finditer(query):
        if scope_identity := direct_source_scope_identity_from_label(
            match.group("scope")
        ):
            scope_identities.setdefault(scope_identity, None)
    if len(scope_identities) != 1:
        return ""
    return next(iter(scope_identities))


def _query_explicit_natural_source_scope_identity(query: str) -> str:
    scope_identities: dict[str, None] = {}
    for regex in (
        _QUERY_EXPLICIT_NATURAL_DIALOGUE_SCOPE_RE,
        _QUERY_BARE_EXPLICIT_NATURAL_DIALOGUE_SCOPE_RE,
    ):
        for match in regex.finditer(query):
            if scope_identity := source_scope_identity_from_label(
                _dialogue_scope_label(match.group("scope"))
            ):
                scope_identities.setdefault(scope_identity, None)
    if len(scope_identities) != 1:
        return ""
    return next(iter(scope_identities))


def _dialogue_scope_label(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"D\d{1,4}", text, re.IGNORECASE):
        return text
    if number := source_turn_label_number_value(text):
        return f"D{number}"
    return text


def _source_turns_with_query_scope(
    values: tuple[SourceTurnRef, ...],
    source_identity: str,
) -> tuple[SourceTurnRef, ...]:
    if not source_identity:
        return values
    return tuple(
        source_turn
        if source_turn.source_identity
        else SourceTurnRef(
            dialogue=source_turn.dialogue,
            turn=source_turn.turn,
            source_identity=source_identity,
        )
        for source_turn in values
    )


def source_turn_sequence_boost_signal(
    item: ContextItem,
    *,
    request: SourceTurnSequenceRequest,
) -> SourceTurnSequenceSignal:
    """Score item source turns against explicit query source-turn boundaries."""

    if request.empty:
        return SourceTurnSequenceSignal()
    item_turns = source_turn_refs_from_item(item)
    if not item_turns:
        return SourceTurnSequenceSignal()
    if request.after_turns and request.before_turns:
        return _source_turn_between_signal(
            item_turns=item_turns,
            after_boundaries=request.after_turns,
            before_boundaries=request.before_turns,
        )
    if request.near_turns:
        return _source_turn_proximity_signal(
            item_turns=item_turns,
            boundaries=request.near_turns,
            radius=request.near_turn_radius,
        )
    if request.after_turns and request.after_turn_radius:
        return _source_turn_direction_radius_signal(
            item_turns=item_turns,
            boundaries=request.after_turns,
            direction="after",
            radius=request.after_turn_radius,
        )
    if request.before_turns and request.before_turn_radius:
        return _source_turn_direction_radius_signal(
            item_turns=item_turns,
            boundaries=request.before_turns,
            direction="before",
            radius=request.before_turn_radius,
        )
    if request.after_turns:
        return _source_turn_direction_signal(
            item_turns=item_turns,
            boundaries=request.after_turns,
            direction="after",
        )
    return _source_turn_direction_signal(
        item_turns=item_turns,
        boundaries=request.before_turns,
        direction="before",
    )


def source_turn_refs_from_item(item: ContextItem) -> tuple[SourceTurnRef, ...]:
    values: list[str] = [item.item_id, item.text]
    source_ref_turns: list[SourceTurnRef] = []
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    metadata = safe_diagnostic_mapping(diagnostics.get("metadata"))
    for mapping in (diagnostics, provenance, metadata):
        values.extend(_string_values(mapping))
        source_ref_turns.extend(_identified_source_turns_from_mapping(mapping))
    for ref in item.source_refs:
        values.extend(
            str(value)
            for value in (
                ref.source_id,
                ref.chunk_id,
                ref.quote_preview,
            )
            if value
        )
        scope_identity = source_scope_identity_from_label(ref.source_id)
        for value in (ref.chunk_id, ref.quote_preview):
            if value:
                source_ref_turns.extend(
                    _source_turns_from_value(value, source_identity=scope_identity)
                )
    if text_identity := _single_source_ref_scope_identity(item):
        source_ref_turns.extend(
            _source_turns_from_value(item.text, source_identity=text_identity)
        )
    return _prefer_identified_source_turns(
        _dedupe_source_turns((*_source_turns_from_values(tuple(values)), *source_ref_turns))
    )


def _single_source_ref_scope_identity(item: ContextItem) -> str:
    identities: list[str] = []
    for ref in item.source_refs:
        identity = conversation_source_scope_identity_from_label(ref.source_id)
        if identity and not any(
            source_identity_matches(identity, existing) for existing in identities
        ):
            identities.append(identity)
    return identities[0] if len(identities) == 1 else ""


def _source_turn_proximity_signal(
    *,
    item_turns: tuple[SourceTurnRef, ...],
    boundaries: tuple[SourceTurnRef, ...],
    radius: int,
) -> SourceTurnSequenceSignal:
    radius = _bounded_turn_radius(radius)
    distances = tuple(
        abs(item_turn.turn - boundary.turn)
        for item_turn in item_turns
        for boundary in boundaries
        if _source_turn_scope_matches(item_turn, boundary)
    )
    if not distances:
        if _has_source_turn_identity_conflict(item_turns, boundaries):
            return _source_turn_identity_conflict_signal()
        return SourceTurnSequenceSignal()
    if min(distances) == 0:
        return SourceTurnSequenceSignal(
            boost=0.04,
            reason="query asks around source turn and item source turn matches boundary",
            code="near_source_turn_exact_match",
        )
    if min(distances) == 1:
        return SourceTurnSequenceSignal(
            boost=0.028,
            reason="query asks around source turn and item source turn is adjacent",
            code="near_source_turn_adjacent_match",
        )
    if min(distances) <= radius:
        return SourceTurnSequenceSignal(
            boost=0.022,
            reason="query asks around source turn and item source turn is within radius",
            code="near_source_turn_radius_match",
        )
    return SourceTurnSequenceSignal(
        boost=-0.014,
        reason="query asks around source turn and item source turn is distant",
        code="near_source_turn_distant_conflict",
    )


def _source_turn_direction_radius_signal(
    *,
    item_turns: tuple[SourceTurnRef, ...],
    boundaries: tuple[SourceTurnRef, ...],
    direction: str,
    radius: int,
) -> SourceTurnSequenceSignal:
    radius = _bounded_turn_radius(radius)
    deltas = tuple(
        _source_turn_direction_delta(
            item_turn=item_turn,
            boundary=boundary,
            direction=direction,
        )
        for item_turn in item_turns
        for boundary in boundaries
        if _source_turn_scope_matches(item_turn, boundary)
    )
    if not deltas:
        if _has_source_turn_identity_conflict(item_turns, boundaries):
            return _source_turn_identity_conflict_signal()
        return SourceTurnSequenceSignal()
    if any(0 < delta <= radius for delta in deltas):
        return SourceTurnSequenceSignal(
            boost=0.04,
            reason=(
                f"query asks within {radius} turns {direction} source turn "
                "and item source turn is inside radius"
            ),
            code=f"{direction}_source_turn_radius_match",
        )
    if any(delta <= 0 for delta in deltas):
        return SourceTurnSequenceSignal(
            boost=-0.026,
            reason=(
                f"query asks within {radius} turns {direction} source turn "
                "and item source turn is on the wrong side"
            ),
            code=f"{direction}_source_turn_radius_direction_conflict",
        )
    return SourceTurnSequenceSignal(
        boost=-0.014,
        reason=(
            f"query asks within {radius} turns {direction} source turn "
            "and item source turn is outside radius"
        ),
        code=f"{direction}_source_turn_radius_distance_conflict",
    )


def _source_turn_direction_delta(
    *,
    item_turn: SourceTurnRef,
    boundary: SourceTurnRef,
    direction: str,
) -> int:
    if direction == "after":
        return item_turn.turn - boundary.turn
    return boundary.turn - item_turn.turn


def _source_turn_between_signal(
    *,
    item_turns: tuple[SourceTurnRef, ...],
    after_boundaries: tuple[SourceTurnRef, ...],
    before_boundaries: tuple[SourceTurnRef, ...],
) -> SourceTurnSequenceSignal:
    windows = tuple(
        _source_turn_window(after_boundary, before_boundary)
        for after_boundary in after_boundaries
        for before_boundary in before_boundaries
        if _source_turn_scope_matches(after_boundary, before_boundary)
    )
    if not windows:
        return SourceTurnSequenceSignal()
    if any(
        lower_boundary < item_turn < upper_boundary
        for item_turn in item_turns
        for lower_boundary, upper_boundary in windows
        if _source_turn_scope_matches(item_turn, lower_boundary)
        and _source_turn_scope_matches(item_turn, upper_boundary)
    ):
        return SourceTurnSequenceSignal(
            boost=0.04,
            reason=(
                "query asks for source-turn window and item source turn is inside boundaries"
            ),
            code="source_turn_window_match",
        )
    if any(
        item_turn <= lower_boundary or item_turn >= upper_boundary
        for item_turn in item_turns
        for lower_boundary, upper_boundary in windows
        if _source_turn_scope_matches(item_turn, lower_boundary)
        and _source_turn_scope_matches(item_turn, upper_boundary)
    ):
        return SourceTurnSequenceSignal(
            boost=-0.026,
            reason=(
                "query asks for source-turn window and item source turn is outside boundaries"
            ),
            code="source_turn_window_conflict",
        )
    if _has_source_turn_identity_conflict(
        item_turns,
        (*after_boundaries, *before_boundaries),
    ):
        return _source_turn_identity_conflict_signal()
    return SourceTurnSequenceSignal()


def _source_turn_window(
    first: SourceTurnRef,
    second: SourceTurnRef,
) -> tuple[SourceTurnRef, SourceTurnRef]:
    return (first, second) if first <= second else (second, first)


def _source_turn_scope_matches(
    item_turn: SourceTurnRef,
    boundary: SourceTurnRef,
) -> bool:
    if item_turn.dialogue != boundary.dialogue:
        return False
    if boundary.source_identity and not item_turn.source_identity:
        return False
    if item_turn.source_identity and boundary.source_identity:
        return source_identity_matches(item_turn.source_identity, boundary.source_identity)
    return True


def _has_source_turn_identity_conflict(
    item_turns: tuple[SourceTurnRef, ...],
    boundaries: tuple[SourceTurnRef, ...],
) -> bool:
    return any(
        item_turn.dialogue == boundary.dialogue
        and item_turn.source_identity
        and boundary.source_identity
        and not source_identity_matches(
            item_turn.source_identity,
            boundary.source_identity,
        )
        for item_turn in item_turns
        for boundary in boundaries
    )


def _source_turn_identity_conflict_signal() -> SourceTurnSequenceSignal:
    return SourceTurnSequenceSignal(
        boost=-0.026,
        reason="query asks for source turn and item source identity differs",
        code="source_turn_identity_conflict",
    )


def _source_turn_direction_signal(
    *,
    item_turns: tuple[SourceTurnRef, ...],
    boundaries: tuple[SourceTurnRef, ...],
    direction: str,
) -> SourceTurnSequenceSignal:
    if direction == "after":
        if any(
            item_turn > boundary
            for item_turn in item_turns
            for boundary in boundaries
            if _source_turn_scope_matches(item_turn, boundary)
        ):
            return SourceTurnSequenceSignal(
                boost=0.04,
                reason="query asks for after source turn and item source turn follows boundary",
                code="after_source_turn_match",
            )
        if any(
            item_turn <= boundary
            for item_turn in item_turns
            for boundary in boundaries
            if _source_turn_scope_matches(item_turn, boundary)
        ):
            return SourceTurnSequenceSignal(
                boost=-0.026,
                reason="query asks for after source turn and item source turn precedes boundary",
                code="after_source_turn_conflict",
            )
    if any(
        item_turn < boundary
        for item_turn in item_turns
        for boundary in boundaries
        if _source_turn_scope_matches(item_turn, boundary)
    ):
        return SourceTurnSequenceSignal(
            boost=0.04,
            reason="query asks for before source turn and item source turn precedes boundary",
            code="before_source_turn_match",
        )
    if any(
        item_turn >= boundary
        for item_turn in item_turns
        for boundary in boundaries
        if _source_turn_scope_matches(item_turn, boundary)
    ):
        return SourceTurnSequenceSignal(
            boost=-0.026,
            reason="query asks for before source turn and item source turn follows boundary",
            code="before_source_turn_conflict",
        )
    if _has_source_turn_identity_conflict(item_turns, boundaries):
        return _source_turn_identity_conflict_signal()
    return SourceTurnSequenceSignal()


def _source_turns_for_regex(regex: re.Pattern[str], text: str) -> tuple[SourceTurnRef, ...]:
    seen: dict[SourceTurnRef, None] = {}
    for match in regex.finditer(text):
        if source_turn := _source_turn_from_label(match.group("ref")):
            seen.setdefault(source_turn, None)
    return tuple(seen)


def _source_turns_with_scope_for_regex(
    regex: re.Pattern[str],
    text: str,
) -> tuple[SourceTurnRef, ...]:
    turns: list[SourceTurnRef] = []
    for match in regex.finditer(text):
        source_turn = _source_turn_from_label(match.group("ref"))
        scope_identity = source_scope_identity_from_label(match.group("scope"))
        if source_turn and scope_identity:
            turns.append(
                SourceTurnRef(
                    dialogue=source_turn.dialogue,
                    turn=source_turn.turn,
                    source_identity=scope_identity,
                )
            )
    return _dedupe_source_turns(turns)


def _source_turn_pairs_for_regex(
    regex: re.Pattern[str],
    text: str,
) -> tuple[tuple[SourceTurnRef, ...], tuple[SourceTurnRef, ...]]:
    after_turns: list[SourceTurnRef] = []
    before_turns: list[SourceTurnRef] = []
    for match in regex.finditer(text):
        after_turn = _source_turn_from_label(match.group("after_ref"))
        before_turn = _source_turn_from_label(match.group("before_ref"))
        if after_turn and before_turn:
            after_turn, before_turn = _source_turn_pair_with_shared_identity(
                after_turn,
                before_turn,
            )
            after_turns.append(after_turn)
            before_turns.append(before_turn)
    return _dedupe_source_turns(after_turns), _dedupe_source_turns(before_turns)


def _same_dialogue_source_turn_pairs_for_regex(
    regex: re.Pattern[str],
    text: str,
) -> tuple[tuple[SourceTurnRef, ...], tuple[SourceTurnRef, ...]]:
    after_turns: list[SourceTurnRef] = []
    before_turns: list[SourceTurnRef] = []
    for match in regex.finditer(text):
        dialogue = int(match.group("dialogue"))
        after_turns.append(
            SourceTurnRef(dialogue=dialogue, turn=int(match.group("after_turn")))
        )
        before_turns.append(
            SourceTurnRef(dialogue=dialogue, turn=int(match.group("before_turn")))
        )
    return _dedupe_source_turns(after_turns), _dedupe_source_turns(before_turns)


def _source_turn_pairs_with_scope_for_regex(
    regex: re.Pattern[str],
    text: str,
) -> tuple[tuple[SourceTurnRef, ...], tuple[SourceTurnRef, ...]]:
    after_turns: list[SourceTurnRef] = []
    before_turns: list[SourceTurnRef] = []
    for match in regex.finditer(text):
        scope_identity = source_scope_identity_from_label(match.group("scope"))
        after_turn = _source_turn_with_identity(match.group("after_ref"), scope_identity)
        before_turn = _source_turn_with_identity(match.group("before_ref"), scope_identity)
        if after_turn and before_turn:
            after_turns.append(after_turn)
            before_turns.append(before_turn)
    return _dedupe_source_turns(after_turns), _dedupe_source_turns(before_turns)


def _source_turn_with_identity(value: str, source_identity: str) -> SourceTurnRef | None:
    source_turn = _source_turn_from_label(value)
    if source_turn is None:
        return None
    return SourceTurnRef(
        dialogue=source_turn.dialogue,
        turn=source_turn.turn,
        source_identity=source_turn.source_identity or source_identity,
    )


def _source_turn_pair_with_shared_identity(
    first: SourceTurnRef,
    second: SourceTurnRef,
) -> tuple[SourceTurnRef, SourceTurnRef]:
    if first.source_identity and not second.source_identity:
        return first, SourceTurnRef(
            dialogue=second.dialogue,
            turn=second.turn,
            source_identity=first.source_identity,
        )
    if second.source_identity and not first.source_identity:
        return SourceTurnRef(
            dialogue=first.dialogue,
            turn=first.turn,
            source_identity=second.source_identity,
        ), second
    return first, second


def _source_turns_and_radius_for_regex(
    regex: re.Pattern[str],
    text: str,
    *,
    default_radius: int = 1,
) -> tuple[tuple[SourceTurnRef, ...], int]:
    turns: list[SourceTurnRef] = []
    radius = default_radius
    for match in regex.finditer(text):
        if source_turn := _source_turn_from_label(match.group("ref")):
            turns.append(source_turn)
            radius = max(radius, _turn_radius_from_token(match.group("radius")))
    if radius == 0:
        return _dedupe_source_turns(turns), 0
    return _dedupe_source_turns(turns), _bounded_turn_radius(radius)


def _source_turns_and_radius_with_scope_for_regex(
    regex: re.Pattern[str],
    text: str,
    *,
    default_radius: int = 1,
) -> tuple[tuple[SourceTurnRef, ...], int]:
    turns: list[SourceTurnRef] = []
    radius = default_radius
    for match in regex.finditer(text):
        scope_identity = source_scope_identity_from_label(match.group("scope"))
        if source_turn := _source_turn_with_identity(match.group("ref"), scope_identity):
            turns.append(source_turn)
            radius = max(radius, _turn_radius_from_token(match.group("radius")))
    if radius == 0:
        return _dedupe_source_turns(turns), 0
    return _dedupe_source_turns(turns), _bounded_turn_radius(radius)


def _source_turns_for_regex_with_radius(
    regex: re.Pattern[str],
    text: str,
    *,
    radius: int,
) -> tuple[tuple[SourceTurnRef, ...], int]:
    turns = _source_turns_for_regex(regex, text)
    if not turns:
        return (), 0
    return turns, _bounded_turn_radius(radius)


def _source_turns_with_scope_for_regex_with_radius(
    regex: re.Pattern[str],
    text: str,
    *,
    radius: int,
) -> tuple[tuple[SourceTurnRef, ...], int]:
    turns = _source_turns_with_scope_for_regex(regex, text)
    if not turns:
        return (), 0
    return turns, _bounded_turn_radius(radius)


def _turn_radius_from_token(value: str) -> int:
    text = value.strip().casefold()
    word_values = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "couple": 2,
        "a couple": 2,
        "couple of": 2,
        "a couple of": 2,
    }
    if text in word_values:
        return word_values[text]
    if text.isdigit():
        return int(text)
    return 1


def _bounded_turn_radius(value: int) -> int:
    return max(1, min(value, 5))


def _dedupe_source_turns(
    values: tuple[SourceTurnRef, ...] | list[SourceTurnRef],
) -> tuple[SourceTurnRef, ...]:
    return _prefer_identified_source_turns(tuple(dict.fromkeys(values)))


def _source_turns_from_values(values: tuple[str, ...]) -> tuple[SourceTurnRef, ...]:
    seen: dict[SourceTurnRef, None] = {}
    for value in values:
        for source_turn in _source_turns_from_value(value):
            seen.setdefault(source_turn, None)
    return _prefer_identified_source_turns(tuple(seen))


def _source_turns_from_value(
    value: str,
    *,
    source_identity: str = "",
) -> tuple[SourceTurnRef, ...]:
    turns: list[SourceTurnRef] = []
    value_identity = source_identity_from_label(value)
    canonical_value = canonicalize_natural_source_turn_labels(value)
    for match in _SOURCE_TURN_RE.finditer(canonical_value):
        turns.append(
            SourceTurnRef(
                dialogue=int(match.group("dialogue")),
                turn=int(match.group("turn")),
                source_identity=value_identity or source_identity,
            )
        )
    return tuple(turns)


def _identified_source_turns_from_mapping(
    mapping: Mapping[str, object],
) -> tuple[SourceTurnRef, ...]:
    turns: list[SourceTurnRef] = []
    for scope_identity in _source_scope_identities_from_mapping(mapping):
        turns.extend(
            source_turn
            for value in _string_values(mapping)
            for source_turn in _source_turns_from_value(
                value,
                source_identity=scope_identity,
            )
        )
    for value in mapping.values():
        turns.extend(_identified_source_turns_from_diagnostic_value(value))
    return _prefer_identified_source_turns(_dedupe_source_turns(turns))


def _source_scope_identities_from_mapping(mapping: Mapping[str, object]) -> tuple[str, ...]:
    identities: list[str] = []
    primary_identity = source_scope_identity_from_mapping(mapping)
    if primary_identity:
        identities.append(primary_identity)
    if primary_identity and _source_identity_has_session_scope(primary_identity):
        return tuple(identities)
    for key in (
        "conversation_id",
        "conversation_index",
        "conversation_number",
        "conversation_order",
        "conv_id",
        "conv_index",
        "conv_number",
        "conv_order",
        "locomo_session_index",
        "locomo_session_key",
        "locomo_session_number",
        "source_conversation_id",
        "source_conversation_index",
        "source_conversation_number",
        "source_conv_id",
        "source_conv_index",
        "source_conv_number",
        "source_session_id",
        "source_session_index",
        "source_session_key",
        "source_session_number",
        "session_index",
        "session_key",
        "session_number",
        "session_order",
    ):
        value = mapping.get(key)
        session_identity = explicit_ordinal_session_scope_identity_from_value(
            value
        ) or explicit_session_scope_identity_from_value(value)
        if session_identity and not any(
            source_identity_matches(session_identity, existing) for existing in identities
        ):
            identities.append(session_identity)
    value = mapping.get("session_id")
    if isinstance(value, str):
        session_identity = conversation_source_scope_identity_from_label(value)
        if session_identity and not any(
            source_identity_matches(session_identity, existing) for existing in identities
        ):
            identities.append(session_identity)
    if _has_opaque_session_id(mapping):
        return tuple(identities)
    for key in (
        "dia_id",
        "dialogue_id",
        "dialogue_index",
        "source_dia_id",
        "source_dialogue_id",
        "source_dialogue_index",
    ):
        value = mapping.get(key)
        session_identity = explicit_ordinal_session_scope_identity_from_value(value)
        if session_identity and not any(
            source_identity_matches(session_identity, existing) for existing in identities
        ):
            identities.append(session_identity)
    return tuple(identities)


def _has_opaque_session_id(mapping: Mapping[str, object]) -> bool:
    value = mapping.get("session_id")
    return isinstance(value, str) and bool(value.strip()) and not (
        conversation_source_scope_identity_from_label(value)
        or explicit_ordinal_session_scope_identity_from_value(value)
    )


def _source_identity_has_session_scope(value: str) -> bool:
    return bool(re.search(r"(?:^|[:_-])session[-_:]?\d", value, re.IGNORECASE))


def _identified_source_turns_from_diagnostic_value(
    value: object,
) -> tuple[SourceTurnRef, ...]:
    if isinstance(value, Mapping):
        return _identified_source_turns_from_mapping(value)
    if isinstance(value, (list, tuple)):
        return _prefer_identified_source_turns(
            _dedupe_source_turns(
                tuple(
                    source_turn
                    for nested_value in value
                    for source_turn in _identified_source_turns_from_diagnostic_value(
                        nested_value
                    )
                )
            )
        )
    return ()


def _source_turn_from_label(value: str) -> SourceTurnRef | None:
    match = _SOURCE_TURN_RE.search(value.strip())
    if match is None:
        return None
    return SourceTurnRef(
        dialogue=int(match.group("dialogue")),
        turn=int(match.group("turn")),
        source_identity=source_identity_from_label(value),
    )


def _prefer_identified_source_turns(
    values: tuple[SourceTurnRef, ...],
) -> tuple[SourceTurnRef, ...]:
    identified_positions = {
        (value.dialogue, value.turn) for value in values if value.source_identity
    }
    return tuple(
        value
        for value in values
        if value.source_identity or (value.dialogue, value.turn) not in identified_positions
    )


def _string_values(mapping: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    if structured_label := _structured_source_turn_label(mapping):
        values.append(structured_label)
    for value in mapping.values():
        values.extend(_strings_from_diagnostic_value(value))
    return tuple(values)


def _strings_from_diagnostic_value(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        structured_label = _structured_source_turn_label(value)
        nested_values = tuple(
            string_value
            for nested_value in value.values()
            for string_value in _strings_from_diagnostic_value(nested_value)
        )
        if structured_label:
            return (structured_label, *nested_values)
        return nested_values
    if isinstance(value, (list, tuple)):
        return tuple(
            string_value
            for nested_value in value
            for string_value in _strings_from_diagnostic_value(nested_value)
        )
    return ()


def _structured_source_turn_label(value: Mapping[str, object]) -> str:
    dia_id = (
        value.get("dia_id")
        or value.get("source_dia_id")
        or value.get("dialogue_turn_id")
    )
    source_scope = (
        value.get("source_id")
        or value.get("source_external_id")
        or value.get("source_ref")
        or value.get("source_ref_id")
        or value.get("source_identity")
        or value.get("source_identity_ref")
        or value.get("source_key")
        or value.get("locomo_session_index")
        or value.get("locomo_session_key")
        or value.get("locomo_session_number")
        or value.get("source_session_id")
        or value.get("source_session_index")
        or value.get("source_session_key")
        or value.get("source_session_number")
        or value.get("session_index")
        or value.get("session_key")
        or value.get("session_number")
        or value.get("session_order")
    )
    dialogue = _first_dialogue_int_value(
        value.get("dialogue"),
        value.get("dialogue_id"),
        value.get("dialogue_index"),
        value.get("source_dialogue"),
        value.get("source_dialogue_id"),
        value.get("source_dialogue_index"),
        value.get("locomo_session_index"),
        value.get("locomo_session_key"),
        value.get("locomo_session_number"),
        value.get("source_session_id"),
        value.get("source_session_index"),
        value.get("source_session_key"),
        value.get("source_session_number"),
        value.get("session"),
        value.get("session_id"),
        value.get("session_key"),
        value.get("session_index"),
        value.get("session_number"),
        value.get("session_order"),
        dia_id,
        source_scope,
        value.get("conversation"),
        value.get("conversation_id"),
        value.get("conversation_index"),
        value.get("conv"),
        value.get("conv_id"),
        value.get("conv_index"),
        value.get("source_conversation"),
        value.get("source_conversation_id"),
        value.get("source_conversation_index"),
        value.get("source_conv"),
        value.get("source_conv_id"),
        value.get("source_conv_index"),
    )
    turn = _first_turn_int_value(
        value.get("turn"),
        value.get("turn_id"),
        value.get("turn_index"),
        value.get("source_turn"),
        value.get("source_turn_id"),
        value.get("source_turn_index"),
        dia_id,
        source_scope,
    )
    if not dialogue or not turn:
        return ""
    return f"D{dialogue}:{turn}"


def _first_dialogue_int_value(*values: object) -> int:
    for value in values:
        if parsed := _dialogue_int_value(value):
            return parsed
    return 0


def _first_turn_int_value(*values: object) -> int:
    for value in values:
        if parsed := _turn_int_value(value):
            return parsed
    return 0


def _dialogue_int_value(value: object) -> int:
    if direct_value := _positive_int_value(value):
        return direct_value
    text = str(value or "").strip()
    session_match = re.search(
        rf"\bsession[_:\-\s#]*{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        rf"(?P<value>{SOURCE_TURN_LABEL_NUMBER_PATTERN})\b",
        text,
        re.IGNORECASE,
    )
    if session_match is not None:
        return source_turn_label_number_value(session_match.group("value"))
    match = re.search(
        r"\b(?:d|dia|dialog|dialogue|conv|conversation|session)"
        rf"[_:\-\s#]*{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        rf"(?P<value>{SOURCE_TURN_LABEL_NUMBER_PATTERN})\b",
        text,
        re.IGNORECASE,
    )
    return source_turn_label_number_value(match.group("value")) if match else 0


def _turn_int_value(value: object) -> int:
    if direct_value := _positive_int_value(value):
        return direct_value
    text = str(value or "").strip()
    match = re.search(
        rf"\b(?:turn|t)[_:\-\s#]*{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        rf"(?P<value>{SOURCE_TURN_LABEL_NUMBER_PATTERN})\b|"
        r"\bD\d{1,4}[:\-](?P<dia_turn>\d{1,4})\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return 0
    return source_turn_label_number_value(match.group("value") or match.group("dia_turn"))


def _positive_int_value(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else 0
    text = str(value).strip()
    if match := re.fullmatch(
        rf"(?:session|conversation|conv|dialogue|dialog|dia)[-_ ]"
        rf"{_OPTIONAL_NUMBER_LABEL_PATTERN}"
        rf"(?P<number>{SOURCE_TURN_LABEL_NUMBER_PATTERN})",
        text,
        re.IGNORECASE,
    ):
        return source_turn_label_number_value(match.group("number"))
    if match := re.fullmatch(r"D(?P<number>\d{1,4})", text, re.IGNORECASE):
        return int(match.group("number"))
    return source_turn_label_number_value(text)
