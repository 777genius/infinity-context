"""Partial required-role support diagnostics for evidence bundles."""

from __future__ import annotations

from collections.abc import Mapping

_PARTIAL_REQUIRED_ROLE_CATEGORY_HINTS = {
    "causal_support": frozenset(
        {
            "emotion_response",
            "exchange",
            "inference",
            "participation_event",
            "registration_event",
        }
    ),
    "communication_support": frozenset({"exchange"}),
    "emotion_response_support": frozenset({"causal", "exchange"}),
    "event_support": frozenset(
        {
            "activity",
            "activity_profile",
            "action_event",
            "current_goal",
            "exchange",
        }
    ),
    "exchange_support": frozenset({"communication"}),
    "inference_support": frozenset(
        {
            "causal",
            "emotion_response",
            "participation_event",
            "registration_event",
            "symbolic_meaning",
        }
    ),
    "location_support": frozenset(
        {"activity", "activity_profile", "travel", "workplace"}
    ),
    "preference_support": frozenset({"favorite_preference"}),
    "symbolic_meaning_support": frozenset({"emotion_response"}),
    "visual_support": frozenset({"activity", "activity_profile"}),
}


def has_partial_required_role_support(
    candidate: object,
    *,
    item_role: str,
    role: str,
    complete_support: bool,
    typed_relation_support_categories: Mapping[str, frozenset[str]],
) -> bool:
    """Return true when an item is relevant but lacks the required evidence shape."""

    if complete_support:
        return False
    role_key = role.removesuffix("_support")
    query_roles = set(_str_tuple(getattr(candidate, "query_roles", ())))
    if role in query_roles:
        return True
    if role == "temporal_support":
        return bool(
            item_role == "temporal_support"
            or getattr(candidate, "has_temporal_surface", False)
            or getattr(candidate, "has_sequence_surface", False)
            or getattr(candidate, "has_duration_surface", False)
            or getattr(candidate, "has_relative_time_surface", False)
            or getattr(candidate, "has_explicit_time_surface", False)
            or getattr(candidate, "has_temporal_sequence_surface", False)
            or getattr(candidate, "currentness_surface", False)
        )
    if role == "contrast":
        return bool(
            getattr(candidate, "contrast_surface", False)
            or getattr(candidate, "currentness_surface", False)
            or getattr(candidate, "stale_surface", False)
            or getattr(candidate, "negation_surface", False)
        )
    if role == "bridge":
        return bool(getattr(candidate, "bridge_query_hit", False))
    categories = set(_str_tuple(getattr(candidate, "relation_category_hits", ())))
    if role in _PARTIAL_REQUIRED_ROLE_CATEGORY_HINTS:
        return bool(categories.intersection(_PARTIAL_REQUIRED_ROLE_CATEGORY_HINTS[role]))
    typed_categories = typed_relation_support_categories.get(role)
    if typed_categories:
        return bool(
            categories
            or _str_tuple(getattr(candidate, "relation_hits", ()))
            or role_key in query_roles
        )
    return bool(
        categories
        or _str_tuple(getattr(candidate, "relation_hits", ()))
        or _str_tuple(getattr(candidate, "entity_hits", ()))
        or _str_tuple(getattr(candidate, "speaker_hits", ()))
    )


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes):
        return ()
    try:
        return tuple(str(item).strip() for item in value if str(item).strip())
    except TypeError:
        return ()
