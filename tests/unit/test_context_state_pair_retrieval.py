from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_ranking import (
    dedupe_rank_items as real_dedupe_rank_items,
)
from infinity_context_core.application.dto import BuildContextQuery, ConsistencyMode, ContextItem
from infinity_context_core.application.use_cases import build_context as build_context_module
from infinity_context_core.application.use_cases.build_context import BuildContextUseCase
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryScopeId,
    SpaceId,
)

_BEFORE_SOURCE = "role-history:before"
_NOW_SOURCE = "role-history:now"


def test_distinct_before_and_now_sources_reach_dedup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _chunk(
        "before-role-state",
        "Taylor: I had just started the role and led a team of 4 engineers.",
        source_external_id=_BEFORE_SOURCE,
    )
    now = _chunk(
        "now-role-state",
        "Taylor: I now lead a team of five engineers.",
        source_external_id=_NOW_SOURCE,
    )
    dedupe_calls: list[tuple[tuple[ContextItem, ...], tuple[ContextItem, ...]]] = []
    use_case = BuildContextUseCase(
        uow_factory=lambda: None,  # type: ignore[arg-type,return-value]
        ids=_Ids(),  # type: ignore[arg-type]
        vector_index=object(),  # type: ignore[arg-type]
        graph_index=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        packer=ContextPacker(),
    )
    use_case._canonical_collector = _CanonicalCollector((before, now))  # type: ignore[assignment]
    use_case._hydrator = _Hydrator()  # type: ignore[assignment]
    use_case._artifact_evidence_collector = _ArtifactCollector()  # type: ignore[assignment]
    use_case._context_link_expander = _LinkExpander()  # type: ignore[assignment]

    async def empty_selection(**_kwargs: object) -> tuple[tuple[object, ...], dict[str, object]]:
        return (), {}

    async def empty_items(**_kwargs: object) -> tuple[object, ...]:
        return ()

    async def temporal_passthrough(
        *, items: tuple[ContextItem, ...], **_kwargs: object
    ) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
        return items, {}

    def recording_dedupe(items: tuple[ContextItem, ...]) -> tuple[ContextItem, ...]:
        output = real_dedupe_rank_items(items)
        dedupe_calls.append((items, output))
        return output

    monkeypatch.setattr(build_context_module, "_aggregation_admission_seed_chunks", empty_selection)
    monkeypatch.setattr(build_context_module, "_keyword_neighbor_chunk_items", empty_selection)
    monkeypatch.setattr(
        build_context_module, "_keyword_source_sibling_chunk_items", empty_selection
    )
    monkeypatch.setattr(build_context_module, "_exact_source_ref_hydration_items", empty_selection)
    monkeypatch.setattr(build_context_module, "_pending_conflict_items", empty_items)
    monkeypatch.setattr(
        build_context_module,
        "_apply_temporal_relation_signals",
        temporal_passthrough,
    )
    monkeypatch.setattr(build_context_module, "dedupe_rank_items", recording_dedupe)

    asyncio.run(use_case.execute(_query()))

    first_input, first_output = dedupe_calls[0]
    assert _source_ids(first_input) == {_BEFORE_SOURCE, _NOW_SOURCE}
    assert _source_ids(first_output) == {_BEFORE_SOURCE, _NOW_SOURCE}
    assert _has_two_distinct_state_sources(first_input) is True
    assert _has_two_distinct_state_sources(first_output) is True

    before_item = next(item for item in first_output if _BEFORE_SOURCE in _source_ids((item,)))
    now_item = next(item for item in first_output if _NOW_SOURCE in _source_ids((item,)))
    mirrored_before = replace(before_item, source_refs=now_item.source_refs)

    assert _has_two_distinct_state_sources((mirrored_before, now_item)) is False


def _has_two_distinct_state_sources(items: tuple[ContextItem, ...]) -> bool:
    before_sources = {
        source_id
        for item in items
        if "4 engineers" in item.text.casefold()
        for source_id in _source_ids((item,))
    }
    now_sources = {
        source_id
        for item in items
        if "five engineers" in item.text.casefold()
        for source_id in _source_ids((item,))
    }
    return bool(before_sources and now_sources and before_sources.isdisjoint(now_sources))


def _source_ids(items: tuple[ContextItem, ...]) -> set[str]:
    return {str(ref.source_id) for item in items for ref in item.source_refs}


class _CanonicalCollector:
    def __init__(self, chunks: tuple[MemoryChunk, ...]) -> None:
        self._chunks = chunks

    async def collect(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            facts=(),
            anchors=(),
            keyword_chunks=self._chunks,
            keyword_query_count=1,
            keyword_query_reasons=("original_query",),
            anchor_lookup_keys_considered=0,
            anchors_loaded_by_lookup=0,
        )


class _Hydrator:
    async def revalidate_visible_items(
        self,
        items: tuple[ContextItem, ...],
        **_kwargs: object,
    ) -> tuple[ContextItem, ...]:
        return items


class _ArtifactCollector:
    async def collect(self, **_kwargs: object) -> tuple[object, ...]:
        return ()


class _LinkExpander:
    async def collect(
        self,
        *,
        items: tuple[ContextItem, ...],
        **_kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(items=items, diagnostics={})


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_role_state"


def _query() -> BuildContextQuery:
    return BuildContextQuery(
        space_id=SpaceId("space-role-state"),
        memory_scope_ids=(MemoryScopeId("scope-role-state"),),
        query=(
            "How many engineers do I lead when I just started my new role as "
            "Senior Software Engineer? How many engineers do I lead now?"
        ),
        max_chunks=10,
        token_budget=512,
        consistency_mode=ConsistencyMode.CANONICAL_ONLY,
    )


def _chunk(chunk_id: str, text: str, *, source_external_id: str) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryChunk.create(
        chunk_id=MemoryChunkId(chunk_id),
        space_id=SpaceId("space-role-state"),
        memory_scope_id=MemoryScopeId("scope-role-state"),
        document_id=MemoryDocumentId(f"{chunk_id}-document"),
        source_type="document",
        source_external_id=source_external_id,
        source_hash=f"{chunk_id}-hash",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        sequence=1,
        char_start=0,
        char_end=len(text),
        token_estimate=max(1, len(text.split())),
        now=now,
    )
