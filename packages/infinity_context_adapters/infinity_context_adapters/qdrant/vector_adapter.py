"""Optional Qdrant vector index adapter.

Qdrant is a derived index. Every result must be hydrated through Postgres before
it is rendered or returned to callers.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from infinity_context_core.ports.adapters import (
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


class QdrantHybridSchemaMismatchError(RuntimeError):
    pass


class QdrantHybridUnsupportedError(RuntimeError):
    pass


class QdrantSparseEncodingError(RuntimeError):
    pass


_FUSION_RANK_CONSTANT = 60.0


@dataclass(frozen=True)
class _FusedPoint:
    payload: object
    score: float


class QdrantVectorMemoryAdapter:
    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        api_key: str | None = None,
        vector_size: int = 1536,
        projection_version: str = "v1",
        hybrid_sparse_enabled: bool = False,
        sparse_model: str = "Qdrant/bm25",
        dense_vector_name: str = "dense",
        sparse_vector_name: str = "bm25",
        sparse_encoder_factory: Callable[[], object] | None = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._collection_name = collection_name
        self._vector_size = vector_size
        self._projection_version = projection_version
        self._hybrid_sparse_enabled = hybrid_sparse_enabled
        self._sparse_model = sparse_model
        self._dense_vector_name = dense_vector_name
        self._sparse_vector_name = sparse_vector_name
        self._sparse_encoder_factory = sparse_encoder_factory
        self._sparse_encoder: object | None = None

    async def capabilities(self) -> AdapterCapabilities:
        client = None
        try:
            client, models = await self._client()
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
            if self._hybrid_sparse_enabled:
                self._ensure_hybrid_supported(models)
                self._ensure_sparse_encoder_available_for_health()
            if await client.collection_exists(self._collection_name):
                collection = await self._get_collection_info(client)
                existing_size = _vector_size_from_collection(
                    collection,
                    vector_name=self._dense_vector_name if self._hybrid_sparse_enabled else None,
                )
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
                if (
                    self._hybrid_sparse_enabled
                    and collection is not None
                    and (
                        existing_size is None
                        or not _sparse_vector_exists(collection, self._sparse_vector_name)
                    )
                ):
                    return AdapterCapabilities(
                        name="qdrant",
                        enabled=True,
                        healthy=False,
                        supports_upsert=False,
                        supports_delete=True,
                        supports_search=False,
                        supports_filters=True,
                        degraded_reason="qdrant.hybrid_schema_mismatch",
                    )
        except QdrantHybridUnsupportedError:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=False,
                supports_upsert=False,
                supports_delete=True,
                supports_search=False,
                supports_filters=True,
                degraded_reason="qdrant.hybrid_unsupported",
            )
        except QdrantSparseEncodingError:
            return AdapterCapabilities(
                name="qdrant",
                enabled=True,
                healthy=False,
                supports_upsert=False,
                supports_delete=True,
                supports_search=False,
                supports_filters=True,
                degraded_reason="qdrant.sparse_encoder_unavailable",
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
                    vector=self._point_vector(models, item),
                    payload={
                        "chunk_id": item.chunk_id,
                        "space_id": item.space_id,
                        "memory_scope_id": item.memory_scope_id,
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
        except QdrantHybridSchemaMismatchError:
            return VectorWriteResult.degraded("qdrant.hybrid_schema_mismatch", retryable=False)
        except QdrantHybridUnsupportedError:
            return VectorWriteResult.degraded("qdrant.hybrid_unsupported", retryable=False)
        except QdrantSparseEncodingError:
            return VectorWriteResult.degraded("qdrant.sparse_encoding_failed", retryable=True)
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
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None = None,
        query_vector: tuple[float, ...],
        query_text: str | None = None,
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
                    key="memory_scope_id",
                    match=models.MatchAny(any=list(memory_scope_ids)),
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
            results = await self._search(
                client,
                models,
                query_vector,
                query_text,
                query_filter,
                limit,
            )
            candidates = [
                VectorCandidate(
                    chunk_id=str(point.payload.get("chunk_id", "")),
                    space_id=str(point.payload.get("space_id", "")),
                    memory_scope_id=str(point.payload.get("memory_scope_id", "")),
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
        except QdrantHybridSchemaMismatchError:
            return VectorSearchResult.degraded("qdrant.hybrid_schema_mismatch", retryable=False)
        except QdrantHybridUnsupportedError:
            return VectorSearchResult.degraded("qdrant.hybrid_unsupported", retryable=False)
        except QdrantSparseEncodingError:
            return VectorSearchResult.degraded("qdrant.sparse_encoding_failed", retryable=True)
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

    async def _search(self, client, models, query_vector, query_text, query_filter, limit):
        if self._hybrid_sparse_enabled:
            dense_results = await self._dense_search(
                client,
                query_vector,
                query_filter,
                limit,
                vector_name=self._dense_vector_name,
            )
            normalized_query_text = " ".join((query_text or "").split())
            if not normalized_query_text:
                return dense_results
            sparse_query = self._sparse_vector_for_text(
                models,
                normalized_query_text,
                is_query=True,
            )
            if sparse_query is None:
                raise QdrantSparseEncodingError
            sparse_results = await self._sparse_search(
                client,
                sparse_query,
                query_filter,
                limit,
            )
            return _fuse_result_sets((dense_results, sparse_results), limit=limit)
        return await self._dense_search(client, query_vector, query_filter, limit)

    async def _dense_search(self, client, query_vector, query_filter, limit, *, vector_name=None):
        if hasattr(client, "query_points"):
            kwargs = {
                "collection_name": self._collection_name,
                "query": list(query_vector),
                "query_filter": query_filter,
                "limit": limit,
                "with_payload": True,
            }
            if vector_name is not None:
                kwargs["using"] = vector_name
            response = await client.query_points(**kwargs)
            return _points_from_response(response)
        if vector_name is not None:
            raise QdrantHybridUnsupportedError
        return await client.search(
            collection_name=self._collection_name,
            query_vector=list(query_vector),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    async def _sparse_search(self, client, sparse_query, query_filter, limit):
        if not hasattr(client, "query_points"):
            raise QdrantHybridUnsupportedError
        response = await client.query_points(
            collection_name=self._collection_name,
            query=sparse_query,
            using=self._sparse_vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return _points_from_response(response)

    async def _ensure_collection(self, client, models) -> None:
        exists = await client.collection_exists(self._collection_name)
        if exists:
            collection = await self._get_collection_info(client)
            existing_size = _vector_size_from_collection(
                collection,
                vector_name=self._dense_vector_name if self._hybrid_sparse_enabled else None,
            )
            if existing_size is not None and existing_size != self._vector_size:
                raise QdrantDimensionMismatchError
            if (
                self._hybrid_sparse_enabled
                and collection is not None
                and (
                    existing_size is None
                    or not _sparse_vector_exists(collection, self._sparse_vector_name)
                )
            ):
                raise QdrantHybridSchemaMismatchError
            return
        if self._hybrid_sparse_enabled:
            self._ensure_hybrid_supported(models)
            await client.create_collection(
                collection_name=self._collection_name,
                vectors_config={
                    self._dense_vector_name: models.VectorParams(
                        size=self._vector_size,
                        distance=models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    self._sparse_vector_name: _sparse_vector_params(models),
                },
            )
            return
        await client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=self._vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    async def _existing_vector_size(self, client) -> int | None:
        collection = await self._get_collection_info(client)
        return _vector_size_from_collection(
            collection,
            vector_name=self._dense_vector_name if self._hybrid_sparse_enabled else None,
        )

    async def _get_collection_info(self, client) -> object | None:
        get_collection = getattr(client, "get_collection", None)
        if get_collection is None:
            return None
        return await get_collection(collection_name=self._collection_name)

    def _point_vector(self, models, item: VectorUpsertItem):
        if not self._hybrid_sparse_enabled:
            return list(item.vector)
        vector = {self._dense_vector_name: list(item.vector)}
        if item.text.strip():
            sparse_vector = self._sparse_vector_for_text(models, item.text, is_query=False)
            if sparse_vector is None:
                raise QdrantSparseEncodingError
            vector[self._sparse_vector_name] = sparse_vector
        return vector

    def _sparse_vector_for_text(self, models, text: str, *, is_query: bool):
        sparse_vector = getattr(models, "SparseVector", None)
        if sparse_vector is None:
            raise QdrantHybridUnsupportedError
        embedding = self._encode_sparse_text(text, is_query=is_query)
        indices = _sparse_embedding_values(embedding, "indices", value_type=int)
        values = _sparse_embedding_values(embedding, "values", value_type=float)
        if not indices and not values:
            return None
        if len(indices) != len(values):
            raise QdrantSparseEncodingError
        return sparse_vector(indices=indices, values=values)

    def _encode_sparse_text(self, text: str, *, is_query: bool) -> object:
        encoder = self._load_sparse_encoder()
        texts = [text]
        if is_query and hasattr(encoder, "query_embed"):
            result = _call_sparse_embedding_method(
                encoder.query_embed,
                texts,
                query_method=True,
            )
        elif hasattr(encoder, "embed"):
            result = _call_sparse_embedding_method(
                encoder.embed,
                texts,
                query_method=False,
            )
        else:
            raise QdrantSparseEncodingError
        return _first_sparse_embedding(result)

    def _load_sparse_encoder(self) -> object:
        if self._sparse_encoder is not None:
            return self._sparse_encoder
        if self._sparse_encoder_factory is not None:
            self._sparse_encoder = self._sparse_encoder_factory()
            return self._sparse_encoder
        try:
            from fastembed import SparseTextEmbedding
        except Exception as exc:
            raise QdrantSparseEncodingError from exc
        self._sparse_encoder = SparseTextEmbedding(model_name=self._sparse_model)
        return self._sparse_encoder

    def _ensure_hybrid_supported(self, models) -> None:
        if not hasattr(models, "SparseVector") or not hasattr(models, "SparseVectorParams"):
            raise QdrantHybridUnsupportedError

    def _ensure_sparse_encoder_available_for_health(self) -> None:
        if self._sparse_encoder is not None or self._sparse_encoder_factory is not None:
            return
        try:
            from fastembed import SparseTextEmbedding  # noqa: F401
        except Exception as exc:
            raise QdrantSparseEncodingError from exc


def _vector_size_from_collection(
    collection: object | None,
    *,
    vector_name: str | None = None,
) -> int | None:
    if collection is None:
        return None
    config = getattr(collection, "config", None)
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    return _vector_size_from_vectors(vectors, vector_name=vector_name)


def _vector_size_from_vectors(vectors: object, *, vector_name: str | None = None) -> int | None:
    if vectors is None:
        return None
    if vector_name is not None:
        named_vectors = _mapping_from_object(vectors)
        if named_vectors is None or vector_name not in named_vectors:
            return None
        return _vector_size_from_vectors(named_vectors[vector_name])
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


def _sparse_vector_exists(collection: object, vector_name: str) -> bool:
    config = getattr(collection, "config", None)
    params = getattr(config, "params", None)
    sparse_vectors = getattr(params, "sparse_vectors", None)
    sparse_mapping = _mapping_from_object(sparse_vectors)
    return sparse_mapping is not None and vector_name in sparse_mapping


def _mapping_from_object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    kwargs = getattr(value, "kwargs", None)
    if isinstance(kwargs, dict):
        return kwargs
    return None


def _sparse_vector_params(models):
    params = getattr(models, "SparseVectorParams", None)
    if params is None:
        raise QdrantHybridUnsupportedError
    modifier = getattr(getattr(models, "Modifier", object), "IDF", None)
    if modifier is not None:
        try:
            return params(modifier=modifier)
        except TypeError:
            pass
    return params()


def _call_sparse_embedding_method(
    method: Callable[..., object],
    texts: list[str],
    *,
    query_method: bool,
):
    attempts: tuple[tuple[tuple[object, ...], dict[str, object]], ...]
    if query_method:
        attempts = (
            ((), {"query": texts}),
            ((), {"queries": texts}),
            ((), {"query": texts[0]}),
            ((texts,), {}),
            ((texts[0],), {}),
        )
    else:
        attempts = (
            ((), {"documents": texts}),
            ((texts,), {}),
        )
    last_error: TypeError | None = None
    for args, kwargs in attempts:
        try:
            return method(*args, **kwargs)
        except TypeError as exc:
            last_error = exc
    raise QdrantSparseEncodingError from last_error


def _first_sparse_embedding(result: object) -> object:
    if hasattr(result, "indices") and hasattr(result, "values"):
        return result
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
        for item in result:
            return item
    raise QdrantSparseEncodingError


def _sparse_embedding_values(embedding: object, field: str, *, value_type: type):
    value = getattr(embedding, field, None)
    if value is None and isinstance(embedding, dict):
        value = embedding.get(field)
    if value is None:
        raise QdrantSparseEncodingError
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [value_type(item) for item in value]


def _points_from_response(response: object) -> tuple[object, ...]:
    points = getattr(response, "points", response)
    return tuple(points)


def _fuse_result_sets(
    result_sets: tuple[tuple[object, ...], ...],
    *,
    limit: int,
) -> tuple[_FusedPoint, ...]:
    scores: dict[str, float] = {}
    best_original_scores: dict[str, float] = {}
    payloads: dict[str, object] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for result_set in result_sets:
        for rank, point in enumerate(result_set, start=1):
            payload = getattr(point, "payload", None)
            if not isinstance(payload, dict) or not payload.get("chunk_id"):
                continue
            key = str(payload["chunk_id"])
            scores[key] = scores.get(key, 0.0) + (1.0 / (_FUSION_RANK_CONSTANT + rank))
            best_original_scores[key] = max(
                best_original_scores.get(key, 0.0),
                float(getattr(point, "score", 0.0) or 0.0),
            )
            payloads.setdefault(key, payload)
            if key not in first_seen:
                first_seen[key] = order
                order += 1
    ranked = sorted(
        scores,
        key=lambda key: (-scores[key], -best_original_scores[key], first_seen[key]),
    )
    return tuple(_FusedPoint(payload=payloads[key], score=scores[key]) for key in ranked[:limit])


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
