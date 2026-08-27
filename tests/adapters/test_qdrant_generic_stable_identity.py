from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from infinity_context_adapters.qdrant.generation_fence import legacy_generation_point_id
from infinity_context_adapters.qdrant.vector_adapter import QdrantVectorMemoryAdapter
from infinity_context_core.ports.adapters import PortStatus, VectorUpsertItem
from infinity_context_core.ports.vector_projection_evidence import VectorProjectionScope

qdrant_client = pytest.importorskip("qdrant_client")


def test_embedded_qdrant_filters_legacy_generations_before_topk_and_exact_evidence(
    tmp_path: Path,
) -> None:
    asyncio.run(_assert_stable_generic_identity(tmp_path / "qdrant"))


async def _assert_stable_generic_identity(path: Path) -> None:
    from qdrant_client import AsyncQdrantClient, models

    adapter = QdrantVectorMemoryAdapter(
        url="http://embedded.invalid",
        collection_name="generic_stable",
        vector_size=3,
    )

    async def embedded_client():
        return AsyncQdrantClient(path=str(path)), models

    adapter._client = embedded_client  # type: ignore[method-assign]
    version_two = _item("chunk-aba", 2, (1.0, 0.0, 0.0))
    other = _item("chunk-other", 1, (0.9, 0.1, 0.0))
    assert (await adapter.upsert_chunks((version_two, other))).status == PortStatus.OK

    client = AsyncQdrantClient(path=str(path))
    try:
        await client.upsert(
            collection_name="generic_stable",
            points=[
                models.PointStruct(
                    id=legacy_generation_point_id("chunk-aba", 1),
                    vector=[1.0, 0.0, 0.0],
                    payload={
                        "chunk_id": "chunk-aba",
                        "space_id": "space",
                        "memory_scope_id": "scope",
                        "thread_id": None,
                        "projection_version": "v1",
                        "canonical_version": 1,
                    },
                )
            ],
            wait=True,
        )
    finally:
        await client.close()

    search = await adapter.search_chunks(
        space_id="space",
        memory_scope_ids=("scope",),
        query_vector=(1.0, 0.0, 0.0),
        limit=2,
    )
    assert search.status == PortStatus.OK
    assert [item.chunk_id for item in search.items] == ["chunk-aba", "chunk-other"]

    # Replay current canonical state removes the retired generation-ID point.
    assert (await adapter.upsert_chunks((version_two,))).status == PortStatus.OK
    evidence = await adapter.observe_exact(
        scope=VectorProjectionScope(
            space_id="space",
            memory_scope_id="scope",
            thread_id=None,
            projection_version="v1",
        ),
        chunk_ids=("chunk-aba", "chunk-other"),
    )
    assert evidence.complete is True
    assert evidence.issues == ()


def _item(
    chunk_id: str,
    canonical_version: int,
    vector: tuple[float, ...],
) -> VectorUpsertItem:
    return VectorUpsertItem(
        chunk_id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id=None,
        text=f"text {chunk_id}",
        vector=vector,
        projection_version="v1",
        metadata={"canonical_version": canonical_version},
    )
