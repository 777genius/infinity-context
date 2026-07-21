"""Shared helpers for Postgres repository implementations."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_counts,
)
from sqlalchemy import case, func, or_

from infinity_context_adapters.postgres.models import MemorySourceRefRow

_MAX_QUERY_TERMS = 24


def _terms(query: str) -> tuple[LexicalQueryTerm, ...]:
    terms: list[LexicalQueryTerm] = []
    for term in query_terms(query, max_terms=_MAX_QUERY_TERMS):
        variants = tuple(dict.fromkeys(variant for variant in term.variants if len(variant) >= 3))
        if variants:
            terms.append(LexicalQueryTerm(raw=term.raw, variants=variants))
    return tuple(terms)


def _score(text: str, terms: tuple[LexicalQueryTerm, ...]) -> int:
    counts = text_variant_counts(text)
    unique_hits = sum(1 for term in terms if query_term_frequency(term, counts) > 0)
    if unique_hits == 0:
        return 0
    density_penalty = len(text) // 800
    return unique_hits * 1000 - density_penalty


def _grouped_sql_matches(column, terms: tuple[LexicalQueryTerm, ...]):
    """Return one SQL predicate per raw term, with aliases ORed inside it."""
    return tuple(
        or_(*(column.contains(variant) for variant in term.variants))
        for term in terms
    )


def _grouped_sql_score(term_matches):
    """Count matched raw-term groups without counting their aliases separately."""
    return sum(case((match, 1), else_=0) for match in term_matches)


def _retrieval_candidate_limit(limit: int) -> int:
    if limit <= 0:
        return 0
    return min(max(limit * 20, limit, 200), 2000)


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _not_expired(model: type, now: datetime | None):
    comparable_now = now if now is not None else func.now()
    return or_(model.expires_at.is_(None), model.expires_at > comparable_now)


def _tags_match(
    values: list[str],
    *,
    tags_any: tuple[str, ...],
    tags_all: tuple[str, ...],
    tags_none: tuple[str, ...],
) -> bool:
    tags = set(values)
    return (
        (not tags_any or bool(tags.intersection(tags_any)))
        and (not tags_all or set(tags_all).issubset(tags))
        and (not tags_none or not tags.intersection(tags_none))
    )


def _source_ref_points_to_deleted_document(
    ref: MemorySourceRefRow,
    *,
    document_id: str,
    chunk_ids: set[str],
) -> bool:
    if ref.chunk_id is not None:
        return ref.chunk_id in chunk_ids
    return ref.source_type == "document" and ref.source_id == document_id


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"
