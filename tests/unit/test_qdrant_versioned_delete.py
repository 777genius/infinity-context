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
from infinity_context_core.features.context_building.public import (
    ProfileTombstoneDeleteAuthorization,
    RetrievalProfileIdentity,
)
from infinity_context_core.ports.adapters import PortStatus, VectorUpsertItem


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
        self.current_versions: dict[str, object] = {}
        self.delete_enabled = True
        self.fail_observation_once = False

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name == "locator"

    async def delete(self, **kwargs: object) -> None:
        self.delete_calls.append(kwargs)
        selector = kwargs["points_selector"]
        conditions = selector.kwargs["filter"].kwargs["must"]
        point_ids = conditions[0].kwargs["has_id"]
        version = conditions[1].kwargs["match"].kwargs["value"]
        if self.delete_enabled:
            for point_id in point_ids:
                if self.current_versions.get(point_id) == version:
                    del self.current_versions[point_id]

    async def retrieve(self, **kwargs: object) -> list[SimpleNamespace]:
        assert kwargs["with_payload"] == ["canonical_version"]
        assert kwargs["with_vectors"] is False
        if "consistency" in kwargs:
            assert kwargs["consistency"] == "all"
        if self.fail_observation_once:
            self.fail_observation_once = False
            raise TimeoutError("ambiguous read after completed delete")
        return [
            SimpleNamespace(
                id=point_id,
                payload=({} if version is None else {"canonical_version": version}),
            )
            for point_id in kwargs["ids"]
            if (version := self.current_versions.get(point_id, _MISSING)) is not _MISSING
        ]

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


_MISSING = object()


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


def test_qdrant_rejects_unversioned_generic_point_before_provider_access() -> None:
    async def run() -> None:
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="generic", vector_size=3
        )

        async def forbidden_client():
            raise AssertionError("unversioned point reached provider")

        adapter._client = forbidden_client  # type: ignore[method-assign]
        result = await adapter.upsert_chunks(
            (
                VectorUpsertItem(
                    chunk_id="chunk-unversioned",
                    space_id="space",
                    memory_scope_id="scope",
                    thread_id=None,
                    text="legacy point",
                    vector=(0.1, 0.2, 0.3),
                    projection_version="v1",
                ),
            )
        )
        assert result.status == PortStatus.DEGRADED
        assert result.diagnostics[0].code == "qdrant.canonical_version_invalid"
        assert result.diagnostics[0].retryable is False

    asyncio.run(run())


def test_profile_projection_versioned_delete_preserves_exact_port_arguments() -> None:
    async def run() -> None:
        calls: list[tuple[tuple[str, ...], int]] = []

        async def delete_chunks_if_version(chunk_ids, *, canonical_version):
            calls.append((chunk_ids, canonical_version))
            return SimpleNamespace(status=PortStatus.OK)

        async def observe_chunk_versions(chunk_ids):
            return tuple(None for _ in chunk_ids)

        fence = _Fence()
        projection = QdrantRetrievalProfileProjection(
            url="http://qdrant.test",
            api_key=None,
            vector_size=3,
            embedder=SimpleNamespace(),
            mutation_registry=fence,
        )
        adapter = SimpleNamespace(
            delete_chunks_if_version=delete_chunks_if_version,
            observe_chunk_versions=observe_chunk_versions,
        )
        projection._adapters["profile-a"] = adapter
        identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "locator")
        authorization = ProfileTombstoneDeleteAuthorization(identity, "chunk-2", 8, 0)

        proof = await projection.delete_profile_if_version(
            identity,
            ("chunk-2",),
            canonical_version=7,
            tombstone_authorization=authorization,
        )

        assert calls == [(("chunk-2",), 7)]
        assert proof.canonical_ids == ("chunk-2",)
        assert proof.canonical_version == 7
        assert proof.remaining_canonical_versions == (None,)
        assert proof.provider_mutation_epoch == 2
        assert [event[0] for event in fence.events] == ["begin", "finish"]
        assert fence.events[0][3]["tombstone_authorization"] == authorization
        assert await projection.attestation_epoch(identity, now=datetime.now(UTC)) == 2

    asyncio.run(run())


def test_qdrant_delete_fails_closed_when_exact_generation_remains() -> None:
    async def run() -> None:
        client = _Client()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        async def ineffective_delete(**kwargs: object) -> None:
            client.delete_calls.append(kwargs)

        adapter._client = fake_client  # type: ignore[method-assign]
        client.delete = ineffective_delete  # type: ignore[method-assign]
        point_id = qdrant_point_id_for_chunk("chunk-1")
        client.current_versions[point_id] = 7

        result = await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=7)

        assert result.status == PortStatus.DEGRADED
        assert tuple(item.code for item in result.diagnostics) == (
            "qdrant.delete_generation_remaining",
        )

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
        first_stale = await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=4)
        second_stale = await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=4)
        assert first_stale.status == second_stale.status == PortStatus.OK
        assert client.current_versions[point_id] == 5

        await adapter.delete_chunks_if_version(("chunk-1",), canonical_version=5)
        assert point_id not in client.current_versions

    asyncio.run(run())


def test_qdrant_observation_reports_absent_older_equal_and_newer_generations() -> None:
    async def run() -> None:
        client = _Client()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        adapter._client = fake_client  # type: ignore[method-assign]
        point_id = qdrant_point_id_for_chunk("chunk-1")
        assert await adapter.observe_chunk_versions(("chunk-1",)) == (None,)
        for version in (1, 2, 4):
            client.current_versions[point_id] = version
            assert await adapter.observe_chunk_versions(("chunk-1",)) == (version,)

    asyncio.run(run())


def test_legacy_unversioned_and_older_points_require_explicit_rebuild() -> None:
    async def run() -> None:
        client = _Client()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        adapter._client = fake_client  # type: ignore[method-assign]
        point_id = qdrant_point_id_for_chunk("chunk-legacy")
        for observed_version in (None, 3):
            client.current_versions[point_id] = observed_version
            result = await adapter.delete_chunks_if_version(("chunk-legacy",), canonical_version=4)
            assert result.status == PortStatus.DEGRADED
            assert result.diagnostics[0].code == "qdrant.delete_rebuild_required"
            assert result.diagnostics[0].retryable is False
            assert point_id in client.current_versions

    asyncio.run(run())


def test_qdrant_observation_failure_is_not_absence() -> None:
    async def run() -> None:
        client = _Client()
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        async def failed_retrieve(**_kwargs):
            raise OSError("injected observation failure")

        adapter._client = fake_client  # type: ignore[method-assign]
        client.retrieve = failed_retrieve  # type: ignore[method-assign]
        try:
            await adapter.observe_chunk_versions(("chunk-1",))
        except RuntimeError as exc:
            assert str(exc) == "qdrant.observe_canonical_version_failed"
        else:  # pragma: no cover
            raise AssertionError("failed provider observation was treated as absence")

    asyncio.run(run())


def test_exact_generation_must_be_observed_absent_before_completion() -> None:
    async def run() -> None:
        client = _Client()
        client.delete_enabled = False
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        adapter._client = fake_client  # type: ignore[method-assign]
        point_id = qdrant_point_id_for_chunk("chunk-remaining")
        client.current_versions[point_id] = 7
        result = await adapter.delete_chunks_if_version(("chunk-remaining",), canonical_version=7)
        assert result.status == PortStatus.DEGRADED
        assert result.diagnostics[0].code == "qdrant.delete_generation_remaining"
        assert result.diagnostics[0].retryable is True

    asyncio.run(run())


def test_delete_crash_replay_reconciles_already_absent_generation() -> None:
    async def run() -> None:
        client = _Client()
        client.fail_observation_once = True
        adapter = QdrantVectorMemoryAdapter(
            url="http://qdrant.test", collection_name="locator", vector_size=3
        )

        async def fake_client():
            return client, _Models

        adapter._client = fake_client  # type: ignore[method-assign]
        point_id = qdrant_point_id_for_chunk("chunk-replay")
        client.current_versions[point_id] = 9

        ambiguous = await adapter.delete_chunks_if_version(("chunk-replay",), canonical_version=9)
        assert ambiguous.status == PortStatus.DEGRADED
        assert point_id not in client.current_versions

        reconciled = await adapter.delete_chunks_if_version(("chunk-replay",), canonical_version=9)
        assert reconciled.status == PortStatus.OK
        assert reconciled.affected_count == 1

    asyncio.run(run())
