"""Optional Qdrant vector index adapter.

Qdrant is a derived index. Every result must be hydrated through Postgres before
it is rendered or returned to callers.
"""

from __future__ import annotations

import inspect
from uuid import NAMESPACE_URL, uuid5

from memo_stack_core.ports.adapters import (
    AdapterCapabilities,
    PortDiagnostic,
    PortStatus,
    VectorCandidate,
    VectorSearchResult,
    VectorUpsertItem,
    VectorWriteResult,
)


class QdrantDimensionMismatchError(RuntimeError):
    pass


class QdrantVectorMemoryAdapter:
    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        api_key: str | None = None,
        vector_size: int = 1536,
        projection_version: str = "v1",
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._collection_name = collection_name
        self._vector_size = vector_size
        self._projection_version = projection_version

    async def capabilities(self) -> AdapterCapabilities:
        client = None
        try:
            client, _models = await self._client()
        except Exception:
            return AdapterCapabilities(
                name="qdrant",
                enabled=False,
                healthy=False,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                degraded_reason="qdrant_sdk_missing",
            )
        try:
            if await client.collection_exists(self._collection_name):
                existing_size = await self._existing_vector_size(client)
                if existing_size is not None and existing_size != self._vector_size:
                    return AdapterCapabilities(
                        name="qdrant",
                        enabled=True,
                        healthy=False,
                        supports_upsert=False,
                        supports_delete=True,
                        supports_search=False,
                        supports_filters=True,
                        degraded_reason="qdrant.dimension_mismatch",
                    )
        except Exception:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=False,
                supports_upsert=False,
                supports_delete=False,
                supports_search=False,
                supports_filters=False,
                degraded_reason="qdrant_unavailable",
            )
        finally:
            await _close_client(client)
        return AdapterCapabilities(
            name="qdrant",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
        )

    async def upsert_chunks(self, items: tuple[VectorUpsertItem, ...]) -> VectorWriteResult:
        if not items:
            return VectorWriteResult.ok(0)
        client = None
        try:
            client, models = await self._client()
            await self._ensure_collection(client, models)
            points = [
                models.PointStruct(
                    id=str(uuid5(NAMESPACE_URL, item.chunk_id)),
                    vector=list(item.vector),
                    payload={
                        "chunk_id": item.chunk_id,
                        "space_id": item.space_id,
                        "profile_id": item.profile_id,
                        "thread_id": item.thread_id,
                        "projection_version": item.projection_version,
                        **item.metadata,
                    },
                )
                for item in items
            ]
            await client.upsert(collection_name=self._collection_name, points=points, wait=True)
            return VectorWriteResult.ok(len(points))
        except QdrantDimensionMismatchError:
            return VectorWriteResult.degraded("qdrant.dimension_mismatch", retryable=False)
        except Exception:
            return VectorWriteResult.degraded("qdrant.upsert_failed", retryable=True)
        finally:
            await _close_client(client)

    async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> VectorWriteResult:
        if not chunk_ids:
            return VectorWriteResult.ok(0)
        client = None
        try:
            client, models = await self._client()
            if not await client.collection_exists(self._collection_name):
                return VectorWriteResult.ok(0)
            point_ids = [str(uuid5(NAMESPACE_URL, chunk_id)) for chunk_id in chunk_ids]
            await client.delete(
                collection_name=self._collection_name,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True,
            )
            return VectorWriteResult.ok(len(chunk_ids))
        except Exception:
            return VectorWriteResult.degraded("qdrant.delete_failed", retryable=True)
        finally:
            await _close_client(client)

    async def search_chunks(
        self,
        *,
        space_id: str,
        profile_ids: tuple[str, ...],
        thread_id: str | None = None,
        query_vector: tuple[float, ...],
        limit: int,
    ) -> VectorSearchResult:
        if limit <= 0:
            return VectorSearchResult.ok(())
        if not query_vector:
            return VectorSearchResult.degraded("qdrant.empty_query_vector", retryable=False)
        client = None
        try:
            client, models = await self._client()
            await self._ensure_collection(client, models)
            must_conditions = [
                models.FieldCondition(key="space_id", match=models.MatchValue(value=space_id)),
                models.FieldCondition(
                    key="projection_version",
                    match=models.MatchValue(value=self._projection_version),
                ),
                models.FieldCondition(
                    key="profile_id",
                    match=models.MatchAny(any=list(profile_ids)),
                ),
            ]
            filter_kwargs = {"must": must_conditions}
            if thread_id is not None:
                filter_kwargs["min_should"] = models.MinShould(
                    conditions=[
                        models.FieldCondition(
                            key="thread_id",
                            match=models.MatchValue(value=thread_id),
                        ),
                        models.IsNullCondition(is_null=models.PayloadField(key="thread_id")),
                        models.IsEmptyCondition(is_empty=models.PayloadField(key="thread_id")),
                    ],
                    min_count=1,
                )
            query_filter = models.Filter(**filter_kwargs)
            results = await self._search(client, models, query_vector, query_filter, limit)
            candidates = [
                VectorCandidate(
                    chunk_id=str(point.payload.get("chunk_id", "")),
                    space_id=str(point.payload.get("space_id", "")),
                    profile_id=str(point.payload.get("profile_id", "")),
                    score=float(point.score),
                    projection_version=str(point.payload.get("projection_version", "")),
                    preview=None,
                )
                for point in results
                if point.payload and point.payload.get("chunk_id")
            ]
            return VectorSearchResult.ok(candidates)
        except QdrantDimensionMismatchError:
            return VectorSearchResult.degraded("qdrant.dimension_mismatch", retryable=False)
        except Exception:
            return VectorSearchResult(
                status=PortStatus.DEGRADED,
                items=(),
                diagnostics=(
                    PortDiagnostic(
                        code="qdrant.search_failed",
                        safe_message="Vector retrieval degraded",
                        retryable=True,
                    ),
                ),
            )
        finally:
            await _close_client(client)

    async def _client(self):
        from qdrant_client import AsyncQdrantClient, models

        return AsyncQdrantClient(url=self._url, api_key=self._api_key), models

    async def _search(self, client, models, query_vector, query_filter, limit):
        if hasattr(client, "query_points"):
            response = await client.query_points(
                collection_name=self._collection_name,
                query=list(query_vector),
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return getattr(response, "points", response)
        return await client.search(
            collection_name=self._collection_name,
            query_vector=list(query_vector),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    async def _ensure_collection(self, client, models) -> None:
        exists = await client.collection_exists(self._collection_name)
        if exists:
            existing_size = await self._existing_vector_size(client)
            if existing_size is not None and existing_size != self._vector_size:
                raise QdrantDimensionMismatchError
            return
        await client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=self._vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    async def _existing_vector_size(self, client) -> int | None:
        get_collection = getattr(client, "get_collection", None)
        if get_collection is None:
            return None
        collection = await get_collection(collection_name=self._collection_name)
        return _vector_size_from_collection(collection)


def _vector_size_from_collection(collection: object) -> int | None:
    config = getattr(collection, "config", None)
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    return _vector_size_from_vectors(vectors)


def _vector_size_from_vectors(vectors: object) -> int | None:
    if vectors is None:
        return None
    size = getattr(vectors, "size", None)
    if isinstance(size, int):
        return size
    kwargs = getattr(vectors, "kwargs", None)
    if isinstance(kwargs, dict) and isinstance(kwargs.get("size"), int):
        return int(kwargs["size"])
    if isinstance(vectors, dict):
        for value in vectors.values():
            nested_size = _vector_size_from_vectors(value)
            if nested_size is not None:
                return nested_size
    return None


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    for method_name in ("aclose", "close"):
        close = getattr(client, method_name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return
