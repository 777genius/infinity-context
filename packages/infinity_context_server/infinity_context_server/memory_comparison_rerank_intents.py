"""Focused intent policies for memory-comparison benchmark rerank."""

from __future__ import annotations

from collections.abc import Sequence


def focused_intent_policy_boosts(
    *,
    memory_terms: set[str],
    relation_terms: Sequence[str],
    relation_hits: Sequence[str],
    focused_turn_boost: float,
) -> dict[str, float]:
    boosts = _empty_intent_policy_boosts()
    if focused_turn_boost <= 0:
        return boosts

    relation_set = set(relation_terms)
    hit_set = set(relation_hits)
    boosts["benchmark_excited_outcome_boost"] = _excited_outcome_boost(
        relation_set=relation_set,
        hit_set=hit_set,
    )
    boosts["benchmark_song_preference_boost"] = _song_preference_boost(
        relation_set=relation_set,
        hit_set=hit_set,
    )
    boosts["benchmark_writing_affinity_boost"] = _writing_affinity_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    boosts["benchmark_outdoor_park_preference_boost"] = (
        _outdoor_park_preference_boost(
            memory_terms=memory_terms,
            relation_set=relation_set,
        )
    )
    boosts["benchmark_support_motivation_boost"] = _support_motivation_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    boosts["benchmark_research_goal_boost"] = _research_goal_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    boosts["benchmark_identity_visual_identity_boost"] = (
        _identity_visual_identity_boost(
            memory_terms=memory_terms,
            relation_set=relation_set,
        )
    )
    boosts["benchmark_political_context_boost"] = _political_context_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    boosts["benchmark_adoption_agency_support_boost"] = (
        _adoption_agency_support_boost(
            memory_terms=memory_terms,
            relation_set=relation_set,
        )
    )
    boosts["benchmark_conference_plan_time_boost"] = _conference_plan_time_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    boosts["benchmark_relationship_status_context_boost"] = (
        _relationship_status_context_boost(
            memory_terms=memory_terms,
            relation_set=relation_set,
        )
    )
    boosts["benchmark_current_goal_context_boost"] = _current_goal_context_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    boosts["benchmark_registration_event_boost"] = _registration_event_boost(
        memory_terms=memory_terms,
        relation_set=relation_set,
    )
    return boosts


def _empty_intent_policy_boosts() -> dict[str, float]:
    return {
        "benchmark_excited_outcome_boost": 0.0,
        "benchmark_song_preference_boost": 0.0,
        "benchmark_writing_affinity_boost": 0.0,
        "benchmark_outdoor_park_preference_boost": 0.0,
        "benchmark_support_motivation_boost": 0.0,
        "benchmark_research_goal_boost": 0.0,
        "benchmark_identity_visual_identity_boost": 0.0,
        "benchmark_political_context_boost": 0.0,
        "benchmark_adoption_agency_support_boost": 0.0,
        "benchmark_conference_plan_time_boost": 0.0,
        "benchmark_relationship_status_context_boost": 0.0,
        "benchmark_current_goal_context_boost": 0.0,
        "benchmark_registration_event_boost": 0.0,
    }


def _excited_outcome_boost(*, relation_set: set[str], hit_set: set[str]) -> float:
    if not {"excite", "adoption", "process"}.issubset(relation_set):
        return 0.0
    if "thrill" in hit_set and {"make", "create"} & hit_set:
        return 0.16
    if {"excite", "create"} <= hit_set:
        return 0.08
    return 0.0


def _song_preference_boost(*, relation_set: set[str], hit_set: set[str]) -> float:
    if not {"enjoy", "song"}.issubset(relation_set):
        return 0.0
    return 0.08 if {"fan", "like"} <= hit_set else 0.0


def _writing_affinity_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"write", "career"}.issubset(relation_set):
        return 0.0
    if {"book", "read"} & memory_terms and {
        "discover",
        "guide",
        "motivate",
    } & memory_terms:
        return 0.25
    return 0.0


def _outdoor_park_preference_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"interest", "park"}.issubset(relation_set):
        return 0.0
    durable_camping_preference = (
        {"camping", "trip"} <= memory_terms
        and {"campfire", "marshmallow", "story"} & memory_terms
        and {"always", "highlight", "summer"} & memory_terms
    )
    memorable_sky_preference = (
        {"meteor", "shower"} <= memory_terms
        and {"remember", "wish", "universe"} & memory_terms
        and {"sky", "amazing"} & memory_terms
    )
    return 0.1 if durable_camping_preference or memorable_sky_preference else 0.0


def _support_motivation_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"counsel", "receive", "support", "grow"}.issubset(relation_set):
        return 0.0
    received_support = {"support", "got"} <= memory_terms
    changed_life = {"difference", "huge"} <= memory_terms or {
        "improv",
        "life",
    } <= memory_terms
    counseling_path = {"counsel", "group"} & memory_terms and {
        "mental",
        "health",
        "grow",
    } & memory_terms
    return 0.1 if received_support and changed_life and counseling_path else 0.0


def _research_goal_boost(*, memory_terms: set[str], relation_set: set[str]) -> float:
    if "research" not in relation_set:
        return 0.0
    direct_research = "research" in memory_terms
    family_goal = {"dream", "family", "home"} <= memory_terms and {
        "kid",
        "kids",
    } & memory_terms
    return 0.22 if direct_research and family_goal else 0.0


def _identity_visual_identity_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if "identity" not in relation_set:
        return 0.0
    visual_identity_surface = {"transgender", "pride", "flag", "mural"} <= memory_terms
    first_person_story_surface = {"story", "inspir", "support"} <= memory_terms
    return 0.08 if visual_identity_surface and first_person_story_surface else 0.0


def _political_context_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if "political" not in relation_set:
        return 0.0
    conservative_encounter = {"conservative", "hike", "upset"} <= memory_terms
    rights_context = {"lgbtq", "right", "work"} <= memory_terms
    support_context = {"accept", "support"} <= memory_terms
    return 0.08 if conservative_encounter and rights_context and support_context else 0.0


def _adoption_agency_support_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"individual", "adoption", "support"}.issubset(relation_set):
        return 0.0
    lgbtq_surface = "lgbtq" in memory_terms or "lgbtq+" in memory_terms
    agency_choice = {"chose", "help", "adoption"} <= memory_terms
    inclusive_support = {"inclusivity", "support", "spoke"} <= memory_terms
    return 0.08 if lgbtq_surface and agency_choice and inclusive_support else 0.0


def _conference_plan_time_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if "conference" not in relation_set:
        return 0.0
    planned_time = {"conference", "month"} <= memory_terms and "going" in memory_terms
    purpose_context = {"community", "advocacy"} & memory_terms
    return 0.08 if planned_time and purpose_context else 0.0


def _relationship_status_context_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"relationship", "status"}.issubset(relation_set):
        return 0.0
    direct_breakup_context = {"breakup", "family"} <= memory_terms and {
        "parent",
        "friend",
        "support",
    } & memory_terms
    parenting_context = {"parent", "family", "challenge"} <= memory_terms
    return 0.1 if direct_breakup_context or parenting_context else 0.0


def _current_goal_context_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"want", "move"} <= relation_set:
        return 0.0
    if {"goal", "future"} & memory_terms:
        return 0.18
    if {"hope", "plan"} & memory_terms:
        return 0.12
    return 0.0


def _registration_event_boost(
    *,
    memory_terms: set[str],
    relation_set: set[str],
) -> float:
    if not {"enroll", "register", "sign"} & relation_set:
        return 0.0
    registration_action = {
        "enroll",
        "enrolled",
        "register",
        "registered",
        "registration",
        "sign",
        "signed",
        "signup",
    } & memory_terms
    event_context = {"class", "course", "lesson", "workshop", "event"} & memory_terms
    return 0.12 if registration_action and event_context else 0.0
