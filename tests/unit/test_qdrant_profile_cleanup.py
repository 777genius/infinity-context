from __future__ import annotations

import asyncio

from infinity_context_adapters.qdrant.profile_lifecycle import (
    QdrantRetrievalProfileProjection,
)
from infinity_context_core.features.context_building.public import (
    ProfileCollectionDeleteAuthorization,
    RetrievalProfileIdentity,
)


def test_collection_cleanup_is_idempotent_when_collection_is_already_absent() -> None:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "collection_a")
    client = _Client()
    projection = QdrantRetrievalProfileProjection(
        "http://qdrant.invalid", None, 2, object(), _Fence()
    )
    projection._adapters[identity.profile_id] = _Adapter(client)

    authorization = ProfileCollectionDeleteAuthorization(identity, "delete-token", 3)
    asyncio.run(projection.delete_profile(authorization))
    projection._adapters[identity.profile_id] = _Adapter(client)
    asyncio.run(projection.delete_profile(authorization))

    assert client.deletions == ["collection_a"]


def test_provider_fence_spans_prepare_acknowledgement_and_exact_close() -> None:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "collection_a")
    events: list[str] = []
    fence = _RecordingFence(events)
    projection = QdrantRetrievalProfileProjection("http://qdrant.invalid", None, 2, object(), fence)
    projection._adapters[identity.profile_id] = _PreparingAdapter(events)

    asyncio.run(projection.prepare_profile(identity))

    assert events == ["begin", "provider_start", "provider_ack", "finish:1"]


def test_ambiguous_provider_failure_leaves_durable_fence_open() -> None:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "collection_a")
    events: list[str] = []
    fence = _RecordingFence(events)
    projection = QdrantRetrievalProfileProjection("http://qdrant.invalid", None, 2, object(), fence)
    projection._adapters[identity.profile_id] = _PreparingAdapter(events, fail=True)

    try:
        asyncio.run(projection.prepare_profile(identity))
    except RuntimeError as exc:
        assert str(exc) == "retrieval_profile_qdrant_prepare_failed"
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("ambiguous provider failure was acknowledged")

    assert events == ["begin", "provider_start"]


class _Adapter:
    def __init__(self, client):
        self.client = client

    async def _client(self):
        return self.client, object()


class _PreparingAdapter:
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    async def _client(self):
        return _PreparingClient(), object()

    async def _ensure_collection(self, _client, _models):
        self.events.append("provider_start")
        if self.fail:
            raise TimeoutError("ambiguous provider outcome")
        self.events.append("provider_ack")


class _PreparingClient:
    async def close(self):
        return None


class _Fence:
    async def begin_provider_mutation(self, *_args, **_kwargs):
        return 1

    async def finish_provider_mutation(self, *_args, **_kwargs):
        return 2


class _RecordingFence:
    def __init__(self, events):
        self.events = events

    async def begin_provider_mutation(self, *_args, **_kwargs):
        self.events.append("begin")
        return 1

    async def heartbeat_provider_mutation(self, *_args, **_kwargs):
        self.events.append("heartbeat")

    async def finish_provider_mutation(self, *_args, started_epoch, **_kwargs):
        self.events.append(f"finish:{started_epoch}")
        return started_epoch + 1


class _Client:
    def __init__(self):
        self.exists = True
        self.deletions = []

    async def collection_exists(self, collection_name):
        return self.exists

    async def delete_collection(self, collection_name):
        self.deletions.append(collection_name)
        self.exists = False

    async def close(self):
        return None
