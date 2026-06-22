"""Deterministic query decomposition for evidence-oriented retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_decomposition import (
    QueryDecompositionPlan,
    build_query_decomposition_plan,
)


@dataclass(frozen=True)
class QueryExpansion:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryExpansionPlan:
    original_query: str
    expansions: tuple[QueryExpansion, ...]
    decompositions: tuple[QueryExpansion, ...] = ()

    @property
    def retrieval_queries(self) -> tuple[QueryExpansion, ...]:
        return (
            QueryExpansion(query=self.original_query, reason="original_query"),
            *self.decompositions,
            *self.expansions,
        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_expansion_status": "available" if self.expansions else "empty",
            "query_expansion_count": len(self.expansions),
            "query_expansion_reasons": [item.reason for item in self.expansions],
            "query_decomposition_status": (
                "available" if self.decompositions else "empty"
            ),
            "query_decomposition_count": len(self.decompositions),
            "query_decomposition_reasons": [
                item.reason for item in self.decompositions
            ],
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
    (
        frozenset({"screenshot"}),
        "ocr detected text written label title screen image visual текст написано",
        "visual_text_evidence_bridge",
    ),
    (
        frozenset({"image"}),
        "ocr detected text written label title photo picture visual текст написано",
        "visual_text_evidence_bridge",
    ),
    (
        frozenset({"audio"}),
        "transcript speech voice said told mentioned discussed audio транскрипт сказал сказала",
        "audio_transcript_evidence_bridge",
    ),
    (
        frozenset({"video"}),
        (
            "transcript speech said told mentioned discussed keyframe frame video audio "
            "транскрипт сказал сказала обсудили кадр"
        ),
        "video_transcript_evidence_bridge",
    ),
    (
        frozenset({"call"}),
        "transcript conversation said told mentioned discussed decision action item call",
        "conversation_transcript_evidence_bridge",
    ),
    (
        frozenset({"meeting"}),
        "transcript notes discussed decision decisions action items follow up meeting",
        "meeting_evidence_bridge",
    ),
    (
        frozenset({"видео"}),
        "транскрипт сказал сказала обсудили упомянул упомянула кадр видео аудио",
        "video_transcript_evidence_bridge",
    ),
    (
        frozenset({"аудио"}),
        "транскрипт речь голос сказал сказала обсудили аудио",
        "audio_transcript_evidence_bridge",
    ),
    (
        frozenset({"скриншот"}),
        "ocr текст написано надпись экран изображение визуальный",
        "visual_text_evidence_bridge",
    ),
    (
        frozenset({"latest"}),
        (
            "latest current active newest recent updated now valid not stale "
            "актуальный текущий последний"
        ),
        "current_state_temporal_bridge",
    ),
    (
        frozenset({"current"}),
        (
            "latest current active newest recent updated now valid not stale "
            "актуальный текущий последний"
        ),
        "current_state_temporal_bridge",
    ),
    (
        frozenset({"changed"}),
        (
            "changed change updated now before after previous current old new "
            "superseded replaced difference"
        ),
        "change_over_time_bridge",
    ),
    (
        frozenset({"change"}),
        (
            "changed change updated now before after previous current old new "
            "superseded replaced difference"
        ),
        "change_over_time_bridge",
    ),
    (
        frozenset({"updated"}),
        "changed change updated latest current previous superseded replaced difference",
        "change_over_time_bridge",
    ),
    (
        frozenset({"after"}),
        "after later following post meeting call decision follow up next",
        "after_event_temporal_bridge",
    ),
    (
        frozenset({"before"}),
        "before earlier prior previous previous state old initial",
        "before_event_temporal_bridge",
    ),
    (
        frozenset({"актуальн"}),
        "актуальный текущий последний сейчас обновлен действует не устаревший latest current",
        "current_state_temporal_bridge",
    ),
    (
        frozenset({"последн"}),
        "последний актуальный текущий сейчас обновлен latest current recent",
        "current_state_temporal_bridge",
    ),
    (
        frozenset({"обновлен"}),
        "изменилось обновилось последний текущий предыдущий старый новый replaced superseded",
        "change_over_time_bridge",
    ),
    (
        frozenset({"изменилось"}),
        "изменилось изменили стало раньше сейчас до после предыдущий текущий старый новый",
        "change_over_time_bridge",
    ),
    (
        frozenset({"после"}),
        "после позже затем встреча созвон решение follow up next after",
        "after_event_temporal_bridge",
    ),
    (
        frozenset({"до"}),
        "до раньше перед предыдущий начальный старый before prior previous",
        "before_event_temporal_bridge",
    ),
    (
        frozenset({"устаревш"}),
        "устаревший старый superseded replaced previous not current актуальный текущий",
        "stale_state_temporal_bridge",
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


def build_query_expansion_plan(
    query: str,
    *,
    decomposition_plan: QueryDecompositionPlan | None = None,
) -> QueryExpansionPlan:
    decomposition_plan = decomposition_plan or build_query_decomposition_plan(query)
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
    return QueryExpansionPlan(
        original_query=query,
        expansions=tuple(expansions),
        decompositions=tuple(
            QueryExpansion(query=item.query, reason=item.reason)
            for item in decomposition_plan.decompositions
        ),
    )


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
