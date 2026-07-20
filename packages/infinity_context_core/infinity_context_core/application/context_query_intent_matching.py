"""Query anchor intent matching and conflict policies."""

from __future__ import annotations

import re

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key_for_kind,
    extract_observed_anchors,
)
from infinity_context_core.application.context_occupational_role_identity import (
    is_non_person_identity_label,
)
from infinity_context_core.application.context_query_intent_common import (
    _bounded_unique,
    _metadata_text,
    _normalized,
)
from infinity_context_core.application.context_query_intent_contracts import (
    QueryAnchorIntent,
    QueryAnchorMatch,
)
from infinity_context_core.application.context_query_intent_extraction import (
    _PERSON_HINT_STOP_WORDS,
    _PROJECT_HINT_STOP_WORDS,
)
from infinity_context_core.application.context_query_intent_keys import (
    _anchor_identity_keys,
    _compatible_identity_matches,
    _event_type_identity_keys,
    _event_type_keys_conflict,
    _identity_term_variants,
    _observed_anchor_identity_keys,
    _temporal_identity_keys,
    _temporal_keys_conflict,
)
from infinity_context_core.domain.entities import MemoryAnchor, MemoryAnchorKind

_RELOCATION_ORIGIN_EVIDENCE_RE = re.compile(
    r"\b(?:move|moved|moving|relocate|relocated)\s+from\b|"
    r"\b(?:home country|country of origin|native country|previous country|former country|"
    r"birth country|roots|origin|origins)\b|"
    r"\b(?:родн(?:ая|ой|ую)\s+стран|страна\s+происхождения|корни|переехал[аи]?\s+из)\b",
    re.IGNORECASE,
)


def match_query_anchor_intent(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> QueryAnchorMatch | None:
    if intent.empty:
        return None
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _match_event_anchor(intent, anchor)
    anchor_keys = _anchor_identity_keys(anchor)
    query_keys = intent.keys_for_kind(anchor.kind)
    shared = _compatible_identity_matches(anchor_keys, query_keys)
    if not shared:
        return None
    return QueryAnchorMatch(
        score_boost=0.055,
        reasons=(f"query_{anchor.kind.value}_identity_match",),
        matched_keys=tuple(shared[:4]),
    )


def match_query_anchor_intent_to_text(
    intent: QueryAnchorIntent,
    text: str,
) -> QueryAnchorMatch | None:
    if intent.empty:
        return None
    anchors = _text_intent_observed_anchors(text)
    if not anchors:
        return None
    if _observed_anchor_conflicts_intent(intent, anchors, text=text):
        return None
    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    for anchor in anchors:
        if anchor.kind == MemoryAnchorKind.EVENT:
            match = _match_observed_event_anchor(intent, anchor)
            if match is None:
                continue
            reasons.extend(match.reasons)
            matched_keys.extend(match.matched_keys)
            score_boost += match.score_boost
            continue
        query_keys = intent.keys_for_kind(anchor.kind)
        if not query_keys:
            continue
        shared = _compatible_identity_matches(
            _observed_anchor_identity_keys(anchor),
            query_keys,
        )
        if not shared:
            continue
        reasons.append(f"query_{anchor.kind.value}_identity_match")
        matched_keys.extend(shared[:4])
        score_boost += 0.025
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.055, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
    )


def query_anchor_intent_conflicts(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> bool:
    if intent.empty:
        return False
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _event_anchor_conflicts_intent(intent, anchor)
    query_keys = intent.keys_for_kind(anchor.kind)
    if not query_keys:
        return False
    return not _compatible_identity_matches(_anchor_identity_keys(anchor), query_keys)


def query_anchor_intent_text_conflicts(
    intent: QueryAnchorIntent,
    text: str,
) -> bool:
    """Return True when observed text anchors contradict explicit query anchors."""

    if intent.empty:
        return False
    anchors = _text_intent_observed_anchors(text)
    return bool(anchors and _observed_anchor_conflicts_intent(intent, anchors, text=text))


def _text_intent_observed_anchors(text: str) -> tuple[ObservedAnchor, ...]:
    return tuple(
        anchor
        for anchor in extract_observed_anchors(text)
        if not _observed_anchor_is_text_intent_noise(anchor, text=text)
    )


def _observed_anchor_is_text_intent_noise(anchor: ObservedAnchor, *, text: str) -> bool:
    canonical_key = _metadata_text(anchor.metadata.get("canonical_key"))
    if not canonical_key:
        canonical_key = canonical_anchor_key_for_kind(anchor.kind, anchor.label)
    normalized_label = _normalized(anchor.label)
    if anchor.kind == MemoryAnchorKind.PERSON:
        return (
            canonical_key in _PERSON_HINT_STOP_WORDS
            or normalized_label in _PERSON_HINT_STOP_WORDS
            or is_non_person_identity_label(label=anchor.label, text=text)
        )
    if anchor.kind == MemoryAnchorKind.PROJECT:
        return (
            canonical_key in _PROJECT_HINT_STOP_WORDS
            or normalized_label in _PROJECT_HINT_STOP_WORDS
        )
    return False


def _match_event_anchor(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> QueryAnchorMatch | None:
    event_keys = _anchor_identity_keys(anchor)
    exact_event_keys = intent.keys_for_kind(MemoryAnchorKind.EVENT).intersection(event_keys)
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()

    anchor_person = _metadata_text(anchor.metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    anchor_person_keys = _identity_term_variants(anchor_person)
    anchor_project_keys = _identity_term_variants(anchor_project)
    anchor_temporal_keys = _temporal_identity_keys(anchor.metadata)
    anchor_event_type_keys = _event_type_identity_keys(anchor.metadata)

    if person_keys and not anchor_person_keys.intersection(person_keys):
        return None
    if project_keys and not _compatible_identity_matches(anchor_project_keys, project_keys):
        return None
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return None
    if _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    ):
        return None

    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    if exact_event_keys:
        reasons.append("query_event_identity_match")
        matched_keys.extend(sorted(exact_event_keys)[:4])
        score_boost += 0.04
    person_matches = sorted(anchor_person_keys.intersection(person_keys))
    if person_matches:
        reasons.append("query_event_participant_match")
        matched_keys.extend(person_matches[:2])
        score_boost += 0.035
    project_matches = _compatible_identity_matches(anchor_project_keys, project_keys)
    if project_matches:
        reasons.append("query_event_project_match")
        matched_keys.extend(project_matches[:2])
        score_boost += 0.035
    shared_event_type = sorted(anchor_event_type_keys.intersection(event_type_keys))
    if shared_event_type:
        reasons.append("query_event_type_match")
        matched_keys.extend(shared_event_type[:3])
        score_boost += 0.025
    shared_temporal = sorted(anchor_temporal_keys.intersection(temporal_keys))
    if shared_temporal:
        reasons.append("query_event_temporal_match")
        matched_keys.extend(shared_temporal[:3])
        score_boost += 0.02
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.09, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
    )


def _match_observed_event_anchor(
    intent: QueryAnchorIntent,
    anchor: ObservedAnchor,
) -> QueryAnchorMatch | None:
    metadata = anchor.metadata
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()

    anchor_person = _metadata_text(metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        metadata.get("event_project_canonical_key") or metadata.get("project_canonical_key")
    )
    anchor_person_keys = _identity_term_variants(anchor_person)
    anchor_project_keys = _identity_term_variants(anchor_project)
    anchor_temporal_keys = _temporal_identity_keys(metadata)
    anchor_event_type_keys = _event_type_identity_keys(metadata)

    if person_keys and anchor_person_keys and not anchor_person_keys.intersection(person_keys):
        return None
    if (
        project_keys
        and anchor_project_keys
        and not _compatible_identity_matches(anchor_project_keys, project_keys)
    ):
        return None
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return None
    if _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    ):
        return None

    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    person_matches = sorted(anchor_person_keys.intersection(person_keys))
    if person_matches:
        reasons.append("query_event_participant_match")
        matched_keys.extend(person_matches[:2])
        score_boost += 0.02
    project_matches = _compatible_identity_matches(anchor_project_keys, project_keys)
    if project_matches:
        reasons.append("query_event_project_match")
        matched_keys.extend(project_matches[:2])
        score_boost += 0.02
    shared_event_type = sorted(anchor_event_type_keys.intersection(event_type_keys))
    if shared_event_type:
        reasons.append("query_event_type_match")
        matched_keys.extend(shared_event_type[:3])
        score_boost += 0.015
    shared_temporal = sorted(anchor_temporal_keys.intersection(temporal_keys))
    if shared_temporal:
        reasons.append("query_event_temporal_match")
        matched_keys.extend(shared_temporal[:3])
        score_boost += 0.015
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.045, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
    )


def _observed_anchor_conflicts_intent(
    intent: QueryAnchorIntent,
    anchors: tuple[ObservedAnchor, ...],
    *,
    text: str,
) -> bool:
    for kind in (
        MemoryAnchorKind.PERSON,
        MemoryAnchorKind.PROJECT,
        MemoryAnchorKind.ORGANIZATION,
    ):
        query_keys = intent.keys_for_kind(kind)
        if not query_keys:
            continue
        observed_keys: set[str] = set()
        for anchor in anchors:
            if anchor.kind == kind:
                observed_keys.update(_observed_anchor_identity_keys(anchor))
        if observed_keys and not _compatible_identity_matches(observed_keys, query_keys):
            return True
    event_anchors = tuple(anchor for anchor in anchors if anchor.kind == MemoryAnchorKind.EVENT)
    if event_anchors:
        observed_temporal_keys: set[str] = set()
        observed_event_type_keys: set[str] = set()
        for anchor in event_anchors:
            observed_temporal_keys.update(_temporal_identity_keys(anchor.metadata))
            observed_event_type_keys.update(_event_type_identity_keys(anchor.metadata))
        if (
            not _is_broad_activity_event_query(intent)
            and _event_type_keys_conflict(
                query_event_type_keys=intent.event_type_keys(),
                anchor_event_type_keys=frozenset(observed_event_type_keys),
            )
            and not _is_relocation_origin_evidence_text(intent, text)
        ):
            return True
        if _temporal_keys_conflict(
            query_temporal_keys=intent.temporal_keys(),
            anchor_temporal_keys=frozenset(observed_temporal_keys),
        ) and not _is_relocation_origin_evidence_text(intent, text):
            return True
    return False


def _is_relocation_origin_evidence_text(intent: QueryAnchorIntent, text: str) -> bool:
    """Origin snippets often answer relocation questions without repeating the date."""

    if "group:relocation" not in intent.event_type_keys():
        return False
    return bool(_RELOCATION_ORIGIN_EVIDENCE_RE.search(str(text)[:2000]))


def _is_broad_activity_event_query(intent: QueryAnchorIntent) -> bool:
    """Activity list questions often describe events with indirect verbs in evidence text."""

    return "group:activity" in intent.event_type_keys()


def _event_anchor_conflicts_intent(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> bool:
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()
    anchor_person = _metadata_text(anchor.metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    anchor_temporal_keys = _temporal_identity_keys(anchor.metadata)
    anchor_event_type_keys = _event_type_identity_keys(anchor.metadata)
    if person_keys and not _identity_term_variants(anchor_person).intersection(person_keys):
        return True
    if project_keys and not _compatible_identity_matches(
        _identity_term_variants(anchor_project),
        project_keys,
    ):
        return True
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return True
    return _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    )
