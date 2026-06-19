"""Query relevance helpers for context assembly."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_counts,
    text_variant_sequence,
)


@dataclass(frozen=True)
class QueryRelevance:
    score_boost: float
    query_term_count: int
    unique_term_hits: int
    capped_frequency_hits: int
    hit_ratio: float
    distinctive_term_count: int = 0
    distinctive_term_hits: int = 0
    phrase_bigram_count: int = 0
    phrase_bigram_hits: int = 0
    phrase_boost: float = 0.0


_GENERIC_MEMORY_QUERY_TERMS = frozenset(
    {
        "about",
        "audio",
        "call",
        "chat",
        "document",
        "event",
        "file",
        "image",
        "link",
        "meeting",
        "memory",
        "note",
        "photo",
        "picture",
        "project",
        "scope",
        "screenshot",
        "task",
        "thread",
        "transcript",
        "video",
        "аудио",
        "видео",
        "встреч",
        "документ",
        "задач",
        "заметк",
        "изображени",
        "картинк",
        "памят",
        "пользовател",
        "проект",
        "событи",
        "скриншот",
        "сохран",
        "транскрипт",
        "файл",
        "фото",
        "чат",
        "человек",
    }
)


def score_query_relevance(*, query: str, text: str, max_boost: float = 0.12) -> QueryRelevance:
    terms = query_terms(query)
    if not terms:
        return QueryRelevance(
            score_boost=0.0,
            query_term_count=0,
            unique_term_hits=0,
            capped_frequency_hits=0,
            hit_ratio=0.0,
        )
    counts = text_variant_counts(text)
    frequencies = tuple(query_term_frequency(term, counts) for term in terms)
    unique_hits = sum(1 for frequency in frequencies if frequency > 0)
    capped_frequency_hits = sum(min(frequency, 3) for frequency in frequencies)
    hit_ratio = unique_hits / len(terms)
    distinctive_terms = tuple(term for term in terms if _is_distinctive_term(term))
    distinctive_hits = sum(
        1
        for term in distinctive_terms
        if query_term_frequency(term, counts) > 0
    )
    phrase_bigram_count = max(0, len(terms) - 1)
    phrase_bigram_hits = _phrase_bigram_hits(
        terms=terms,
        text_variants=text_variant_sequence(text),
    )
    frequency_boost = min(0.025, capped_frequency_hits * 0.002)
    phrase_boost = _phrase_boost(
        hit_ratio=hit_ratio,
        phrase_bigram_hits=phrase_bigram_hits,
    )
    score_cap = max_boost + (0.02 if phrase_boost > 0 else 0.0)
    score_boost = min(
        score_cap,
        round(hit_ratio * max_boost + frequency_boost + phrase_boost, 4),
    )
    return QueryRelevance(
        score_boost=score_boost,
        query_term_count=len(terms),
        unique_term_hits=unique_hits,
        capped_frequency_hits=capped_frequency_hits,
        hit_ratio=round(hit_ratio, 4),
        distinctive_term_count=len(distinctive_terms),
        distinctive_term_hits=distinctive_hits,
        phrase_bigram_count=phrase_bigram_count,
        phrase_bigram_hits=phrase_bigram_hits,
        phrase_boost=phrase_boost,
    )


def is_query_relevance_sufficient(relevance: QueryRelevance) -> bool:
    if relevance.query_term_count <= 0:
        return True
    if relevance.unique_term_hits <= 0:
        return False
    return relevance.distinctive_term_count <= 0 or relevance.distinctive_term_hits > 0


def query_relevance_score_signals(relevance: QueryRelevance) -> dict[str, int | float]:
    return {
        "query_term_count": relevance.query_term_count,
        "unique_term_hits": relevance.unique_term_hits,
        "capped_frequency_hits": relevance.capped_frequency_hits,
        "hit_ratio": relevance.hit_ratio,
        "distinctive_term_count": relevance.distinctive_term_count,
        "distinctive_term_hits": relevance.distinctive_term_hits,
        "phrase_bigram_count": relevance.phrase_bigram_count,
        "phrase_bigram_hits": relevance.phrase_bigram_hits,
        "phrase_boost": relevance.phrase_boost,
        "query_relevance_boost": relevance.score_boost,
    }


def _is_distinctive_term(term: LexicalQueryTerm) -> bool:
    return not any(variant in _GENERIC_MEMORY_QUERY_TERMS for variant in term.variants)


def _phrase_bigram_hits(
    *,
    terms: tuple[LexicalQueryTerm, ...],
    text_variants: tuple[tuple[str, ...], ...],
) -> int:
    if len(terms) < 2 or len(text_variants) < 2:
        return 0
    text_variant_sets = tuple(set(variants) for variants in text_variants)
    hits = 0
    for left, right in zip(terms, terms[1:], strict=False):
        left_variants = set(left.variants)
        right_variants = set(right.variants)
        if any(
            left_variants.intersection(text_variant_sets[index])
            and right_variants.intersection(text_variant_sets[index + 1])
            for index in range(len(text_variant_sets) - 1)
        ):
            hits += 1
    return hits


def _phrase_boost(*, hit_ratio: float, phrase_bigram_hits: int) -> float:
    if hit_ratio <= 0.0 or hit_ratio >= 0.8 or phrase_bigram_hits <= 0:
        return 0.0
    return min(0.02, round(phrase_bigram_hits * 0.006, 4))
