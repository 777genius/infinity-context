"""Bind-bounded ordered batching for canonical chunk and anchor reads."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from infinity_context_core.application.context_lexical import LexicalQueryTerm
from infinity_context_core.domain.entities import MemoryAnchor, MemoryChunk
from infinity_context_core.ports.repositories import (
    ActiveAnchorKey,
    AnchorScopeQuery,
    ChunkKeywordSearch,
)
from sqlalchemy import and_, literal_column, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.mappers import anchor_row_to_domain, chunk_row_to_domain
from infinity_context_adapters.postgres.models import MemoryAnchorRow, MemoryChunkRow
from infinity_context_adapters.postgres.repository_helpers import (
    _grouped_sql_matches,
    _grouped_sql_score,
    _retrieval_candidate_limit,
    _score,
    _terms,
)

# SQLite commonly permits 999 variables and asyncpg permits substantially more. Keeping every
# statement at 900 actual positional binds leaves headroom for dialect/compiler bookkeeping.
_MAX_SQL_BINDS = 900
_MAX_TERM_SLICE_BINDS = 400
_T = TypeVar("_T")


@dataclass(frozen=True)
class _TermSlice:
    score_key: int
    terms: tuple[LexicalQueryTerm, ...]

    @property
    def bind_count(self) -> int:
        # Every variant occurs in both the projected SQL score and WHERE predicate. CASE also
        # contributes its true/false result values for every raw-term group, and SQLAlchemy's
        # additive score starts with one bound zero value.
        return 1 + 2 * sum(len(term.variants) + 1 for term in self.terms)


@dataclass(frozen=True)
class _KeywordFragment:
    request_index: int
    scope_ids: tuple[str, ...]
    term_slice: _TermSlice | None
    bind_count: int


@dataclass
class _KeywordCandidate:
    row: MemoryChunkRow
    scores: dict[int, int] = field(default_factory=dict)


def _batches(values: Sequence[_T], size: int) -> tuple[Sequence[_T], ...]:
    return tuple(values[offset : offset + size] for offset in range(0, len(values), size))


def _packed_by_bind_count(
    values: Sequence[_T],
    bind_count,
) -> tuple[tuple[_T, ...], ...]:
    packs: list[tuple[_T, ...]] = []
    current: list[_T] = []
    current_binds = 0
    for value in values:
        value_binds = bind_count(value)
        if current and current_binds + value_binds > _MAX_SQL_BINDS:
            packs.append(tuple(current))
            current = []
            current_binds = 0
        current.append(value)
        current_binds += value_binds
    if current:
        packs.append(tuple(current))
    return tuple(packs)


async def get_anchor_ids(
    session: AsyncSession,
    anchor_ids: tuple[str, ...],
) -> list[MemoryAnchor]:
    """Load IDs in bounded statements and restore duplicates and input order."""
    if not anchor_ids:
        return []
    rows_by_id: dict[str, MemoryAnchorRow] = {}
    unique_ids = tuple(dict.fromkeys(anchor_ids))
    for batch in _batches(unique_ids, _MAX_SQL_BINDS):
        rows = (
            await session.execute(select(MemoryAnchorRow).where(MemoryAnchorRow.id.in_(batch)))
        ).scalars()
        rows_by_id.update((row.id, row) for row in rows)
    return [anchor_row_to_domain(rows_by_id[item]) for item in anchor_ids if item in rows_by_id]


async def find_active_anchor_keys(
    session: AsyncSession,
    requests: tuple[ActiveAnchorKey, ...],
) -> list[MemoryAnchor | None]:
    """Resolve ordered scoped keys without concurrent session operations."""
    if not requests:
        return []
    rows_by_key: dict[tuple[str, str, str, str], MemoryAnchorRow] = {}
    indexed = tuple(enumerate(requests))
    for pack in _packed_by_bind_count(indexed, lambda _item: 5):
        predicates = tuple(and_(*_active_anchor_key_conditions(request)) for _, request in pack)
        rows = (await session.execute(select(MemoryAnchorRow).where(or_(*predicates)))).scalars()
        rows_by_key.update((_anchor_key(row), row) for row in rows)
    return [
        anchor_row_to_domain(row) if (row := rows_by_key.get(_request_key(request))) else None
        for request in requests
    ]


async def list_anchor_scopes(
    session: AsyncSession,
    requests: tuple[AnchorScopeQuery, ...],
) -> list[list[MemoryAnchor]]:
    """List each logical scope exactly as its scalar query would."""
    if not requests:
        return []
    rows_by_request: list[dict[str, MemoryAnchorRow]] = [dict() for _ in requests]
    indexed = tuple(
        (index, request) for index, request in enumerate(requests) if request.limit != 0
    )
    for pack in _packed_by_bind_count(indexed, _anchor_scope_bind_count):
        predicates = tuple(and_(*_anchor_scope_conditions(request)) for _, request in pack)
        rows = list(
            (await session.execute(select(MemoryAnchorRow).where(or_(*predicates)))).scalars()
        )
        for index, request in pack:
            rows_by_request[index].update(
                (row.id, row) for row in rows if _anchor_matches_scope(row, request)
            )
    results: list[list[MemoryAnchor]] = []
    for request, rows_by_id in zip(requests, rows_by_request, strict=True):
        rows = sorted(
            rows_by_id.values(),
            key=lambda row: (row.updated_at, row.id),
            reverse=True,
        )
        if request.limit >= 0:
            rows = rows[: request.limit]
        results.append([anchor_row_to_domain(row) for row in rows])
    return results


def _active_anchor_key_conditions(request: ActiveAnchorKey):
    return (
        MemoryAnchorRow.space_id == request.space_id,
        MemoryAnchorRow.memory_scope_id == request.memory_scope_id,
        MemoryAnchorRow.kind == request.kind,
        MemoryAnchorRow.normalized_key == request.normalized_key,
        MemoryAnchorRow.status == "active",
    )


def _anchor_scope_conditions(request: AnchorScopeQuery):
    conditions = [
        MemoryAnchorRow.space_id == request.space_id,
        MemoryAnchorRow.memory_scope_id == request.memory_scope_id,
    ]
    if request.kind:
        conditions.append(MemoryAnchorRow.kind == request.kind)
    if request.status:
        conditions.append(MemoryAnchorRow.status == request.status)
    return tuple(conditions)


def _anchor_scope_bind_count(item: tuple[int, AnchorScopeQuery]) -> int:
    request = item[1]
    return 2 + int(bool(request.kind)) + int(bool(request.status))


def _anchor_matches_scope(row: MemoryAnchorRow, request: AnchorScopeQuery) -> bool:
    return (
        row.space_id == request.space_id
        and row.memory_scope_id == request.memory_scope_id
        and (not request.kind or row.kind == request.kind)
        and (not request.status or row.status == request.status)
    )


def _anchor_key(row: MemoryAnchorRow) -> tuple[str, str, str, str]:
    return (row.space_id, row.memory_scope_id, row.kind, row.normalized_key)


def _request_key(request: ActiveAnchorKey) -> tuple[str, str, str, str]:
    return (request.space_id, request.memory_scope_id, request.kind, request.normalized_key)


async def keyword_search_many(
    session: AsyncSession,
    requests: tuple[ChunkKeywordSearch, ...],
) -> list[list[MemoryChunk]]:
    """Search in bind-bounded UNION packs and merge each request without ranking drift."""
    if not requests:
        return []
    terms_by_request = tuple(_terms(request.query) for request in requests)
    fragments = tuple(
        fragment
        for index, (request, terms) in enumerate(zip(requests, terms_by_request, strict=True))
        for fragment in _keyword_fragments(index, request, terms)
    )
    candidates: list[dict[str, _KeywordCandidate]] = [dict() for _ in requests]
    for pack in _packed_by_bind_count(fragments, lambda fragment: fragment.bind_count):
        statement = _keyword_batch_statement(pack, requests)
        rows = await session.execute(statement)
        for row, request_index, score_key, lexical_score in rows:
            candidate = candidates[request_index].setdefault(row.id, _KeywordCandidate(row=row))
            if score_key >= 0:
                previous = candidate.scores.get(score_key, 0)
                candidate.scores[score_key] = max(previous, int(lexical_score))
    return [
        _rank_keyword_candidates(request, terms, tuple(by_id.values()))
        for request, terms, by_id in zip(requests, terms_by_request, candidates, strict=True)
    ]


def _keyword_fragments(
    request_index: int,
    request: ChunkKeywordSearch,
    terms: tuple[LexicalQueryTerm, ...],
) -> tuple[_KeywordFragment, ...]:
    scope_ids = tuple(dict.fromkeys(request.memory_scope_ids))
    if request.limit <= 0 or not scope_ids:
        return ()
    fixed_binds = 3 + int(request.thread_id is not None)
    slices: tuple[_TermSlice | None, ...] = _term_slices(terms) if terms else (None,)
    fragments: list[_KeywordFragment] = []
    for term_slice in slices:
        term_binds = term_slice.bind_count if term_slice is not None else 0
        scopes_per_fragment = _MAX_SQL_BINDS - fixed_binds - term_binds
        if scopes_per_fragment < 1:
            msg = "One lexical term group exceeds the canonical retrieval SQL bind budget"
            raise ValueError(msg)
        for scope_batch in _batches(scope_ids, scopes_per_fragment):
            fragments.append(
                _KeywordFragment(
                    request_index=request_index,
                    scope_ids=tuple(scope_batch),
                    term_slice=term_slice,
                    bind_count=fixed_binds + len(scope_batch) + term_binds,
                )
            )
    return tuple(fragments)


def _term_slices(terms: tuple[LexicalQueryTerm, ...]) -> tuple[_TermSlice, ...]:
    slices: list[_TermSlice] = []
    current: list[LexicalQueryTerm] = []
    current_binds = 0
    score_key = 0
    for term in terms:
        term_binds = 2 * (len(term.variants) + 1)
        if 1 + term_binds > _MAX_TERM_SLICE_BINDS:
            if current:
                slices.append(_TermSlice(score_key=score_key, terms=tuple(current)))
                score_key += 1
                current = []
                current_binds = 0
            variants_per_slice = max(1, ((_MAX_TERM_SLICE_BINDS - 1) // 2) - 1)
            for variants in _batches(term.variants, variants_per_slice):
                slices.append(
                    _TermSlice(
                        score_key=score_key,
                        terms=(LexicalQueryTerm(raw=term.raw, variants=tuple(variants)),),
                    )
                )
            score_key += 1
            continue
        if current and 1 + current_binds + term_binds > _MAX_TERM_SLICE_BINDS:
            slices.append(_TermSlice(score_key=score_key, terms=tuple(current)))
            score_key += 1
            current = []
            current_binds = 0
        current.append(term)
        current_binds += term_binds
    if current:
        slices.append(_TermSlice(score_key=score_key, terms=tuple(current)))
    return tuple(slices)


def _keyword_batch_statement(
    fragments: tuple[_KeywordFragment, ...],
    requests: tuple[ChunkKeywordSearch, ...],
):
    selects = tuple(
        _keyword_fragment_select(fragment, requests[fragment.request_index])
        for fragment in fragments
    )
    membership = (selects[0] if len(selects) == 1 else union_all(*selects)).subquery(
        "canonical_keyword_candidates"
    )
    return select(
        MemoryChunkRow,
        membership.c.request_index,
        membership.c.score_key,
        membership.c.lexical_score,
    ).join(membership, membership.c.chunk_id == MemoryChunkRow.id)


def _keyword_fragment_select(fragment: _KeywordFragment, request: ChunkKeywordSearch):
    conditions = list(_chunk_conditions(request, fragment.scope_ids))
    if fragment.term_slice is None:
        score_key = -1
        lexical_score = literal_column("0")
    else:
        score_key = fragment.term_slice.score_key
        term_matches = _grouped_sql_matches(
            MemoryChunkRow.normalized_text,
            fragment.term_slice.terms,
        )
        lexical_score = _grouped_sql_score(term_matches)
        conditions.append(or_(*term_matches))
    return select(
        literal_column(str(fragment.request_index)).label("request_index"),
        literal_column(str(score_key)).label("score_key"),
        MemoryChunkRow.id.label("chunk_id"),
        lexical_score.label("lexical_score"),
    ).where(*conditions)


def _chunk_conditions(request: ChunkKeywordSearch, scope_ids: tuple[str, ...]):
    conditions = [
        MemoryChunkRow.space_id == request.space_id,
        MemoryChunkRow.memory_scope_id.in_(scope_ids),
        MemoryChunkRow.status == "active",
        MemoryChunkRow.classification != "restricted",
    ]
    if request.thread_id is not None:
        conditions.append(
            or_(MemoryChunkRow.thread_id == request.thread_id, MemoryChunkRow.thread_id.is_(None))
        )
    return tuple(conditions)


def _rank_keyword_candidates(
    request: ChunkKeywordSearch,
    terms: tuple[LexicalQueryTerm, ...],
    candidates: tuple[_KeywordCandidate, ...],
) -> list[MemoryChunk]:
    if request.limit <= 0:
        return []
    if terms:
        ranked = sorted(
            candidates,
            key=lambda item: (
                -sum(item.scores.values()),
                item.row.sequence,
                item.row.created_at,
                item.row.id,
            ),
        )[: _retrieval_candidate_limit(request.limit)]
        rescored = [
            (score, index, item.row)
            for index, item in enumerate(ranked)
            for score in (_score(item.row.normalized_text, terms),)
            if score > 0
        ]
        rescored.sort(key=lambda item: (-item[0], item[1]))
        rows = [row for _, _, row in rescored]
    else:
        rows = [
            item.row
            for item in sorted(
                candidates,
                key=lambda item: (item.row.created_at, item.row.id),
                reverse=True,
            )[: _retrieval_candidate_limit(request.limit)]
        ]
    return [chunk_row_to_domain(row) for row in rows[: request.limit]]


__all__ = [
    "find_active_anchor_keys",
    "get_anchor_ids",
    "keyword_search_many",
    "list_anchor_scopes",
]
