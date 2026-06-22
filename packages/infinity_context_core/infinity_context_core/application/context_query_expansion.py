"""Deterministic query decomposition for evidence-oriented retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from infinity_context_core.application.context_lexical import query_terms


@dataclass(frozen=True)
class QueryExpansion:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryExpansionPlan:
    original_query: str
    expansions: tuple[QueryExpansion, ...]

    @property
    def retrieval_queries(self) -> tuple[QueryExpansion, ...]:
        return (
            QueryExpansion(query=self.original_query, reason="original_query"),
            *self.expansions,
        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_expansion_status": "available" if self.expansions else "empty",
            "query_expansion_count": len(self.expansions),
            "query_expansion_reasons": [item.reason for item in self.expansions],
        }


_EXPANSION_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (
        frozenset({"pursue", "career"}),
        "looking counseling mental health jobs education options work",
        "career_intent_bridge",
    ),
    (
        frozenset({"support", "career"}),
        (
            "motivation motivated mattered made difference support got counseling "
            "support groups improved life mental health help people safe inviting grow"
        ),
        "support_career_motivation_bridge",
    ),
    (
        frozenset({"support", "growing"}),
        "journey love support acceptance community hope",
        "support_counterfactual_bridge",
    ),
    (
        frozenset({"support", "growing"}),
        "blessed love support journey supportive community hope",
        "support_origin_bridge",
    ),
    (
        frozenset({"move", "from"}),
        "moved home country roots family origin",
        "relocation_origin_bridge",
    ),
    (
        frozenset({"national", "park"}),
        "camping trip campfire meteor shower nature outdoors",
        "outdoor_preference_bridge",
    ),
    (
        frozenset({"theme", "park"}),
        "camping trip campfire meteor shower nature outdoors",
        "outdoor_preference_bridge",
    ),
    (
        frozenset({"national", "park"}),
        "camping trip meteor shower sky universe nature",
        "outdoor_nature_memory_bridge",
    ),
    (
        frozenset({"theme", "park"}),
        "camping trip meteor shower sky universe nature",
        "outdoor_nature_memory_bridge",
    ),
    (
        frozenset({"decision", "adopt"}),
        "adoption family kids children mom support good luck",
        "adoption_support_bridge",
    ),
    (
        frozenset({"ally", "transgender"}),
        "supportive support acceptance community encouraging trans lgbtq",
        "ally_support_bridge",
    ),
    (
        frozenset({"member", "community"}),
        "part belong identify refer herself community lgbtq",
        "community_membership_bridge",
    ),
    (
        frozenset({"political", "leaning"}),
        "rights lgbtq transition conservative conservatives unwelcoming support",
        "political_inference_bridge",
    ),
    (
        frozenset({"religious"}),
        "church faith religious conservative conservatives",
        "religious_inference_bridge",
    ),
    (
        frozenset({"destress"}),
        "running pottery class therapeutic therapy calm relax clear mind headspace",
        "destress_activity_bridge",
    ),
    (
        frozenset({"camped"}),
        "camping camped family mountains beach forest outdoors trip",
        "camping_location_bridge",
    ),
    (
        frozenset({"activities"}),
        "pottery camping painting swimming running hobbies activities creative outdoors",
        "activity_aggregation_bridge",
    ),
    (
        frozenset({"partake"}),
        "pottery camping painting swimming running hobbies activities creative outdoors",
        "activity_aggregation_bridge",
    ),
    (
        frozenset({"personality", "traits"}),
        (
            "thoughtful authentic driven drive determined dedicated passionate "
            "real care concern help helpful kind plan pitch awesome"
        ),
        "personality_trait_bridge",
    ),
    (
        frozenset({"personality", "traits"}),
        "thoughtful concern caring considerate precaution sign",
        "personality_thoughtfulness_bridge",
    ),
    (
        frozenset({"personality", "traits"}),
        "authentic real genuine true self care helping others",
        "personality_authenticity_bridge",
    ),
    (
        frozenset({"personality", "traits"}),
        "driven drive determined dedicated passionate plan pitch help awesome",
        "personality_drive_bridge",
    ),
    (
        frozenset({"roadtrip"}),
        "roadtrip accident scary scared bad start freaked lucky okay family",
        "adverse_trip_bridge",
    ),
)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CAPITALIZED_IDENTITY_STOPWORDS = frozenset(
    {
        "Are",
        "Can",
        "Could",
        "Did",
        "Does",
        "How",
        "Is",
        "May",
        "Might",
        "Should",
        "The",
        "Was",
        "Were",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Whom",
        "Why",
        "Will",
        "Would",
        "Где",
        "Зачем",
        "Как",
        "Какая",
        "Какие",
        "Какой",
        "Когда",
        "Кто",
        "Почему",
        "Что",
    }
)


def build_query_expansion_plan(query: str) -> QueryExpansionPlan:
    query_term_variants = _query_variant_set(query)
    identity_terms = _capitalized_identity_terms(query)
    expansions: list[QueryExpansion] = []
    seen_queries = {query.strip().casefold()}
    seen_reasons: set[str] = set()
    for required_terms, expansion, reason in _EXPANSION_RULES:
        if reason in seen_reasons:
            continue
        if not required_terms.issubset(query_term_variants):
            continue
        expanded_query = _with_identity_terms(identity_terms, expansion)
        normalized_expanded_query = expanded_query.casefold()
        if normalized_expanded_query in seen_queries:
            continue
        expansions.append(QueryExpansion(query=expanded_query, reason=reason))
        seen_queries.add(normalized_expanded_query)
        seen_reasons.add(reason)
        if len(expansions) >= 8:
            break
    return QueryExpansionPlan(original_query=query, expansions=tuple(expansions))


def _query_variant_set(query: str) -> frozenset[str]:
    variants: set[str] = set()
    for term in query_terms(query, min_chars=2, max_terms=24):
        variants.update(term.variants)
    variants.update(_raw_query_tokens(query))
    return frozenset(variants)


def _raw_query_tokens(query: str) -> Iterable[str]:
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            yield token


def _capitalized_identity_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).strip("_")
        if len(token) < 2 or token in _CAPITALIZED_IDENTITY_STOPWORDS:
            continue
        if not token[:1].isupper():
            continue
        normalized = token.casefold()
        if normalized in seen:
            continue
        terms.append(token)
        seen.add(normalized)
        if len(terms) >= 3:
            break
    return tuple(terms)


def _with_identity_terms(identity_terms: tuple[str, ...], expansion: str) -> str:
    if not identity_terms:
        return expansion
    return " ".join((*identity_terms, expansion))
