"""Provider-independent candidate query planning and rank fusion."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CandidateQueryPolicy:
    """Explicit selection and fusion policy for one candidate query."""

    weight: float
    max_rank: int
    protected_head_count: int


@dataclass(frozen=True, slots=True)
class CandidateQuery:
    """A provider-independent query with an opaque compatibility key."""

    query: str
    key: str
    selection_priority: int
    policy: CandidateQueryPolicy


@dataclass(frozen=True, slots=True)
class CandidateRanking:
    """Ranked candidate keys returned for one planned query."""

    ranked_keys: tuple[str, ...]
    policy: CandidateQueryPolicy


def select_candidate_queries(
    queries: tuple[CandidateQuery, ...],
    *,
    fallback: CandidateQuery,
    limit: int,
) -> tuple[CandidateQuery, ...]:
    """Select stable, normalized, case-insensitively deduplicated queries."""

    ranked_queries = sorted(
        enumerate(queries),
        key=lambda item: (item[1].selection_priority, item[0]),
    )
    selected: list[CandidateQuery] = []
    seen: set[str] = set()
    for _, raw_query in ranked_queries:
        query_text = " ".join(raw_query.query.split())
        dedupe_key = query_text.casefold()
        if not query_text or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        selected.append(
            CandidateQuery(
                query=query_text,
                key=raw_query.key,
                selection_priority=raw_query.selection_priority,
                policy=raw_query.policy,
            )
        )
        if len(selected) >= limit:
            break
    if selected:
        return tuple(selected)
    return (fallback,)


def protected_candidate_head_keys(
    rankings: tuple[CandidateRanking, ...],
) -> tuple[str, ...]:
    """Keep the configured number of unique heads from each query ranking."""

    protected: list[str] = []
    seen: set[str] = set()
    for ranking in rankings:
        if ranking.policy.protected_head_count <= 0:
            continue
        head_count = 0
        for raw_key in ranking.ranked_keys:
            key = raw_key.strip()
            if key and key not in seen:
                seen.add(key)
                protected.append(key)
                head_count += 1
                if head_count >= ranking.policy.protected_head_count:
                    break
    return tuple(protected)


def fuse_ranked_candidate_keys(
    rankings: tuple[CandidateRanking, ...],
    *,
    limit: int,
    rank_constant: float,
) -> tuple[str, ...]:
    """Apply deterministic weighted reciprocal-rank fusion."""

    if limit <= 0:
        return ()
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    sequence = 0
    for ranking in rankings:
        seen_in_ranking: set[str] = set()
        for rank, raw_key in enumerate(ranking.ranked_keys, start=1):
            if rank > ranking.policy.max_rank:
                break
            key = raw_key.strip()
            if not key or key in seen_in_ranking:
                continue
            seen_in_ranking.add(key)
            if key not in first_seen:
                first_seen[key] = sequence
                sequence += 1
            scores[key] = scores.get(key, 0.0) + ranking.policy.weight / (
                rank_constant + rank
            )
    return tuple(
        key
        for key, _ in sorted(
            scores.items(),
            key=lambda item: (-item[1], first_seen[item[0]], item[0]),
        )[:limit]
    )


__all__ = (
    "CandidateQuery",
    "CandidateQueryPolicy",
    "CandidateRanking",
    "fuse_ranked_candidate_keys",
    "protected_candidate_head_keys",
    "select_candidate_queries",
)
