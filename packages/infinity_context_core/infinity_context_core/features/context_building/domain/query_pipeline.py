"""Query normalization and expansion policy for context retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from infinity_context_core.features.context_building.domain.context import (
    ContextQuery,
)

DEFAULT_QUERY_STOP_WORDS: Final[tuple[str, ...]] = (
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "this",
    "to",
    "was",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
)
_TERM_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\w][\w:+./#-]*", re.UNICODE)


@dataclass(frozen=True, slots=True)
class NormalizedContextQuery:
    """Canonical query text and retrieval terms derived from a request."""

    original_query: ContextQuery
    normalized_query: ContextQuery
    terms: tuple[str, ...]
    normalized_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.normalized_query.text.strip():
            raise ValueError("Normalized context query requires text")


@dataclass(frozen=True, slots=True)
class ContextQueryVariant:
    """Search text variant produced by deterministic expansion rules."""

    text: str
    reason: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Context query variant requires text")
        if not self.reason.strip():
            raise ValueError("Context query variant requires a reason")
        if self.weight <= 0:
            raise ValueError("Context query variant weight must be positive")


@dataclass(frozen=True, slots=True)
class ContextQueryPlan:
    """Provider-independent retrieval query plan for candidate adapters."""

    original_query: ContextQuery
    normalized_query: ContextQuery
    terms: tuple[str, ...]
    variants: tuple[ContextQueryVariant, ...]
    normalized_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.variants:
            raise ValueError("Context query plan requires at least one variant")

    @property
    def search_texts(self) -> tuple[str, ...]:
        """Return variant text in adapter-consumable order."""

        return tuple(variant.text for variant in self.variants)


@dataclass(frozen=True, slots=True)
class ContextQueryNormalizationPolicy:
    """Normalize context requests without provider-specific query syntax."""

    max_query_chars: int = 512
    max_terms: int = 12
    min_term_chars: int = 2
    stop_words: tuple[str, ...] = DEFAULT_QUERY_STOP_WORDS

    def __post_init__(self) -> None:
        if self.max_query_chars < 1:
            raise ValueError("Max query chars must be positive")
        if self.max_terms < 1:
            raise ValueError("Max query terms must be positive")
        if self.min_term_chars < 1:
            raise ValueError("Minimum query term chars must be positive")

    def normalize(self, query: ContextQuery) -> NormalizedContextQuery:
        normalized_text = _normalize_text(query.text)
        if len(normalized_text) > self.max_query_chars:
            normalized_text = normalized_text[: self.max_query_chars].strip()
        if not normalized_text:
            raise ValueError("Context query text cannot be empty after normalization")

        normalized_tags = tuple(_dedupe(_normalize_label(tag) for tag in query.tags))
        terms = tuple(
            _dedupe(
                _term
                for _term in _extract_terms(
                    normalized_text,
                    normalized_tags,
                    min_chars=self.min_term_chars,
                    stop_words=self.stop_words,
                )
            )
        )[: self.max_terms]
        normalized_query = ContextQuery(
            scope=query.scope,
            text=normalized_text,
            intent=_normalize_label(query.intent) or "answer",
            as_of=query.as_of,
            tags=normalized_tags,
        )
        return NormalizedContextQuery(
            original_query=query,
            normalized_query=normalized_query,
            terms=terms,
            normalized_tags=normalized_tags,
        )


@dataclass(frozen=True, slots=True)
class ContextQueryExpansionPolicy:
    """Build deterministic query variants from normalized text, terms and tags."""

    normalization_policy: ContextQueryNormalizationPolicy = (
        ContextQueryNormalizationPolicy()
    )
    max_variants: int = 6
    max_terms_per_variant: int = 6
    include_tag_variants: bool = True

    def __post_init__(self) -> None:
        if self.max_variants < 1:
            raise ValueError("Max query variants must be positive")
        if self.max_terms_per_variant < 1:
            raise ValueError("Max terms per query variant must be positive")

    def plan(self, query: ContextQuery) -> ContextQueryPlan:
        normalized = self.normalization_policy.normalize(query)
        variants: list[ContextQueryVariant] = [
            ContextQueryVariant(
                text=normalized.normalized_query.text,
                reason="normalized_query",
                weight=1.0,
            )
        ]

        if normalized.terms:
            variants.append(
                ContextQueryVariant(
                    text=" ".join(normalized.terms[: self.max_terms_per_variant]),
                    reason="significant_terms",
                    weight=0.85,
                )
            )

        if self.include_tag_variants:
            for tag in normalized.normalized_tags:
                variants.append(
                    ContextQueryVariant(
                        text=tag,
                        reason="tag",
                        weight=0.6,
                    )
                )

        return ContextQueryPlan(
            original_query=query,
            normalized_query=normalized.normalized_query,
            terms=normalized.terms,
            variants=tuple(_dedupe_variants(variants))[: self.max_variants],
            normalized_tags=normalized.normalized_tags,
        )


def _normalize_text(text: str) -> str:
    without_control_chars = "".join(
        " " if character.isspace() else character
        for character in text
        if character.isprintable() or character.isspace()
    )
    return " ".join(without_control_chars.split())


def _normalize_label(value: str) -> str:
    folded = " ".join(value.casefold().split())
    normalized = re.sub(r"[^0-9a-z_.:/#-]+", "-", folded)
    return normalized.strip("-")


def _extract_terms(
    text: str,
    tags: tuple[str, ...],
    *,
    min_chars: int,
    stop_words: tuple[str, ...],
) -> tuple[str, ...]:
    stop_word_set = set(stop_words)
    source = " ".join((text.casefold(), *tags))
    terms = []
    for match in _TERM_PATTERN.finditer(source):
        term = match.group(0).strip("_-").casefold()
        if len(term) < min_chars:
            continue
        if term in stop_word_set:
            continue
        terms.append(term)
    return tuple(terms)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _dedupe_variants(
    variants: list[ContextQueryVariant],
) -> tuple[ContextQueryVariant, ...]:
    seen: set[str] = set()
    result: list[ContextQueryVariant] = []
    for variant in variants:
        key = variant.text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(variant)
    return tuple(result)


__all__ = (
    "ContextQueryExpansionPolicy",
    "ContextQueryNormalizationPolicy",
    "ContextQueryPlan",
    "ContextQueryVariant",
    "DEFAULT_QUERY_STOP_WORDS",
    "NormalizedContextQuery",
)
