"""Explainable canonical related-fact ranking."""

from __future__ import annotations

import re

from memo_stack_core.application.dto import RelatedFactItem
from memo_stack_core.domain.entities import MemoryFact, SourceRef

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]{3,}")
_MAX_TEXT_SCORE = 20.0


def rank_related_facts(
    *,
    target: MemoryFact,
    candidates: tuple[MemoryFact, ...],
    limit: int,
    include_other_threads: bool,
) -> tuple[RelatedFactItem, ...]:
    """Rank facts by explainable canonical evidence rather than opaque similarity."""

    related: list[RelatedFactItem] = []
    for candidate in candidates:
        if str(candidate.id) == str(target.id):
            continue
        if not _thread_visible(
            target=target,
            candidate=candidate,
            include_other_threads=include_other_threads,
        ):
            continue
        if candidate.classification == "restricted":
            continue
        score, reasons = _relation_score(target, candidate)
        if score <= 0:
            continue
        related.append(
            RelatedFactItem(
                fact=candidate,
                score=round(score, 3),
                relation_reasons=tuple(reasons),
            )
        )

    return tuple(
        sorted(
            related,
            key=lambda item: (item.score, item.fact.updated_at, str(item.fact.id)),
            reverse=True,
        )[:limit]
    )


def _thread_visible(
    *,
    target: MemoryFact,
    candidate: MemoryFact,
    include_other_threads: bool,
) -> bool:
    if include_other_threads:
        return True
    target_thread_id = str(target.thread_id) if target.thread_id else None
    candidate_thread_id = str(candidate.thread_id) if candidate.thread_id else None
    if target_thread_id is None:
        return candidate_thread_id is None
    return candidate_thread_id in {target_thread_id, None}


def _relation_score(target: MemoryFact, candidate: MemoryFact) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    source_score, source_reasons = _source_ref_score(target.source_refs, candidate.source_refs)
    score += source_score
    reasons.extend(source_reasons)

    if target.category and target.category == candidate.category:
        score += 18
        reasons.append("same_category")

    shared_tags = sorted(set(target.tags).intersection(candidate.tags))
    if shared_tags:
        score += min(30, len(shared_tags) * 10)
        reasons.append("shared_tags:" + ",".join(shared_tags[:5]))

    if target.kind == candidate.kind:
        score += 6
        reasons.append("same_kind")

    if target.thread_id and target.thread_id == candidate.thread_id:
        score += 6
        reasons.append("same_thread")
    elif candidate.thread_id is None:
        score += 4
        reasons.append("profile_wide")

    text_score = _text_overlap_score(target.text, candidate.text)
    if text_score > 0:
        score += text_score
        reasons.append("text_overlap")

    return score, reasons


def _source_ref_score(
    target_refs: tuple[SourceRef, ...],
    candidate_refs: tuple[SourceRef, ...],
) -> tuple[float, list[str]]:
    target_chunks = _source_keys(target_refs, include_chunk=True)
    candidate_chunks = _source_keys(candidate_refs, include_chunk=True)
    if target_chunks.intersection(candidate_chunks):
        return 90.0, ["shared_source_chunk"]

    target_sources = _source_keys(target_refs, include_chunk=False)
    candidate_sources = _source_keys(candidate_refs, include_chunk=False)
    if target_sources.intersection(candidate_sources):
        return 70.0, ["shared_source"]

    return 0.0, []


def _source_keys(refs: tuple[SourceRef, ...], *, include_chunk: bool) -> set[tuple[str, str, str]]:
    keys = set()
    for ref in refs:
        chunk = ref.chunk_id or ""
        if include_chunk and not chunk:
            continue
        keys.add((ref.source_type, ref.source_id, chunk if include_chunk else ""))
    return keys


def _text_overlap_score(left: str, right: str) -> float:
    left_terms = set(_TOKEN_PATTERN.findall(left.lower()))
    right_terms = set(_TOKEN_PATTERN.findall(right.lower()))
    if not left_terms or not right_terms:
        return 0.0
    overlap = left_terms.intersection(right_terms)
    if not overlap:
        return 0.0
    ratio = len(overlap) / max(len(left_terms), len(right_terms))
    if ratio < 0.08:
        return 0.0
    return min(_MAX_TEXT_SCORE, ratio * _MAX_TEXT_SCORE)
