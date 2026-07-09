"""Deterministic hybrid retrieval helpers for local eval harnesses."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application import BuildContextUseCase
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    EmbeddingResult,
    PortStatus,
    VectorCandidate,
    VectorSearchResult,
    VectorWriteResult,
)


class EvalHybridEmbeddingAdapter:
    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult.degraded("eval.empty_embedding_request", retryable=False)
        return EmbeddingResult(status=PortStatus.OK, vectors=((0.11, 0.22, 0.33),))


class EvalHybridVectorAdapter:
    def __init__(self, chunk_id: str) -> None:
        self._chunk_id = chunk_id

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="eval-hybrid-vector",
            enabled=True,
            healthy=True,
            supports_upsert=False,
            supports_delete=False,
            supports_search=True,
            supports_filters=True,
        )

    async def search_chunks(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None = None,
        query_vector: tuple[float, ...],
        query_text: str | None = None,
        limit: int,
    ) -> VectorSearchResult:
        if not memory_scope_ids or not query_vector or limit <= 0:
            return VectorSearchResult.ok([])
        return VectorSearchResult.ok(
            [
                VectorCandidate(
                    chunk_id=self._chunk_id,
                    space_id=space_id,
                    memory_scope_id=memory_scope_ids[0],
                    score=1.0,
                    projection_version="eval-hybrid-v1",
                )
            ]
        )

    async def upsert_chunks(self, items: tuple[object, ...]) -> VectorWriteResult:
        return VectorWriteResult.ok(len(items))

    async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> VectorWriteResult:
        return VectorWriteResult.ok(len(chunk_ids))


def install_eval_hybrid_context(client: Any, *, chunk_id: str | None) -> bool:
    """Install deterministic vector recall into an in-process TestClient app."""

    if not chunk_id:
        return False
    app = getattr(client, "app", None)
    state = getattr(app, "state", None)
    container = getattr(state, "container", None)
    if container is None:
        return False

    vector = EvalHybridVectorAdapter(chunk_id)
    embedder = EvalHybridEmbeddingAdapter()
    build_context = BuildContextUseCase(
        uow_factory=container.uow_factory,
        ids=container.ids,
        vector_index=vector,
        graph_index=container.graph_index,
        embedder=embedder,
        clock=container.clock,
        rag_recall=container.cognee_memory,
        packer=ContextPacker(),
        blob_storage=container.blob_storage,
    )
    object.__setattr__(container, "vector_index", vector)
    object.__setattr__(container, "embedder", embedder)
    object.__setattr__(container, "build_context", build_context)
    return True
