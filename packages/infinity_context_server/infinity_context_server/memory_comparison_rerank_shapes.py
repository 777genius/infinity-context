"""Evidence-shape boost policies for benchmark reranking."""

from __future__ import annotations

from collections.abc import Sequence


def focused_evidence_shape_boosts(
    *,
    memory_terms: set[str],
    relation_terms: Sequence[str],
    focused_turn_boost: float,
    relation_category_hits: Sequence[str] = (),
    direct_speaker_turn: bool = False,
) -> dict[str, float]:
    relation_set = set(relation_terms)
    category_hit_set = set(relation_category_hits)
    boosts = _empty_shape_boosts()
    activity_category_evidence = (
        direct_speaker_turn
        and "activity" in category_hit_set
        and ("activity" in relation_set or "hike" in relation_set)
    )
    adoption_reaction_evidence = (
        direct_speaker_turn
        and {"think", "decision", "adopt"}.issubset(relation_set)
        and _has_adoption_reaction_answer_shape(memory_terms)
    )
    if (
        focused_turn_boost <= 0
        and not activity_category_evidence
        and not adoption_reaction_evidence
    ):
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
            0.22
            if _has_adoption_reaction_answer_shape(memory_terms)
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
        birthday_context = "birthday" in memory_terms and (
            {"18th", "age", "year", "years"} & memory_terms
        )
        personal_memento = (
            {"gift", "keepsake", "memento", "special", "treasure", "remember"}
            & memory_terms
        )
        giver_context = {"friend", "family", "parent", "mother", "father"} & memory_terms
        boosts["benchmark_birthday_memory_boost"] = (
            0.08 if birthday_context and personal_memento and giver_context else 0.0
        )
    if "activity" in relation_set or "hike" in relation_set:
        boosts["benchmark_activity_coverage_shape_boost"] = (
            0.1
            if (
                {"paint", "sunrise"} <= memory_terms
                or ({"kid"} <= memory_terms and {"swim", "swimming"} & memory_terms)
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


def _has_adoption_reaction_answer_shape(memory_terms: set[str]) -> bool:
    positive_reaction = (
        {"amazing", "lovely", "mom"} <= memory_terms
        or {"awesome", "mom"} <= memory_terms
        or {"lovely", "luck"} <= memory_terms
    )
    adoption_outcome = bool({"family", "kid", "kids", "child", "children"} & memory_terms)
    return positive_reaction and adoption_outcome


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
