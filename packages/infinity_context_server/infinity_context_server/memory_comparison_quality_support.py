"""Support-role predicates for memory-comparison quality diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def needs_temporal_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        {"temporal_support", "temporal_sequence"}.intersection(evidence_need)
        or "temporal" in relation_categories
    )


def needs_contrast_evidence(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool("contrast" in evidence_need or "contrast" in relation_categories)


def needs_causal_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    return bool(
        "causal_support" in evidence_need
        or "causal_support" in roles
        or "causal" in relation_categories
    )


def needs_location_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "location_support" in evidence_need
        or "location_transition" in relation_categories
    )


def needs_inference_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    return bool("inference_support" in evidence_need or "inference_support" in roles)


def needs_preference_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "preference" in evidence_need
        or "preference_support" in roles
        or "preference" in relation_categories
    )


def needs_emotion_response_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "emotion_response" in evidence_need
        or "emotion_response_support" in roles
        or "emotion_response" in relation_categories
    )


def needs_event_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    event_categories = {"participation_event", "registration_event"}
    return bool(
        event_categories & set(evidence_need)
        or "event_support" in roles
        or event_categories & set(relation_categories)
    )


def needs_exchange_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "exchange" in evidence_need
        or "exchange_support" in roles
        or "exchange" in relation_categories
    )


def needs_communication_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "communication" in evidence_need
        or "communication_support" in roles
        or "communication" in relation_categories
    )


def needs_symbolic_meaning_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "symbolic_meaning" in evidence_need
        or "symbolic_meaning_support" in roles
        or "symbolic_meaning" in relation_categories
    )


def needs_visual_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = (
        _str_tuple(query_profile.get("evidence_need"))
        or _str_tuple(intent.get("evidence_need"))
    )
    roles = (
        _str_tuple(query_profile.get("bundle_evidence_roles"))
        or _str_tuple(intent.get("bundle_evidence_roles"))
    )
    relation_categories = _relation_categories(query_profile, intent)
    visual_terms = _str_tuple(query_profile.get("visual_terms"))
    return bool(
        "visual_evidence" in evidence_need
        or "visual_support" in roles
        or "visual" in relation_categories
        or visual_terms
    )


def bundle_roles(bundle: Mapping[str, object]) -> set[str]:
    roles = {
        str(item.get("role") or "").strip()
        for item in _bundle_items(bundle)
        if str(item.get("role") or "").strip()
    }
    planner = _mapping(bundle.get("bundle_planner"))
    role_counts = _mapping(planner.get("role_counts"))
    roles.update(str(role).strip() for role in role_counts if str(role).strip())
    return roles


def bundle_has_planner_reason(bundle: Mapping[str, object], reason: str) -> bool:
    return any(
        reason in _str_tuple(item.get("planner_reason_codes"))
        for item in _bundle_items(bundle)
    )


def bundle_has_temporal_support(bundle: Mapping[str, object]) -> bool:
    return any(_bundle_item_has_temporal_support(item) for item in _bundle_items(bundle))


def _bundle_item_has_temporal_support(item: Mapping[str, object]) -> bool:
    time_kind = str(item.get("time_intent_kind") or "").strip()
    reasons = _str_tuple(item.get("planner_reason_codes"))
    has_temporal = bool(
        item.get("has_temporal_surface") or "temporal_surface" in reasons
    )
    has_sequence = bool(
        item.get("has_sequence_surface") or "sequence_surface" in reasons
    )
    has_duration = bool(
        item.get("has_duration_surface") or "duration_surface" in reasons
    )
    has_relative = bool(
        item.get("has_relative_time_surface") or "relative_time_surface" in reasons
    )
    has_explicit = bool(
        item.get("has_explicit_time_surface") or "explicit_time_surface" in reasons
    )
    has_temporal_sequence = bool(
        item.get("has_temporal_sequence_surface")
        or "temporal_sequence_surface" in reasons
    )
    has_currentness = bool(
        item.get("currentness_surface") or "currentness_surface" in reasons
    )
    if time_kind == "duration":
        return has_duration
    if time_kind == "temporal_sequence":
        return has_temporal_sequence or has_sequence
    if time_kind == "explicit_time":
        return has_explicit or has_temporal
    if time_kind == "relative_time":
        return has_relative or has_currentness or has_temporal
    return bool(
        has_temporal
        or has_sequence
        or has_duration
        or has_relative
        or has_explicit
        or has_temporal_sequence
        or has_currentness
    )


def bundle_has_contrast_support(bundle: Mapping[str, object]) -> bool:
    return any(_bundle_item_has_contrast_support(item) for item in _bundle_items(bundle))


def _bundle_item_has_contrast_support(item: Mapping[str, object]) -> bool:
    reasons = _str_tuple(item.get("planner_reason_codes"))
    if item.get("contrast_surface") or "contrast_surface" in reasons:
        return True
    has_currentness = bool(
        item.get("currentness_surface") or "currentness_surface" in reasons
    )
    has_change_or_negation = bool(
        item.get("stale_surface")
        or item.get("negation_surface")
        or "stale_surface" in reasons
        or "negation_surface" in reasons
    )
    return has_currentness and has_change_or_negation


def bundle_has_causal_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "causal" in _str_tuple(item.get("relation_category_hits"))
                or "causal_relation_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or "causal_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_location_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "location_transition"
                in _str_tuple(item.get("relation_category_hits"))
                or "location_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_preference_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                item.get("has_preference_evidence") is True
                or "preference" in _str_tuple(item.get("relation_category_hits"))
                or "preference_evidence"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_emotion_response_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "emotion_response"
                in _str_tuple(item.get("relation_category_hits"))
                or "emotion_response_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_event_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                {"registration_event", "participation_event"}
                & set(_str_tuple(item.get("relation_category_hits")))
                or "event_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_communication_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            "communication" in _str_tuple(item.get("relation_category_hits"))
            and _passes_person_grounding(
                item,
                require_grounding=require_grounding,
                speaker_grounding=require_grounding,
            )
            and (
                "communication_speaker_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or "communication_direct_speaker_turn"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_exchange_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "exchange" in _str_tuple(item.get("relation_category_hits"))
                or "exchange_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_symbolic_meaning_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "symbolic_meaning" in _str_tuple(item.get("relation_category_hits"))
                or "symbolic_meaning_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_visual_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                item.get("has_visual_evidence") is True
                or "visual" in _str_tuple(item.get("relation_category_hits"))
                or "visual_evidence" in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_inference_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                _str_tuple(item.get("relation_category_hits"))
                or "inference_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or "inference_relation_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or (
                    "inference_entity_hits"
                    in _str_tuple(item.get("planner_reason_codes"))
                    and "inference_relation_hits"
                    in _str_tuple(item.get("planner_reason_codes"))
                )
            )
        )
        for item in _bundle_items(bundle)
    )


def _query_profile_and_intent(
    item: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    metadata = _mapping(_mapping(item.get("retrieval")).get("metadata"))
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    return (
        _mapping(query_decomposition.get("query_profile")),
        _mapping(query_decomposition.get("retrieval_intent")),
    )


def _passes_person_grounding(
    item: Mapping[str, object],
    *,
    require_grounding: bool,
    speaker_grounding: bool = False,
) -> bool:
    if not require_grounding:
        return True
    if speaker_grounding:
        return bool(_str_tuple(item.get("speaker_hits")))
    return bool(_str_tuple(item.get("entity_hits")) or _str_tuple(item.get("speaker_hits")))


def _relation_categories(
    query_profile: Mapping[str, object],
    intent: Mapping[str, object],
) -> tuple[str, ...]:
    categories = _str_tuple(query_profile.get("relation_categories"))
    if categories:
        return categories
    relation_items = _sequence(_mapping(intent.get("relations")).get("intents"))
    return tuple(
        str(relation.get("category") or "").strip()
        for relation in relation_items
        if isinstance(relation, Mapping) and str(relation.get("category") or "").strip()
    )


def _bundle_items(bundle: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(
        item
        for item in _sequence(bundle.get("items"))
        if isinstance(item, Mapping)
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, str):
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, Sequence):
        return tuple(value)
    return ()


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return ()
