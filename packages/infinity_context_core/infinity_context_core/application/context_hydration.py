"""Hydrate derived candidates through canonical repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from infinity_context_core.application.context_media_time import enrich_context_item_with_media_time
from infinity_context_core.application.context_policy import (
    is_context_anchor_visible,
    is_context_fact_visible,
    is_graph_fact_visible,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.context_source_sibling_evidence_rules import (
    _is_activity_event_duration_source_sibling_strong,
)
from infinity_context_core.application.context_source_siblings import (
    is_direct_source_sibling_obligation_evidence,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.source_refs import chunk_source_refs
from infinity_context_core.domain.entities import MemoryChunk, SourceRef
from infinity_context_core.features.memory_facts.public import (
    FactCurrentnessPolicy,
    FactTemporalQueryMode,
    MemoryFactSelectionPort,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_PREFOCUSED_CHUNK_EVIDENCE_SOURCES = frozenset(
    {
        "keyword_aggregation_chunks",
        "keyword_source_sibling_chunks",
    }
)


class ContextHydrator:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort | None = None,
        fact_selection: MemoryFactSelectionPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._fact_selection = fact_selection

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[MemoryChunk, ...]:
        if not chunk_ids:
            return ()
        async with self._uow_factory() as uow:
            chunks = await uow.chunks.hydrate_visible_chunks(
                chunk_ids=chunk_ids,
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
            )
        return tuple(chunks)

    async def hydrate_graph_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        if not fact_ids:
            return (), 0
        if self._fact_selection is not None:
            facts_by_id = await self._canonical_visible_facts(
                fact_ids=fact_ids,
                query=query,
                memory_scope_ids=memory_scope_ids,
            )
            hydrated = tuple(
                _canonical_fact_item(
                    fact,
                    query=query,
                    reference_time=self._reference_time(query),
                    score=0.78,
                    diagnostics={
                        "memory_scope_id": fact.identity.scope.memory_scope_id,
                        "retrieval_source": "graph_hydrated",
                        "retrieval_sources": ["graph_hydrated"],
                        "canonical_hydration": True,
                    },
                )
                for fact_id in fact_ids
                if (fact := facts_by_id.get(fact_id)) is not None
            )
            return hydrated, len(fact_ids) - len(hydrated)
        async with self._uow_factory() as uow:
            hydrated: list[ContextItem] = []
            stale_count = 0
            now = self._clock.now() if self._clock is not None else None
            facts_by_id = {str(fact.id): fact for fact in await uow.facts.get_by_ids(fact_ids)}
            for fact_id in fact_ids:
                fact = facts_by_id.get(fact_id)
                if fact is not None and is_graph_fact_visible(
                    fact,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                    now=now,
                ):
                    snippet = query_focused_snippet(query=query.query, text=fact.text)
                    hydrated.append(
                        enrich_context_item_with_media_time(
                            ContextItem(
                                item_id=str(fact.id),
                                item_type="fact",
                                text=fact.text,
                                score=0.78,
                                source_refs=source_refs_with_query_snippet(
                                    fact.source_refs,
                                    snippet,
                                ),
                                diagnostics={
                                    "memory_scope_id": str(fact.memory_scope_id),
                                    "retrieval_source": "graph_hydrated",
                                    "retrieval_sources": ["graph_hydrated"],
                                    "ranking_reason": (
                                        "graph candidate resolved to visible active fact"
                                    ),
                                    "score_signals": {
                                        "base_score": 0.78,
                                        "retrieval_channel": "graph_hydrated",
                                        "fact_status": fact.status.value,
                                        **query_snippet_score_signals(snippet),
                                    },
                                    "provenance": {
                                        "retrieval_sources": ["graph_hydrated"],
                                        "source_ref_count": len(fact.source_refs),
                                        "fact_status": fact.status.value,
                                        "fact_version": fact.version,
                                        **query_snippet_diagnostics(snippet),
                                    },
                                    **query_snippet_diagnostics(snippet),
                                },
                            ),
                            query_text=query.query,
                        )
                    )
                else:
                    stale_count += 1
        return tuple(hydrated), stale_count

    async def revalidate_visible_items(
        self,
        items: tuple[ContextItem, ...],
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[ContextItem, ...]:
        if not items:
            return ()

        chunk_ids = tuple(
            dict.fromkeys(item.item_id for item in items if item.item_type == "chunk")
        )
        visible_chunks = {
            str(chunk.id): chunk
            for chunk in await self.hydrate_visible_chunks(
                chunk_ids=chunk_ids,
                query=query,
                memory_scope_ids=memory_scope_ids,
            )
        }
        fact_ids = tuple(dict.fromkeys(item.item_id for item in items if item.item_type == "fact"))
        review_fact_statuses = {
            item.item_id: status
            for item in items
            if item.item_type == "fact" and (status := _review_fact_status(item)) is not None
        }
        visible_facts = {}
        if fact_ids:
            if self._fact_selection is not None:
                visible_facts = await self._canonical_visible_facts(
                    fact_ids=fact_ids,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                    review_fact_statuses=review_fact_statuses,
                )
            else:
                async with self._uow_factory() as uow:
                    now = self._clock.now() if self._clock is not None else None
                    for fact in await uow.facts.get_by_ids(fact_ids):
                        if is_context_fact_visible(
                            fact,
                            query=query,
                            memory_scope_ids=memory_scope_ids,
                            now=now,
                        ):
                            visible_facts[str(fact.id)] = fact
        anchor_ids = tuple(
            dict.fromkeys(item.item_id for item in items if item.item_type == "anchor")
        )
        visible_anchors = {}
        if anchor_ids:
            async with self._uow_factory() as uow:
                now = self._clock.now() if self._clock is not None else None
                if hasattr(uow.anchors, "get_by_ids"):
                    anchors = await uow.anchors.get_by_ids(anchor_ids)
                else:
                    anchors = []
                    for anchor_id in anchor_ids:
                        anchor = await uow.anchors.get_by_id(anchor_id)
                        if anchor is not None:
                            anchors.append(anchor)
                for anchor in anchors:
                    if is_context_anchor_visible(
                        anchor,
                        query=query,
                        memory_scope_ids=memory_scope_ids,
                        now=now,
                    ):
                        visible_anchors[str(anchor.id)] = anchor

        visible_items: list[ContextItem] = []
        for item in items:
            if item.item_type == "fact":
                fact = visible_facts.get(item.item_id)
                if fact is None:
                    continue
                if isinstance(fact, MemoryFactSnapshot):
                    visible_items.append(
                        _canonical_fact_item(
                            fact,
                            query=query,
                            reference_time=self._reference_time(query),
                            score=item.score,
                            diagnostics={
                                **(item.diagnostics or {}),
                                "canonical_hydration": True,
                            },
                        )
                    )
                    continue
                snippet = query_focused_snippet(query=query.query, text=fact.text)
                visible_items.append(
                    enrich_context_item_with_media_time(
                        ContextItem(
                            item_id=str(fact.id),
                            item_type=item.item_type,
                            text=fact.text,
                            score=item.score,
                            source_refs=source_refs_with_query_snippet(
                                fact.source_refs,
                                snippet,
                            ),
                            is_instruction=item.is_instruction,
                            diagnostics=item.diagnostics,
                        ),
                        query_text=query.query,
                    )
                )
            elif item.item_type == "anchor":
                anchor = visible_anchors.get(item.item_id)
                if anchor is None:
                    continue
                visible_items.append(
                    ContextItem(
                        item_id=str(anchor.id),
                        item_type=item.item_type,
                        text=item.text,
                        score=item.score,
                        source_refs=anchor.evidence_refs,
                        is_instruction=item.is_instruction,
                        diagnostics=item.diagnostics,
                    )
                )
            elif item.item_type == "chunk":
                chunk = visible_chunks.get(item.item_id)
                if chunk is None:
                    continue
                chunk_text = document_chunk_retrieval_text(
                    text=chunk.text,
                    metadata=chunk.metadata,
                )
                preserve_existing_evidence = _should_preserve_chunk_item_evidence(item)
                snippet = (
                    None
                    if preserve_existing_evidence
                    else query_focused_snippet(query=query.query, text=chunk_text)
                )
                if preserve_existing_evidence and item.text.strip():
                    evidence_text = item.text
                elif snippet is not None:
                    evidence_text = snippet.text
                else:
                    evidence_text = chunk_text
                visible_items.append(
                    enrich_context_item_with_media_time(
                        _with_application_evidence_contract(
                            ContextItem(
                                item_id=str(chunk.id),
                                item_type=item.item_type,
                                text=evidence_text,
                                score=item.score,
                                source_refs=source_refs_with_query_snippet(
                                    item.source_refs
                                    if preserve_existing_evidence and item.source_refs
                                    else chunk_source_refs(
                                        chunk,
                                        text_preview=snippet.text if snippet else chunk_text,
                                    ),
                                    snippet,
                                    include_char_range=True,
                                ),
                                is_instruction=item.is_instruction,
                                diagnostics=item.diagnostics,
                            ),
                            query_text=query.query,
                        ),
                        query_text=query.query,
                    )
                )
        return tuple(visible_items)

    async def _canonical_visible_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        review_fact_statuses: dict[str, str] | None = None,
    ) -> dict[str, MemoryFactSnapshot]:
        if self._fact_selection is None:
            return {}
        reference_time = self._reference_time(query)
        review_statuses = review_fact_statuses or {}
        review_ids = tuple(fact_id for fact_id in fact_ids if fact_id in review_statuses)
        normal_ids = tuple(fact_id for fact_id in fact_ids if fact_id not in review_statuses)
        visible: dict[str, MemoryFactSnapshot] = {}
        if normal_ids:
            mode = (
                FactTemporalQueryMode.AS_OF
                if query.as_of is not None
                else FactTemporalQueryMode.CURRENT
            )
            facts = await self._select_facts(
                fact_ids=normal_ids,
                query=query,
                memory_scope_ids=memory_scope_ids,
                temporal_mode=mode,
                reference_time=reference_time,
            )
            visible.update((fact.identity.fact_id, fact) for fact in facts)
        if review_ids:
            review_facts = await self._select_facts(
                fact_ids=review_ids,
                query=query,
                memory_scope_ids=memory_scope_ids,
                temporal_mode=FactTemporalQueryMode.HISTORY,
                reference_time=reference_time,
            )
            visible.update(
                (fact.identity.fact_id, fact)
                for fact in review_facts
                if fact.visibility.status == review_statuses[fact.identity.fact_id]
            )
        return visible

    async def _select_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        temporal_mode: FactTemporalQueryMode,
        reference_time: datetime,
    ) -> tuple[MemoryFactSnapshot, ...]:
        if self._fact_selection is None:
            return ()
        return await self._fact_selection.find_eligible(
            MemoryFactSelectionQuery(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                repository_id=query.repository_id,
                code_scope_id=query.code_scope_id,
                temporal_mode=temporal_mode,
                reference_time=reference_time,
                fact_ids=fact_ids,
                limit=len(fact_ids),
            )
        )

    def _reference_time(self, query: BuildContextQuery) -> datetime:
        return query.as_of or (self._clock.now() if self._clock is not None else datetime.now(UTC))


def _canonical_fact_item(
    fact: MemoryFactSnapshot,
    *,
    query: BuildContextQuery,
    reference_time: datetime,
    score: float,
    diagnostics: dict[str, object],
) -> ContextItem:
    source_refs = tuple(
        SourceRef(
            source_type=ref.source_type,
            source_id=ref.source_id,
            chunk_id=ref.chunk_id,
            char_start=ref.char_start,
            char_end=ref.char_end,
            quote_preview=ref.quote_preview,
            page_number=ref.page_number,
            time_start_ms=ref.time_start_ms,
            time_end_ms=ref.time_end_ms,
            bbox=ref.bbox,
        )
        for ref in fact.source_refs
    )
    snippet = query_focused_snippet(query=query.query, text=fact.text)
    temporal = fact.temporal_extent
    currentness = (
        FactCurrentnessPolicy().assess(
            temporal,
            reference_time=reference_time,
            freshness=fact.freshness,
        )
        if temporal is not None
        else None
    )
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=fact.identity.fact_id,
            item_type="fact",
            text=snippet.text if snippet is not None else fact.text,
            score=score,
            source_refs=source_refs_with_query_snippet(source_refs, snippet),
            diagnostics={
                **diagnostics,
                "fact_status": fact.visibility.status,
                "fact_version": fact.visibility.version,
                "temporal_currentness": (
                    currentness.state.value if currentness is not None else "unknown"
                ),
                "temporal_assurance": (
                    currentness.assurance.value if currentness is not None else "unknown"
                ),
                "temporal_reason_codes": (
                    list(currentness.reason_codes) if currentness is not None else ["unknown"]
                ),
                "temporal_kind": temporal.kind.value if temporal is not None else None,
                "observed_at": temporal.observed_at.isoformat() if temporal is not None else None,
                "valid_from": (
                    temporal.valid_from.isoformat()
                    if temporal is not None and temporal.valid_from is not None
                    else None
                ),
                "valid_to": (
                    temporal.valid_to.isoformat()
                    if temporal is not None and temporal.valid_to is not None
                    else None
                ),
                "last_confirmed_at": _confirmation_visible_at(
                    fact.freshness.last_confirmed_at,
                    reference_time=reference_time,
                ),
            },
        ),
        query_text=query.query,
    )


def _confirmation_visible_at(
    confirmed_at: datetime | None,
    *,
    reference_time: datetime,
) -> str | None:
    if confirmed_at is None or confirmed_at > reference_time:
        return None
    return confirmed_at.isoformat()


def _review_fact_status(item: ContextItem) -> str | None:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
    if diagnostics.get("review_only") is not True:
        return None
    retrieval_source = diagnostics.get("retrieval_source")
    if retrieval_source == "superseded_review":
        return "superseded"
    if retrieval_source == "disputed_review":
        return "disputed"
    return None


def _should_preserve_chunk_item_evidence(item: ContextItem) -> bool:
    """Keep bounded application evidence projections while revalidating canonicals."""

    diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
    retrieval_sources = diagnostics.get("retrieval_sources")
    if isinstance(retrieval_sources, (list, tuple)) and any(
        source in _PREFOCUSED_CHUNK_EVIDENCE_SOURCES for source in retrieval_sources
    ):
        return True
    return diagnostics.get("retrieval_source") in _PREFOCUSED_CHUNK_EVIDENCE_SOURCES


def _with_application_evidence_contract(
    item: ContextItem,
    *,
    query_text: str,
) -> ContextItem:
    """Materialize a bounded direct-evidence contract before final ranking."""

    diagnostics = dict(item.diagnostics or {})
    raw_signals = diagnostics.get("score_signals")
    signals = dict(raw_signals) if isinstance(raw_signals, dict) else {}
    if not _positive_signal(signals.get("source_sibling_answer_evidence")):
        return item
    expansion_reason = str(signals.get("query_expansion_reason") or "")
    direct_duration = (
        expansion_reason == "decomposition_activity_duration"
        and _is_activity_event_duration_source_sibling_strong(
            expansion_query=query_text,
            text=item.text,
        )
    )
    direct_obligation = is_direct_source_sibling_obligation_evidence(
        query_text=query_text,
        text=item.text,
    )
    signals.pop("application_evidence_contract_tier", None)
    if expansion_reason == "decomposition_activity_duration" and not direct_duration:
        diagnostics["score_signals"] = signals
        return replace(item, diagnostics=diagnostics)
    if not direct_duration and not direct_obligation:
        diagnostics["score_signals"] = signals
        return replace(item, diagnostics=diagnostics)
    diagnostics["score_signals"] = {
        "application_evidence_contract_tier": 1,
        **signals,
    }
    return replace(item, diagnostics=diagnostics)


def _positive_signal(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0
