import asyncio
import hashlib
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter
from infinity_context_adapters.qdrant.identity_evidence import (
    qdrant_point_id_for_chunk,
)
from infinity_context_core.ports.vector_projection_evidence import VectorProjectionScope


class _Box:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _Models:
    class PointIdsList(_Box):
        pass

    class Filter(_Box):
        pass

    class FieldCondition(_Box):
        pass

    class MatchValue(_Box):
        pass

    class PayloadField(_Box):
        pass

    class IsNullCondition(_Box):
        pass

    class WriteOrdering:
        STRONG = "strong"


class _EvidenceClient:
    def __init__(self, records: tuple[object, ...], *, sticky_delete: bool = False) -> None:
        self.collection_name = "collection_1"
        self.records = {str(record.id): record for record in records}
        self.sticky_delete = sticky_delete
        self.retrieve_calls: list[dict[str, object]] = []
        self.scroll_calls: list[dict[str, object]] = []
        self.count_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.closed = 0

    async def collection_exists(self, collection_name: str) -> bool:
        return collection_name == self.collection_name

    async def retrieve(self, **kwargs: object) -> list[object]:
        self.retrieve_calls.append(kwargs)
        return [self.records[point_id] for point_id in kwargs["ids"] if point_id in self.records]

    async def scroll(self, **kwargs: object) -> tuple[list[object], int | None]:
        self.scroll_calls.append(kwargs)
        records = list(self.records.values())
        start = int(kwargs["offset"] or 0)
        page = records[start : start + 1]
        next_offset = start + 1 if start + 1 < len(records) else None
        return page, next_offset

    async def count(self, **kwargs: object) -> object:
        self.count_calls.append(kwargs)
        return SimpleNamespace(count=len(self.records))

    async def delete(self, **kwargs: object) -> object:
        self.delete_calls.append(kwargs)
        if not self.sticky_delete:
            for point_id in kwargs["points_selector"].kwargs["points"]:
                self.records.pop(point_id, None)
        return SimpleNamespace(status="completed")

    async def close(self) -> None:
        self.closed += 1


def _scope() -> VectorProjectionScope:
    return VectorProjectionScope(
        space_id="space_1",
        memory_scope_id="memory_scope_1",
        thread_id=None,
        projection_version="v1",
    )


def _record(chunk_id: str) -> object:
    return SimpleNamespace(
        id=qdrant_point_id_for_chunk(chunk_id),
        payload={
            "chunk_id": chunk_id,
            "space_id": "space_1",
            "memory_scope_id": "memory_scope_1",
            "thread_id": None,
            "projection_version": "v1",
        },
    )


def _adapter(client: _EvidenceClient) -> QdrantVectorMemoryAdapter:
    adapter = QdrantVectorMemoryAdapter(
        url="http://qdrant.invalid",
        api_key="not-exported",
        collection_name="collection_1",
        projection_version="v1",
    )

    async def client_factory() -> tuple[_EvidenceClient, type[_Models]]:
        return client, _Models

    adapter._client = client_factory  # type: ignore[method-assign]
    return adapter


def test_qdrant_point_identity_and_target_commitment_are_stable_and_secret_free() -> None:
    first = QdrantVectorMemoryAdapter(
        url="http://first.invalid",
        api_key="secret-one",
        collection_name="collection_1",
    )
    second = QdrantVectorMemoryAdapter(
        url="http://second.invalid",
        api_key="secret-two",
        collection_name="collection_1",
    )
    other_collection = QdrantVectorMemoryAdapter(
        url="http://first.invalid",
        api_key="secret-one",
        collection_name="collection_2",
    )

    assert qdrant_point_id_for_chunk("chunk_1") == str(uuid5(NAMESPACE_URL, "chunk_1"))
    assert (
        first.target_commitment_sha256
        == hashlib.sha256(b"qdrant\x00http://first.invalid\x00collection_1").hexdigest()
    )
    assert first.target_commitment_sha256 != second.target_commitment_sha256
    assert first.target_commitment_sha256 != other_collection.target_commitment_sha256
    assert "secret" not in first.target_commitment_sha256
    assert "qdrant" not in first.target_commitment_sha256

    same_target_other_secret = QdrantVectorMemoryAdapter(
        url="HTTP://FIRST.INVALID:80/?api_key=query-secret",
        api_key="another-secret",
        collection_name="collection_1",
    )
    assert same_target_other_secret.target_commitment_sha256 == first.target_commitment_sha256


def test_qdrant_presence_evidence_is_exact_paginated_and_identity_only() -> None:
    async def run() -> None:
        client = _EvidenceClient((_record("chunk_1"), _record("chunk_2")))
        adapter = _adapter(client)

        evidence = await adapter.observe_exact(
            scope=_scope(),
            chunk_ids=("chunk_1", "chunk_2"),
        )

        assert evidence.complete is True
        assert evidence.target_commitment_sha256 == adapter.target_commitment_sha256
        assert [item.chunk_id for item in evidence.observed] == ["chunk_1", "chunk_2"]
        assert len(client.scroll_calls) == 2
        retrieve = client.retrieve_calls[0]
        assert retrieve["with_payload"] == [
            "chunk_id",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "projection_version",
        ]
        assert retrieve["with_vectors"] is False
        assert retrieve["consistency"] == "all"
        assert all(call["with_vectors"] is False for call in client.scroll_calls)
        assert all(call["consistency"] == "all" for call in client.scroll_calls)
        assert client.count_calls == [
            {
                "collection_name": "collection_1",
                "count_filter": client.scroll_calls[0]["scroll_filter"],
                "exact": True,
            }
        ]
        must = client.scroll_calls[0]["scroll_filter"].kwargs["must"]
        assert {
            condition.kwargs["key"]: condition.kwargs["match"].kwargs["value"]
            for condition in must[:3]
        } == {
            "space_id": "space_1",
            "memory_scope_id": "memory_scope_1",
            "projection_version": "v1",
        }
        assert must[3].kwargs["is_null"].kwargs == {"key": "thread_id"}

    asyncio.run(run())


def test_qdrant_delete_uses_strong_ordering_readback_and_idempotent_second_pass() -> None:
    async def run() -> None:
        client = _EvidenceClient((_record("chunk_1"), _record("chunk_2")))
        adapter = _adapter(client)

        first = await adapter.delete_and_observe_exact(
            scope=_scope(),
            chunk_ids=("chunk_1", "chunk_2"),
            pass_index=1,
        )
        second = await adapter.delete_and_observe_exact(
            scope=_scope(),
            chunk_ids=("chunk_1", "chunk_2"),
            pass_index=2,
        )

        assert first.verified_absent is True
        assert second.verified_absent is True
        assert [item.chunk_id for item in first.present_before] == ["chunk_1", "chunk_2"]
        assert second.present_before == ()
        assert first.target_commitment_sha256 == second.target_commitment_sha256
        assert len(client.delete_calls) == 2
        assert all(call["wait"] is True for call in client.delete_calls)
        assert all(call["ordering"] == _Models.WriteOrdering.STRONG for call in client.delete_calls)
        expected_ids = [
            qdrant_point_id_for_chunk("chunk_1"),
            qdrant_point_id_for_chunk("chunk_2"),
        ]
        assert client.delete_calls[0]["points_selector"].kwargs["points"] == expected_ids

    asyncio.run(run())


def test_qdrant_delete_fails_closed_before_mutation_on_unexpected_scoped_point() -> None:
    async def run() -> None:
        client = _EvidenceClient((_record("chunk_1"), _record("unexpected_chunk")))
        adapter = _adapter(client)

        evidence = await adapter.delete_and_observe_exact(
            scope=_scope(),
            chunk_ids=("chunk_1",),
            pass_index=1,
        )

        assert evidence.verified_absent is False
        assert "qdrant.evidence_unexpected_scoped_point" in evidence.issues
        assert "qdrant.evidence_delete_precondition_failed" in evidence.issues
        assert client.delete_calls == []

    asyncio.run(run())


def test_qdrant_delete_fails_closed_when_point_remains_after_completed_ack() -> None:
    async def run() -> None:
        client = _EvidenceClient((_record("chunk_1"),), sticky_delete=True)
        adapter = _adapter(client)

        evidence = await adapter.delete_and_observe_exact(
            scope=_scope(),
            chunk_ids=("chunk_1",),
            pass_index=1,
        )

        assert evidence.delete_completed is True
        assert evidence.verified_absent is False
        assert "qdrant.evidence_delete_remaining" in evidence.issues
        assert "qdrant.evidence_scoped_points_remaining" in evidence.issues

    asyncio.run(run())


def test_qdrant_evidence_rejects_projection_scope_mismatch_before_provider_access() -> None:
    client = _EvidenceClient((_record("chunk_1"),))
    adapter = _adapter(client)
    wrong_scope = VectorProjectionScope(
        space_id="space_1",
        memory_scope_id="memory_scope_1",
        thread_id=None,
        projection_version="v2",
    )

    with pytest.raises(ValueError, match="configured projection"):
        asyncio.run(
            adapter.observe_exact(
                scope=wrong_scope,
                chunk_ids=("chunk_1",),
            )
        )

    assert client.retrieve_calls == []
