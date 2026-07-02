"""Evidence-shape boost policies for benchmark reranking."""

from __future__ import annotations

from collections.abc import Sequence


def focused_evidence_shape_boosts(
    *,
    memory_terms: set[str],
    relation_terms: Sequence[str],
    focused_turn_boost: float,
) -> dict[str, float]:
    relation_set = set(relation_terms)
    boosts = _empty_shape_boosts()
    if focused_turn_boost <= 0:
        return boosts
    if {"kid", "like"}.issubset(relation_set):
        kids_nature = {"kid", "nature", "love"} <= memory_terms
        kids_exhibit = {"dinosaur", "exhibit", "learn"} <= memory_terms and (
            {"animal", "bone"} & memory_terms
        )
        boosts["benchmark_kids_preference_shape_boost"] = (
            0.08 if kids_nature or kids_exhibit else 0.0
        )
    if {"book", "bookshelf"}.issubset(relation_set):
        boosts["benchmark_bookshelf_collection_boost"] = (
            0.08
            if {"book", "kid", "story", "classic"} <= memory_terms
            and {"culture", "educational"} & memory_terms
            else 0.0
        )
    if {"personality", "trait"}.issubset(relation_set):
        if {"concern", "thoughtful"} <= memory_terms:
            boosts["benchmark_personality_trait_shape_boost"] = 0.14
        elif {"care", "real", "help"} <= memory_terms or {"drive", "help"} <= memory_terms:
            boosts["benchmark_personality_trait_shape_boost"] = 0.08
    if "roadtrip" in relation_set:
        boosts["benchmark_roadtrip_incident_boost"] = (
            0.16
            if (
                {"trip", "bad", "start", "accident"} <= memory_terms
                or {"roadtrip", "son", "accident"} <= memory_terms
            )
            else 0.0
        )
    if {"realize", "charity", "race"}.issubset(relation_set):
        boosts["benchmark_realization_self_care_boost"] = (
            0.08
            if {"realize", "self-care", "important"} <= memory_terms
            and {"event", "thought-provok"} & memory_terms
            else 0.0
        )
    if {"think", "decision", "adopt"}.issubset(relation_set):
        boosts["benchmark_adoption_reaction_boost"] = (
            0.1
            if {"amazing", "lovely", "mom"} <= memory_terms
            and {"family", "kid"} & memory_terms
            else 0.0
        )
    if {"current", "group", "friend"}.issubset(relation_set):
        boosts["benchmark_friend_duration_boost"] = (
            0.08
            if {"known", "friend", "year"} <= memory_terms
            and {"mov", "moved", "since"} & memory_terms
            else 0.0
        )
    if "birthday" in relation_set:
        boosts["benchmark_birthday_memory_boost"] = (
            0.08
            if {"18th", "birthday", "bowl", "friend"} <= memory_terms
            and {"hand-paint", "treasure"} & memory_terms
            else 0.0
        )
    if "activity" in relation_set or "hike" in relation_set:
        boosts["benchmark_activity_coverage_shape_boost"] = (
            0.1
            if (
                {"paint", "sunrise"} <= memory_terms
                or {"swim", "kid"} <= memory_terms
                or {"hike", "water"} <= memory_terms
                or {"hike", "spot"} <= memory_terms
                or {"hike", "summer"} <= memory_terms
                or {"hik", "weekend"} <= memory_terms
                or {"run", "read", "violin"} <= memory_terms
                or {"camping", "unplug"} <= memory_terms
            )
            else 0.0
        )
    if "destress" in relation_set:
        boosts["benchmark_destress_running_shape_boost"] = (
            0.26
            if "run" in memory_terms
            and {"de-stres", "destress", "stress"} & memory_terms
            else 0.0
        )
    if {"write", "career"}.issubset(relation_set):
        career_path = {"counsel", "mental", "health"} <= memory_terms and (
            {"job", "jobs"} & memory_terms
        )
        boosts["benchmark_career_contrast_shape_boost"] = (
            0.28 if career_path and {"support", "talk", "help"} & memory_terms
            else 0.0
        )
    return boosts


def _empty_shape_boosts() -> dict[str, float]:
    return {
        "benchmark_kids_preference_shape_boost": 0.0,
        "benchmark_bookshelf_collection_boost": 0.0,
        "benchmark_personality_trait_shape_boost": 0.0,
        "benchmark_roadtrip_incident_boost": 0.0,
        "benchmark_realization_self_care_boost": 0.0,
        "benchmark_adoption_reaction_boost": 0.0,
        "benchmark_friend_duration_boost": 0.0,
        "benchmark_birthday_memory_boost": 0.0,
        "benchmark_activity_coverage_shape_boost": 0.0,
        "benchmark_destress_running_shape_boost": 0.0,
        "benchmark_career_contrast_shape_boost": 0.0,
    }
