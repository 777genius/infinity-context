"""Rule selection helpers for deterministic query expansion."""

from __future__ import annotations

import re

from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_identity_terms import (
    raw_query_tokens as _raw_query_tokens,
)
from infinity_context_core.application.context_temporal_query import build_temporal_query_intent

_NEGATIVE_EATING_QUERY_RE = re.compile(
    r"\b(?:can\W*t|cannot|can\s+not|unable\s+to)\b(?=.{0,80}\beat(?:s|ing)?\b)|"
    r"\beat(?:s|ing)?\b(?=.{0,80}\b(?:can\W*t|cannot|can\s+not|unable\s+to)\b)",
    re.IGNORECASE | re.DOTALL,
)
_WHO_ELSE_COMMONALITY_QUERY_RE = re.compile(
    r"\bwho\s+else\b(?=.{0,120}\b(?:like|likes|enjoy|enjoys|love|loves|"
    r"prefer|prefers|interest|hobby|activity|share|shares)\b)|"
    r"\bwho\s+shares?\b(?=.{0,120}\b(?:interest|hobby|activity|like|love|"
    r"preference)\b)|"
    r"\bкто\s+(?:ещ[её])\b(?=.{0,120}\b(?:любит|нравит|интерес|хобби|"
    r"увлечен|увлечён|предпочитает)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BROAD_COMMONALITY_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+(?:do|did|does)\s+"
    r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё._-]{1,39}\s+"
    r"(?:and|&)\s+[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё._-]{1,39}\s+"
    r"(?:both\s+)?(?:have\s+in\s+common|share)\b",
    re.IGNORECASE | re.DOTALL,
)
_SOCIAL_SUPPORT_NETWORK_QUERY_RE = re.compile(
    r"\bwho\b(?=.{0,90}\b(?:support|supports|supported|supporting|help|helps|"
    r"helped|comfort|encourage|encourages|there\s+for|rocks?|family|friends?|"
    r"mentors?)\b)|"
    r"\b(?:who\s+is|who\s+was|who\s+has\s+been)\b(?=.{0,90}\bthere\s+for\b)|"
    r"\bкто\b(?=.{0,90}\b(?:поддерживает|поддерживал|поддерживала|"
    r"поддержал|поддержала|поддержали|помогает|помогал|помогала|"
    r"помог|помогла|помогли|рядом|семья|друзья|наставники)\b)",
    re.IGNORECASE | re.DOTALL,
)
_TECHNICAL_SUPPORT_CONTEXT_TERMS = frozenset(
    {
        "api",
        "backend",
        "browser",
        "client",
        "cloud",
        "customer",
        "database",
        "frontend",
        "infra",
        "infrastructure",
        "integration",
        "library",
        "model",
        "platform",
        "provider",
        "runtime",
        "sdk",
        "service",
        "software",
        "technical",
        "tool",
        "tools",
        "web",
    }
)
_BUSINESS_PROMOTION_TECHNICAL_CONTEXT_TERMS = _TECHNICAL_SUPPORT_CONTEXT_TERMS | frozenset(
    {
        "campaign",
        "dashboard",
    }
)
_AWARENESS_CAUSE_EVENT_CONTEXT_TERMS = frozenset(
    {
        "campaign",
        "cause",
        "causes",
        "charity",
        "event",
        "fundraiser",
        "fundraising",
        "issue",
        "issues",
        "race",
        "raise",
        "raised",
        "raising",
        "spread",
        "spreading",
    }
)
_STORE_PROMOTION_TERMS = frozenset(
    {
        "clothes",
        "clothing",
        "fashion",
        "shop",
        "store",
    }
)
_BUSINESS_EVENT_PROMOTION_TERMS = frozenset(
    {
        "business",
        "startup",
        "venture",
    }
)
_STUDIO_OPENING_TIMELINE_TERMS = frozenset(
    {
        "long",
        "months",
        "time",
        "timeline",
        "took",
    }
)
_SYMBOL_IMPORTANCE_OBJECT_TERMS = frozenset(
    {
        "cross",
        "drawing",
        "eagle",
        "flag",
        "flower",
        "flowers",
        "heart",
        "mural",
        "necklace",
        "pendant",
        "sunflower",
        "sunflowers",
        "symbol",
        "symbols",
        "tattoo",
        "tattoos",
    }
)
_SYMBOL_IMPORTANCE_MEANING_TERMS = frozenset(
    {
        "important",
        "mean",
        "meaning",
        "means",
        "represent",
        "represented",
        "represents",
        "stand",
        "stands",
    }
)
_FAMILY_RELATIVE_TERMS = frozenset(
    {
        "dad",
        "father",
        "family",
        "grandfather",
        "grandma",
        "grandmother",
        "grandpa",
        "mom",
        "mother",
        "parent",
        "parents",
        "relative",
        "relatives",
    }
)
_POSSESSION_GIFT_TERMS = frozenset(
    {
        "gave",
        "gift",
        "gifted",
        "given",
        "got",
        "keepsake",
        "present",
        "receive",
        "received",
    }
)
_POSSESSION_OBJECT_TERMS = frozenset(
    {
        "book",
        "camera",
        "item",
        "necklace",
        "object",
        "pendant",
        "photo",
        "picture",
        "ring",
    }
)
_POSSESSION_GIFT_EFFECT_TERMS = frozenset(
    {
        "cheer",
        "comfort",
        "focus",
        "happy",
        "happiness",
        "joy",
    }
)
_SENTIMENTAL_REMINDER_TERMS = frozenset(
    {
        "remind",
        "reminded",
        "reminder",
        "reminders",
        "reminds",
        "sentimental",
    }
)
_SENTIMENTAL_REMINDER_OBJECT_TERMS = frozenset(
    {
        "bowl",
        "bowls",
        "bracelet",
        "colors",
        "colours",
        "gift",
        "hand",
        "hand-painted",
        "handmade",
        "keepsake",
        "meaning",
        "necklace",
        "pattern",
        "pendant",
        "photo",
        "picture",
        "ring",
        "symbol",
    }
)
_PET_ACQUISITION_OBJECT_TERMS = frozenset(
    {
        "animal",
        "cat",
        "dog",
        "gift",
        "kitten",
        "pet",
        "present",
        "pup",
        "puppy",
        "stuffed",
        "toy",
    }
)
_NAMED_OBJECT_ACQUISITION_QUERY_RE = re.compile(
    r"\bwhen\s+(?:did|was)\s+"
    r"[A-Z][A-Za-z._'-]{1,39}\s+"
    r"(?:get|got|buy|bought|bring|brought|give|gave)\s+"
    r"[A-Z][A-Za-z._'-]{1,39}\s+"
    r"(?:for|to)\s+[A-Z][A-Za-z._'-]{1,39}\b",
    re.IGNORECASE,
)
_NAMED_ADOPTION_QUERY_RE = re.compile(
    r"\bwhen\s+did\s+"
    r"[A-Z][A-Za-z._'-]{1,39}\s+"
    r"adopt(?:ed)?\s+"
    r"[A-Z][A-Za-z._'-]{1,39}\b",
    re.IGNORECASE,
)
_POST_EVENT_EMOTION_TERMS = frozenset(
    {
        "feel",
        "feeling",
        "felt",
        "realize",
        "realized",
    }
)
_POST_EVENT_CONTEXT_TERMS = frozenset(
    {
        "about",
        "accident",
        "after",
        "because",
        "family",
        "grateful",
        "happy",
        "inspired",
        "reaction",
        "sad",
        "thankful",
        "why",
    }
)
_POST_ATHLETIC_CAREER_CONTEXT_TERMS = frozenset(
    {
        "athlete",
        "athletes",
        "athletic",
        "basketball",
        "career",
        "court",
        "sport",
        "sports",
    }
)
_POST_ATHLETIC_CAREER_FUTURE_TERMS = frozenset(
    {
        "after",
        "could",
        "future",
        "life",
        "might",
        "next",
        "post",
    }
)
_STUDY_TIME_MANAGEMENT_CONTEXT_TERMS = frozenset(
    {
        "class",
        "classes",
        "exam",
        "exams",
        "final",
        "finals",
        "homework",
        "prep",
        "prepare",
        "preparing",
        "school",
        "study",
        "studying",
        "test",
        "tests",
    }
)
_STUDY_TIME_MANAGEMENT_METHOD_TERMS = frozenset(
    {
        "break",
        "breaks",
        "focus",
        "interval",
        "intervals",
        "management",
        "method",
        "methods",
        "pomodoro",
        "popular",
        "strategy",
        "technique",
        "techniques",
        "time",
        "trick",
        "tricks",
    }
)
_STUDY_TIME_MANAGEMENT_TECHNICAL_TERMS = _TECHNICAL_SUPPORT_CONTEXT_TERMS | frozenset(
    {
        "cron",
        "deployment",
        "job",
        "jobs",
        "queue",
        "rate",
        "retry",
        "server",
        "timeout",
        "workflow",
    }
)
_TEST_ATTEMPT_TECHNICAL_TERMS = _TECHNICAL_SUPPORT_CONTEXT_TERMS | frozenset(
    {
        "benchmark",
        "build",
        "ci",
        "pipeline",
        "pytest",
        "suite",
        "unit",
    }
)


def query_expansion_variant_set(query: str) -> frozenset[str]:
    variants: set[str] = set()
    for term in query_terms(query, min_chars=2, max_terms=24):
        variants.update(term.variants)
    variants.update(_raw_query_tokens(query))
    if _requests_symbol_importance_variants(variants):
        variants.add("symbol")
    if _NEGATIVE_EATING_QUERY_RE.search(query):
        variants.update(("not", "cannot", "eat"))
    if any(token.startswith("познаком") for token in variants):
        variants.update(("познакомились", "meet", "met"))
    if any(token.startswith("встрет") for token in variants):
        variants.update(("встретились", "meet", "met"))
    return frozenset(variants)


def should_skip_expansion_rule(
    reason: str,
    *,
    query: str,
    raw_tokens: set[str],
) -> bool:
    if reason in {
        "current_recommendation_bridge",
        "current_state_temporal_bridge",
    } and _requests_stale_state_update(query=query, raw_tokens=raw_tokens):
        return True
    if reason == "career_intent_bridge" and "alternative" in raw_tokens:
        return True
    if reason == "career_intent_bridge" and {"future", "job"}.issubset(raw_tokens):
        return True
    if reason == "career_intent_bridge" and raw_tokens.intersection(
        {"because", "reason", "why"}
    ):
        return True
    if reason == "business_commonality_bridge":
        return not _BROAD_COMMONALITY_QUERY_RE.search(query)
    if reason == "store_promotion_inventory_bridge":
        return not _requests_store_promotion_inventory(raw_tokens)
    if reason == "business_promotion_event_bridge":
        return not _requests_business_promotion_events(raw_tokens)
    if reason == "business_networking_event_bridge":
        return not _requests_business_promotion_events(raw_tokens)
    if reason == "business_store_promotion_event_bridge":
        return not _requests_business_promotion_events(raw_tokens)
    if reason == "business_opening_timeline_bridge":
        return not _requests_business_opening_timeline(raw_tokens)
    if reason == "exercise_activity_inventory_bridge" and raw_tokens.intersection(
        {"delay", "delayed", "off", "postpone", "postponed", "why"}
    ):
        return True
    if reason == "hobby_interest_bridge" and _requests_outdoor_activity_inventory(
        raw_tokens
    ):
        return True
    if reason in {"painting_inventory_bridge", "followup_task_bridge"} and (
        _requests_sentimental_reminder(raw_tokens)
    ):
        return True
    if reason == "painting_inventory_bridge" and raw_tokens.intersection(
        {"activity", "activities", "partake"}
    ):
        return True
    if reason == "painting_inventory_bridge" and {"art", "style"}.issubset(raw_tokens):
        return True
    if reason == "book_reading_list_bridge" and raw_tokens.intersection(
        {"recommend", "recommended", "recommendation", "suggest", "suggested", "suggestion"}
    ):
        return True
    if reason == "recommendation_source_bridge" and _is_book_recommendation_object_query(
        raw_tokens
    ):
        return True
    if reason == "children_count_sibling_bridge" and not raw_tokens.intersection(
        {"child", "children", "kid", "kids", "sibling", "siblings", "brother", "sister"}
    ):
        return True
    if reason == "children_name_inventory_bridge":
        return not _requests_children_name_inventory(raw_tokens)
    if reason == "childhood_possession_inventory_bridge":
        return not _requests_childhood_possession_inventory(raw_tokens)
    if reason == "repeated_test_attempt_bridge":
        return not _requests_repeated_test_attempt(raw_tokens)
    if reason == "family_hardship_support_bridge":
        return not _requests_family_hardship_support(raw_tokens)
    if reason == "allergy_inventory_bridge" and raw_tokens.intersection(
        {"condition", "underlying"}
    ):
        return True
    if reason in {
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
    }:
        return not (
            "where" in raw_tokens
            and raw_tokens.intersection({"friend", "friends"})
            and raw_tokens.intersection({"made", "met", "meet", "joined", "join"})
        )
    if reason == "travel_country_inventory_bridge":
        return not (
            raw_tokens.intersection({"cities", "city", "countries", "country", "place"})
            and raw_tokens.intersection(
                {
                    "been",
                    "both",
                    "travel",
                    "traveled",
                    "travelled",
                    "trip",
                    "visited",
                    "visit",
                    "went",
                }
            )
        )
    if reason in {
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
    }:
        return not (
            raw_tokens.intersection({"cause", "causes"})
            and raw_tokens.intersection(
                {"support", "supporting", "passionate", "interested", "interest"}
            )
        )
    if reason == "cause_awareness_event_bridge":
        return not _requests_awareness_cause_event(raw_tokens)
    if reason == "event_participation_bridge" and raw_tokens.intersection(
        {"military", "veteran", "veterans"}
    ):
        return True
    if reason == "support_network_bridge":
        return (
            not _SOCIAL_SUPPORT_NETWORK_QUERY_RE.search(query)
            or bool(raw_tokens.intersection(_TECHNICAL_SUPPORT_CONTEXT_TERMS))
        )
    if reason == "relationship_origin_bridge":
        return not _requests_relationship_origin(raw_tokens)
    if reason == "relationship_status_bridge":
        return not _requests_relationship_status(raw_tokens)
    if reason == "possession_gift_object_bridge":
        return not _requests_possession_gift_object(raw_tokens)
    if reason == "family_origin_bridge":
        return not _requests_family_origin(raw_tokens)
    if reason == "post_event_emotion_bridge":
        return not _requests_post_event_emotion(raw_tokens)
    if reason == "symbol_importance_bridge":
        return not _requests_symbol_importance(raw_tokens)
    if reason == "post_athletic_career_bridge":
        return not _requests_post_athletic_career(raw_tokens)
    if reason == "study_time_management_bridge":
        return not _requests_study_time_management(raw_tokens)
    if reason == "pet_acquisition_date_bridge":
        return not _requests_pet_acquisition_date(query=query, raw_tokens=raw_tokens)
    if reason == "after_event_temporal_bridge":
        return not build_temporal_query_intent(query).after_event
    if reason == "before_event_temporal_bridge":
        return not build_temporal_query_intent(query).before_event
    return reason == "camping_detail_bridge" and not any(
        token.startswith("camp") for token in raw_tokens
    )


def _requests_relationship_origin(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(
        {
            "introduced",
            "introduce",
            "known",
            "meet",
            "met",
        }
    ):
        return True
    return any(
        token.startswith(("познаком", "встрет"))
        for token in raw_tokens
    )


def _requests_relationship_status(raw_tokens: set[str]) -> bool:
    if {"relationship", "status"}.issubset(raw_tokens):
        return True
    if raw_tokens.intersection({"single", "married", "dating", "partner", "spouse"}):
        return True
    if raw_tokens.intersection({"помимо", "кроме", "besides", "other", "apart"}):
        return False
    return bool(
        raw_tokens.intersection(
            {
                "друг",
                "друга",
                "друзья",
                "отношения",
                "пара",
                "партнер",
                "партнёр",
                "партнеры",
                "партнёры",
                "связан",
                "связана",
                "связаны",
                "супруг",
                "супруга",
            }
        )
    )


def _requests_symbol_importance(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection({"symbol", "symbols"}) or any(
        token.startswith(("symbolic", "symbolis", "symboliz")) for token in raw_tokens
    ):
        return True
    if (
        raw_tokens.intersection(_SYMBOL_IMPORTANCE_OBJECT_TERMS)
        and raw_tokens.intersection(_SYMBOL_IMPORTANCE_MEANING_TERMS)
    ):
        return True
    return bool(
        "for" in raw_tokens
        and raw_tokens.intersection(_SYMBOL_IMPORTANCE_OBJECT_TERMS)
        and raw_tokens.intersection({"stand", "stands"})
    )


def _requests_sentimental_reminder(raw_tokens: set[str]) -> bool:
    return bool(
        raw_tokens.intersection(_SENTIMENTAL_REMINDER_TERMS)
        and raw_tokens.intersection(_SENTIMENTAL_REMINDER_OBJECT_TERMS)
    )


def _requests_possession_gift_object(raw_tokens: set[str]) -> bool:
    if not raw_tokens.intersection(_POSSESSION_GIFT_TERMS):
        return False
    return bool(
        raw_tokens.intersection(_FAMILY_RELATIVE_TERMS)
        or raw_tokens.intersection(_POSSESSION_OBJECT_TERMS)
        or raw_tokens.intersection(_POSSESSION_GIFT_EFFECT_TERMS)
    )


def _requests_pet_acquisition_date(*, query: str, raw_tokens: set[str]) -> bool:
    if "when" not in raw_tokens:
        return False
    if raw_tokens.intersection({"meeting", "meetings", "appointment", "appointments"}):
        return False
    acquisition_verbs = {"adopt", "adopted", "get", "got", "buy", "bought"}
    if not raw_tokens.intersection(acquisition_verbs):
        return False
    if raw_tokens.intersection(_PET_ACQUISITION_OBJECT_TERMS):
        return True
    return bool(
        _NAMED_OBJECT_ACQUISITION_QUERY_RE.search(query)
        or _NAMED_ADOPTION_QUERY_RE.search(query)
    )


def _requests_family_origin(raw_tokens: set[str]) -> bool:
    if not raw_tokens.intersection(_FAMILY_RELATIVE_TERMS):
        return False
    return bool(raw_tokens.intersection({"country", "from", "home", "native", "origin"}))


def _requests_children_name_inventory(raw_tokens: set[str]) -> bool:
    return bool(
        raw_tokens.intersection({"child", "children", "kid", "kids"})
        and raw_tokens.intersection({"name", "names", "called", "named"})
    )


def _requests_childhood_possession_inventory(raw_tokens: set[str]) -> bool:
    if not raw_tokens.intersection({"child", "childhood", "kid", "kids", "younger"}):
        return False
    return bool(
        raw_tokens.intersection({"item", "items", "object", "objects", "having", "had"})
    )


def _requests_repeated_test_attempt(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(_TEST_ATTEMPT_TECHNICAL_TERMS):
        return False
    if not raw_tokens.intersection({"test", "tests", "exam", "assessment"}):
        return False
    return bool(
        raw_tokens.intersection(
            {"multiple", "again", "retake", "retook", "repeated", "several"}
        )
    )


def _requests_family_hardship_support(raw_tokens: set[str]) -> bool:
    if not raw_tokens.intersection({"family", "parent", "parents"}):
        return False
    if not raw_tokens.intersection({"money", "financial", "help", "helped", "support"}):
        return False
    return bool(
        raw_tokens.intersection({"younger", "hardship", "struggling", "struggle", "tough"})
    )


def _requests_outdoor_activity_inventory(raw_tokens: set[str]) -> bool:
    return "outdoor" in raw_tokens and bool(
        raw_tokens.intersection(
            {
                "activity",
                "activities",
                "camp",
                "camping",
                "hike",
                "hiking",
                "mountain",
                "mountains",
                "park",
                "trail",
            }
        )
    )


def _requests_post_event_emotion(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(_TECHNICAL_SUPPORT_CONTEXT_TERMS):
        return False
    return bool(
        raw_tokens.intersection(_POST_EVENT_EMOTION_TERMS)
        and raw_tokens.intersection(_POST_EVENT_CONTEXT_TERMS)
    )


def _requests_post_athletic_career(raw_tokens: set[str]) -> bool:
    return bool(
        "career" in raw_tokens
        and raw_tokens.intersection(_POST_ATHLETIC_CAREER_CONTEXT_TERMS)
        and raw_tokens.intersection(_POST_ATHLETIC_CAREER_FUTURE_TERMS)
    )


def _requests_study_time_management(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(_STUDY_TIME_MANAGEMENT_TECHNICAL_TERMS):
        return False
    return bool(
        raw_tokens.intersection(_STUDY_TIME_MANAGEMENT_CONTEXT_TERMS)
        and raw_tokens.intersection(_STUDY_TIME_MANAGEMENT_METHOD_TERMS)
    )


def _requests_store_promotion_inventory(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(_BUSINESS_PROMOTION_TECHNICAL_CONTEXT_TERMS):
        return False
    return bool(
        "promote" in raw_tokens
        and raw_tokens.intersection(_STORE_PROMOTION_TERMS)
    )


def _requests_business_promotion_events(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(_BUSINESS_PROMOTION_TECHNICAL_CONTEXT_TERMS):
        return False
    return bool(
        raw_tokens.intersection({"event", "events", "participated", "attended"})
        and "promote" in raw_tokens
        and raw_tokens.intersection(_BUSINESS_EVENT_PROMOTION_TERMS)
    )


def _requests_business_opening_timeline(raw_tokens: set[str]) -> bool:
    if raw_tokens.intersection(_BUSINESS_PROMOTION_TECHNICAL_CONTEXT_TERMS):
        return False
    return bool(
        "open" in raw_tokens
        and "studio" in raw_tokens
        and raw_tokens.intersection(_STUDIO_OPENING_TIMELINE_TERMS)
    )


def _requests_awareness_cause_event(raw_tokens: set[str]) -> bool:
    return bool(
        raw_tokens.intersection({"aware", "awareness"})
        and raw_tokens.intersection(_AWARENESS_CAUSE_EVENT_CONTEXT_TERMS)
    )


def _requests_symbol_importance_variants(variants: set[str]) -> bool:
    if variants.intersection({"symbol", "symbols"}) or any(
        token.startswith(("symbolic", "symbolis", "symboliz")) for token in variants
    ):
        return True
    if (
        variants.intersection(_SYMBOL_IMPORTANCE_OBJECT_TERMS)
        and variants.intersection(_SYMBOL_IMPORTANCE_MEANING_TERMS)
    ):
        return True
    return bool(
        "for" in variants
        and variants.intersection(_SYMBOL_IMPORTANCE_OBJECT_TERMS)
        and variants.intersection({"stand", "stands"})
    )


def identity_terms_for_expansion(
    *,
    reason: str,
    query: str,
    identity_terms: tuple[str, ...],
) -> tuple[str, ...]:
    if reason == "choice_reason_bridge":
        return ()
    if reason == "commonality_interest_bridge" and _WHO_ELSE_COMMONALITY_QUERY_RE.search(query):
        return ()
    if reason in {
        "business_networking_event_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "store_promotion_inventory_bridge",
    }:
        return ()
    if reason == "nickname_bridge" and len(identity_terms) > 1:
        return identity_terms[:1]
    if reason == "travel_country_inventory_bridge":
        return tuple(
            term
            for term in identity_terms
            if term.casefold() not in {"europe", "european", "европа", "европейские"}
        )
    return identity_terms


def _requests_stale_state_update(*, query: str, raw_tokens: set[str]) -> bool:
    normalized = query.casefold()
    if any(
        phrase in normalized
        for phrase in (
            "not stale",
            "not outdated",
            "not obsolete",
            "not deprecated",
            "not expired",
        )
    ):
        return False
    return bool(
        "no longer" in normalized
        or "not current" in normalized
        or raw_tokens.intersection({"anymore", "stopped", "больше"})
        or {"longer", "use"}.issubset(raw_tokens)
        or {"больше", "использовать"}.issubset(raw_tokens)
    )


def _is_book_recommendation_object_query(raw_tokens: set[str]) -> bool:
    return (
        bool(raw_tokens.intersection({"book", "books"}))
        and bool(raw_tokens.intersection({"what"}))
        and bool(
            raw_tokens.intersection(
                {
                    "recommend",
                    "recommended",
                    "recommendation",
                    "suggest",
                    "suggested",
                    "suggestion",
                }
            )
        )
        and not raw_tokens.intersection({"who", "whose", "whom", "source"})
    )
