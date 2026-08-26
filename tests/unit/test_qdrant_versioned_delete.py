from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_adapters.qdrant.profile_lifecycle import (
    QdrantRetrievalProfileProjection,
)
from infinity_context_adapters.qdrant.vector_adapter import (
    QdrantVectorMemoryAdapter,
    qdrant_point_id_for_chunk,
)
from infinity_context_core.features.context_building.public import RetrievalProfileIdentity
from infinity_context_core.ports.adapters import PortStatus


class _Value:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _Models:
    FilterSelector = _Value
    Filter = _Value
    HasIdCondition = _Value
    FieldCondition = _Value
    MatchValue = _Value


class _Client:
    def __init__(self) -> None:
        self.delete_calls: list[dict[str, object]] = []
        self.current_versions: dict[str, int] = {}

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name == "locator"

    async def delete(self, **kwargs: object) -> None:
        self.delete_calls.append(kwargs)
        selector = kwargs["points_selector"]
        conditions = selector.kwargs["filter"].kwargs["must"]
        point_ids = conditions[0].kwargs["has_id"]
        version = conditions[1].kwargs["match"].kwargs["value"]
        for point_id in point_ids:
            if self.current_versions.get(point_id) == version:
                del self.current_versions[point_id]

    async def close(self) -> None:
        return None


class _Fence:
    def __init__(self) -> None:
        self.events = []

    async def begin_provider_mutation(self, profile_id, operation_id, **values):
        self.events.append(("begin", profile_id, operation_id, values))
        return 1

    async def finish_provider_mutation(self, profile_id, operation_id, **values):
        self.events.append(("finish", profile_id, operation_id, values))
        return 2

    async def provider_attestation_epoch(self, profile_id, *, now):
        self.events.append(("attest", profile_id, now))
        return 2


def test_qdrant_versioned_delete_filters_id_and_canonical_version() -> None:
    async def run() -> None:
        client = _Client()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        adapter._client = fake_client  # type: ignore[method-assign]
        result = await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=7)

        assert result.status == PortStatus.OK
        selector = client.delete_calls[0]["points_selector"]
        conditions = selector.kwargs["filter"].kwargs["must"]
        assert conditions[0].kwargs["has_id"]
        assert conditions[1].kwargs["key"] == "canonical_version"
        assert conditions[1].kwargs["match"].kwargs["value"] == 7

    asyncio.run(run())


def test_profile_projection_versioned_delete_preserves_exact_port_arguments() -> None:
    async def run() -> None:
        calls: list[tuple[tuple[str, ...], int]] = []

        async def delete_chunks_if_version(chunk_ids, *, canonical_version):
            calls.append((chunk_ids, canonical_version))
            return SimpleNamespace(status=PortStatus.OK)

        fence = _Fence()
        projection = QdrantRetrievalProfileProjection(
            url="http://qdrant.test",
            api_key=None,
            vector_size=3,
            embedder=SimpleNamespace(),
            mutation_registry=fence,
        )
        adapter = SimpleNamespace(delete_chunks_if_version=delete_chunks_if_version)
        projection._adapters["profile-a"] = adapter
        identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "locator")

        await projection.delete_profile_if_version(
            identity, ("chunk-2", "chunk-1"), canonical_version=7
        )

        assert calls == [(("chunk-2", "chunk-1"), 7)]
        assert [event[0] for event in fence.events] == ["begin", "finish"]
        assert await projection.attestation_epoch(identity, now=datetime.now(UTC)) == 2

    asyncio.run(run())


def test_stale_delete_replay_and_reconciliation_cannot_remove_superseding_point() -> None:
    async def run() -> None:
        client = _Client()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        adapter._client = fake_client  # type: ignore[method-assign]
        point_id = qdrant_point_id_for_chunk("chunk-1")

        client.current_versions[point_id] = 4
        await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=4)
        assert point_id not in client.current_versions

        # Supersession/replay restores canonical version 5. Both a delayed event
        # and a later reconciliation pass may replay the version-4 delete.
        client.current_versions[point_id] = 5
        await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=4)
        await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=4)
        assert client.current_versions[point_id] == 5

        await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=5)
        assert point_id not in client.current_versions

    asyncio.run(run())
