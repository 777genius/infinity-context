"""Context candidate collectors."""

from __future__ import annotations

from dataclasses import dataclass

from memo_stack_core.application.context_hydration import ContextHydrator
from memo_stack_core.application.document_text import document_chunk_retrieval_text
from memo_stack_core.application.dto import BuildContextQuery, ContextItem
from memo_stack_core.domain.entities import MemoryChunk, MemoryFact, SourceRef
from memo_stack_core.ports.adapters import (
    EmbeddingPort,
    GraphMemoryPort,
    PortStatus,
    VectorMemoryPort,
)
from memo_stack_core.ports.capabilities import (
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityStatus,
    MemoryScopeFilter,
    RagRecallPort,
)
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SAFE_RECALL_METADATA_KEYS = frozenset(
    {
        "provider",
        "adapter_name",
        "projection_version",
        "collection",
        "dataset_id",
    }
)
_SENSITIVE_VALUE_MARKERS = (
    "bearer ",
    "sk-",
    "api_key",
    "password",
    "secret",
    "token",
    "private_",
)


@dataclass(frozen=True)
class CanonicalCollectionResult:
    facts: tuple[MemoryFact, ...]
    keyword_chunks: tuple[MemoryChunk, ...]


class CanonicalContextCollector:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> CanonicalCollectionResult:
        async with self._uow_factory() as uow:
            facts = await uow.facts.find_active(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                query=query.query,
                limit=query.max_facts,
                category=query.category,
                tags_any=query.tags_any,
                tags_all=query.tags_all,
                tags_none=query.tags_none,
            )
            keyword_chunks = await uow.chunks.keyword_search(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                query=query.query,
                limit=query.max_chunks,
            )
        return CanonicalCollectionResult(
            facts=tuple(facts),
            keyword_chunks=tuple(keyword_chunks),
        )


class VectorContextCollector:
    def __init__(
        self,
        *,
        vector_index: VectorMemoryPort,
        embedder: EmbeddingPort,
        hydrator: ContextHydrator,
    ) -> None:
        self._vector_index = vector_index
        self._embedder = embedder
        self._hydrator = hydrator

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
    ) -> tuple[MemoryChunk, ...]:
        if query.max_chunks <= 0:
            diagnostics["vector_status"] = "skipped"
            return ()
        try:
            capabilities = await self._vector_index.capabilities()
        except Exception as exc:
            diagnostics["vector_status"] = "degraded"
            diagnostics["vector_degraded_reason"] = _exception_code("vector", exc)
            return ()
        if not capabilities.enabled:
            diagnostics["vector_status"] = (
                "disabled" if capabilities.degraded_reason == "disabled" else "degraded"
            )
            if capabilities.degraded_reason:
                diagnostics["vector_degraded_reason"] = capabilities.degraded_reason
            return ()
        if not capabilities.healthy or not capabilities.supports_search:
            diagnostics["vector_status"] = "degraded"
            if capabilities.degraded_reason:
                diagnostics["vector_degraded_reason"] = capabilities.degraded_reason
            return ()

        try:
            embedding = await self._embedder.embed_texts((query.query,))
        except Exception as exc:
            diagnostics["vector_status"] = "degraded"
            diagnostics["vector_degraded_reason"] = _exception_code("embeddings", exc)
            return ()
        if embedding.status != PortStatus.OK or not embedding.vectors:
            diagnostics["vector_status"] = embedding.status.value
            if embedding.diagnostics:
                diagnostics["vector_degraded_reason"] = embedding.diagnostics[0].code
            return ()
        try:
            result = await self._vector_index.search_chunks(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                query_vector=embedding.vectors[0],
                limit=query.max_chunks,
            )
        except Exception as exc:
            diagnostics["vector_status"] = "degraded"
            diagnostics["vector_degraded_reason"] = _exception_code("vector", exc)
            return ()
        diagnostics["vector_status"] = result.status.value
        if result.diagnostics:
            diagnostics["vector_degraded_reason"] = result.diagnostics[0].code
        diagnostics["vector_candidate_count"] = len(result.items)
        if result.status != PortStatus.OK or not result.items:
            return ()
        chunk_ids = tuple(candidate.chunk_id for candidate in result.items)
        chunks = await self._hydrator.hydrate_visible_chunks(
            chunk_ids=chunk_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        hydrated_ids = {str(chunk.id) for chunk in chunks}
        diagnostics["vector_hydrated_count"] = len(chunks)
        diagnostics["stale_vector_drop_count"] = sum(
            1 for chunk_id in chunk_ids if chunk_id not in hydrated_ids
        )
        return chunks


class GraphContextCollector:
    def __init__(
        self,
        *,
        graph_index: GraphMemoryPort,
        hydrator: ContextHydrator,
    ) -> None:
        self._graph_index = graph_index
        self._hydrator = hydrator

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
    ) -> tuple[ContextItem, ...]:
        if not query.include_graph or query.max_facts <= 0:
            diagnostics["graph_status"] = "skipped"
            return ()
        try:
            capabilities = await self._graph_index.capabilities()
        except Exception as exc:
            diagnostics["graph_status"] = "degraded"
            diagnostics["graph_degraded_reason"] = _exception_code("graph", exc)
            return ()
        if not capabilities.enabled:
            diagnostics["graph_status"] = (
                "disabled" if capabilities.degraded_reason == "disabled" else "degraded"
            )
            if capabilities.degraded_reason:
                diagnostics["graph_degraded_reason"] = capabilities.degraded_reason
            return ()
        if not capabilities.healthy or not capabilities.supports_search:
            diagnostics["graph_status"] = "degraded"
            if capabilities.degraded_reason:
                diagnostics["graph_degraded_reason"] = capabilities.degraded_reason
            return ()
        try:
            result = await self._graph_index.search(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                query=query.query,
                limit=query.max_facts,
            )
        except Exception as exc:
            diagnostics["graph_status"] = "degraded"
            diagnostics["graph_degraded_reason"] = _exception_code("graph", exc)
            return ()
        diagnostics["graph_status"] = result.status.value
        if result.diagnostics:
            diagnostics["graph_degraded_reason"] = result.diagnostics[0].code
        diagnostics["graph_candidate_count"] = len(result.items)
        if result.status != PortStatus.OK or not result.items:
            return ()

        orphan_candidate_count = sum(
            1
            for candidate in result.items
            if not candidate.source_fact_ids and not candidate.source_chunk_ids
        )
        fact_ids = tuple(
            dict.fromkeys(
                fact_id for candidate in result.items for fact_id in candidate.source_fact_ids
            )
        )
        if not fact_ids:
            diagnostics["stale_graph_drop_count"] = orphan_candidate_count
            return ()
        items, stale_count = await self._hydrator.hydrate_graph_facts(
            fact_ids=fact_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        diagnostics["graph_hydrated_count"] = len(items)
        diagnostics["stale_graph_drop_count"] = stale_count + orphan_candidate_count
        return items[: query.max_facts]


class RagContextCollector:
    def __init__(
        self,
        *,
        rag_recall: RagRecallPort | None,
        hydrator: ContextHydrator,
    ) -> None:
        self._rag_recall = rag_recall
        self._hydrator = hydrator

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
    ) -> tuple[ContextItem, ...]:
        if self._rag_recall is None or query.max_chunks <= 0:
            diagnostics["rag_status"] = "skipped"
            return ()
        try:
            result = await self._rag_recall.recall(
                CapabilityRecallQuery(
                    scope=MemoryScopeFilter(
                        space_id=str(query.space_id),
                        memory_scope_ids=memory_scope_ids,
                        thread_id=str(query.thread_id) if query.thread_id else None,
                    ),
                    query=query.query,
                    limit=query.max_chunks,
                )
            )
        except Exception as exc:
            diagnostics["rag_status"] = "degraded"
            diagnostics["rag_degraded_reason"] = _exception_code("rag", exc)
            return ()
        diagnostics["rag_status"] = result.status.value
        if result.diagnostics:
            diagnostics["rag_degraded_reason"] = result.diagnostics[0].code
        if result.status != CapabilityStatus.OK:
            return ()

        chunk_ids = tuple(
            dict.fromkeys(
                chunk_id
                for candidate in result.items
                for chunk_id in _candidate_chunk_ids(candidate)
            )
        )
        chunks = await self._hydrator.hydrate_visible_chunks(
            chunk_ids=chunk_ids,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        chunks_by_id = {str(chunk.id): chunk for chunk in chunks}
        items: list[ContextItem] = []
        dropped = 0
        for candidate in result.items:
            visible_chunk = next(
                (
                    chunks_by_id[chunk_id]
                    for chunk_id in _candidate_chunk_ids(candidate)
                    if chunk_id in chunks_by_id
                ),
                None,
            )
            if visible_chunk is None:
                dropped += 1
                continue
            items.append(_rag_chunk_item(candidate, visible_chunk))
        diagnostics["stale_rag_drop_count"] = dropped
        return tuple(items)


def _candidate_chunk_ids(candidate: CapabilityRecallCandidate) -> tuple[str, ...]:
    chunk_ids: list[str] = []
    if candidate.item_type == "chunk":
        chunk_ids.append(candidate.item_id)
    for source_ref in candidate.source_refs:
        if source_ref.chunk_id:
            chunk_ids.append(source_ref.chunk_id)
        elif source_ref.source_type == "chunk":
            chunk_ids.append(source_ref.source_id)
    return tuple(dict.fromkeys(chunk_id for chunk_id in chunk_ids if chunk_id.strip()))


def _rag_chunk_item(candidate: CapabilityRecallCandidate, chunk: MemoryChunk) -> ContextItem:
    chunk_text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
    return ContextItem(
        item_id=str(chunk.id),
        item_type="chunk",
        text=chunk_text,
        score=candidate.score,
        source_refs=(
            SourceRef(
                source_type=chunk.source_type,
                source_id=chunk.source_external_id,
                chunk_id=str(chunk.id),
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                quote_preview=chunk_text[:200],
            ),
        ),
        diagnostics={
            "memory_scope_id": str(chunk.memory_scope_id),
            "retrieval_source": "rag_recall",
            "retrieval_sources": ["rag_recall"],
            "ranking_reason": "matched via external RAG recall and canonical hydration",
            "score_signals": {
                "base_score": candidate.score,
                "retrieval_channel": "rag_recall",
            },
            "provenance": {
                "retrieval_sources": ["rag_recall"],
                "source_ref_count": 1,
                "adapter_name": _safe_adapter_name(candidate.adapter_name),
                "chunk_id": str(chunk.id),
            },
            "adapter_name": _safe_adapter_name(candidate.adapter_name),
            **_safe_recall_metadata(candidate.metadata),
        },
    )


def _safe_recall_metadata(metadata: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = str(raw_key).strip()
        if key not in _SAFE_RECALL_METADATA_KEYS:
            continue
        value = _safe_metadata_value(raw_value)
        if _looks_sensitive(value):
            continue
        safe[key] = value
    return safe


def _safe_adapter_name(value: object) -> str:
    safe_value = _safe_metadata_value(value)
    if not safe_value or _looks_sensitive(safe_value):
        return "unknown"
    return safe_value


def _safe_metadata_value(value: object) -> str:
    return str(value).strip()[:160]


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS)


def _exception_code(adapter: str, exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return f"{adapter}.timeout"
    return f"{adapter}.exception"
