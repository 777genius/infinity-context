"""Optional derived Qdrant vector index adapter."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    PortDiagnostic,
    PortStatus,
    VectorCandidate,
    VectorSearchResult,
    VectorUpsertItem,
)
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkProjectionPassReceipt,
    BenchmarkUnsealedProjectionScope,
)
from infinity_context_core.ports.vector_projection_evidence import (
    VectorProjectionDeleteEvidence,
    VectorProjectionPresenceEvidence,
    VectorProjectionScope,
)

from infinity_context_adapters.qdrant.generation_fence import QdrantCanonicalVersionError
from infinity_context_adapters.qdrant.identity_evidence import (
    QdrantIdentityEvidence,
    qdrant_point_id_for_chunk,
)
from infinity_context_adapters.qdrant.locator_profile import (
    LOCATOR_PAYLOAD_SCHEMA,
    QdrantLocatorPayloadError,
    locator_payload,
    payload_schema_matches,
    validate_locator_payload,
)
from infinity_context_adapters.qdrant.locator_runtime import (
    locator_points_absent as _locator_points_absent,
)
from infinity_context_adapters.qdrant.locator_runtime import (
    locator_profile_attestation as _locator_profile_attestation,
)
from infinity_context_adapters.qdrant.locator_runtime import (
    locator_profile_attestation_page as _locator_profile_attestation_page,
)
from infinity_context_adapters.qdrant.locator_runtime import (
    locator_profile_complete as _locator_profile_complete,
)
from infinity_context_adapters.qdrant.locator_runtime import (
    search_locator_chunks as _search_locator_chunks,
)
from infinity_context_adapters.qdrant.vector_mutations import QdrantVectorMutationMixin
from infinity_context_adapters.qdrant.vector_schema import (
    QdrantDimensionMismatchError,
    QdrantDistanceMismatchError,
    QdrantHybridSchemaMismatchError,
    QdrantHybridUnsupportedError,
    QdrantSparseEncodingError,
)
from infinity_context_adapters.qdrant.vector_schema import (
    is_loopback_url as _is_loopback_url,
)
from infinity_context_adapters.qdrant.vector_schema import (
    mapping_from_object as _mapping_from_object,
)
from infinity_context_adapters.qdrant.vector_schema import (
    sparse_vector_exists as _sparse_vector_exists,
)
from infinity_context_adapters.qdrant.vector_schema import (
    sparse_vector_params as _sparse_vector_params,
)
from infinity_context_adapters.qdrant.vector_schema import (
    vector_distance_from_collection as _vector_distance_from_collection,
)
from infinity_context_adapters.qdrant.vector_schema import (
    vector_size_from_collection as _vector_size_from_collection,
)

_FUSION_RANK_CONSTANT = 60.0


@dataclass(frozen=True)
class _FusedPoint:
    payload: object
    score: float


class QdrantVectorMemoryAdapter(QdrantVectorMutationMixin):
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
        index_profile_digest: str | None = None,
        index_generation: str | None = None,
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
        self._index_profile_digest = index_profile_digest
        self._index_generation = index_generation
        self._identity_evidence = QdrantIdentityEvidence(
            client_factory=lambda: self._client(),
            url=url,
            collection_name=collection_name,
            projection_version=projection_version,
        )

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
                if existing_size != self._vector_size:
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
                    _vector_distance_from_collection(
                        collection,
                        vector_name=self._dense_vector_name
                        if self._hybrid_sparse_enabled
                        else None,
                    )
                    != "cosine"
                ):
                    return AdapterCapabilities(
                        name="qdrant",
                        enabled=True,
                        healthy=False,
                        supports_upsert=False,
                        supports_delete=True,
                        supports_search=False,
                        supports_filters=True,
                        degraded_reason="qdrant.distance_mismatch",
                    )
                if self._locator_profile_enabled and not payload_schema_matches(collection):
                    return AdapterCapabilities(
                        name="qdrant",
                        enabled=True,
                        healthy=False,
                        supports_upsert=False,
                        supports_delete=True,
                        supports_search=False,
                        supports_filters=False,
                        degraded_reason="qdrant.locator_payload_schema_unverified",
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
            else:
                return AdapterCapabilities(
                    name="qdrant",
                    enabled=True,
                    healthy=False,
                    supports_upsert=False,
                    supports_delete=False,
                    supports_search=False,
                    supports_filters=False,
                    degraded_reason="qdrant.collection_unverified",
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

    async def observe_chunk_versions(self, chunk_ids: tuple[str, ...]) -> tuple[int | None, ...]:
        """Read the actual projected generation for deterministic chunk point ids."""

        if not chunk_ids:
            return ()
        client = None
        try:
            client, _ = await self._client()
            if not await client.collection_exists(self._collection_name):
                return tuple(None for _ in chunk_ids)
            return await _retrieve_canonical_versions(
                client,
                collection_name=self._collection_name,
                point_ids=tuple(qdrant_point_id_for_chunk(item) for item in chunk_ids),
            )
        except Exception as exc:
            raise RuntimeError("qdrant.observe_canonical_version_failed") from exc
        finally:
            await _close_client(client)
    @property
    def target_commitment_sha256(self) -> str:
        return self._identity_evidence.target_commitment_sha256

    async def observe_exact(
        self,
        *,
        scope: VectorProjectionScope,
        chunk_ids: tuple[str, ...],
    ) -> VectorProjectionPresenceEvidence:
        return await self._identity_evidence.observe_exact(
            scope=scope,
            chunk_ids=chunk_ids,
        )

    async def delete_and_observe_exact(
        self,
        *,
        scope: VectorProjectionScope,
        chunk_ids: tuple[str, ...],
        pass_index: int,
    ) -> VectorProjectionDeleteEvidence:
        return await self._identity_evidence.delete_and_observe_exact(
            scope=scope,
            chunk_ids=chunk_ids,
            pass_index=pass_index,
        )

    async def delete_benchmark_space_two_pass(
        self,
        *,
        space_id: str,
        scopes: tuple[BenchmarkUnsealedProjectionScope, ...],
    ) -> tuple[BenchmarkProjectionPassReceipt, BenchmarkProjectionPassReceipt]:
        return await self._identity_evidence.delete_benchmark_space_two_pass(
            space_id=space_id,
            scopes=scopes,
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
        if limit <= 0:
            return VectorSearchResult.ok(())
        if not query_vector:
            return VectorSearchResult.degraded("qdrant.empty_query_vector", retryable=False)
        client = None
        try:
            client, models = await self._client()
            if self._locator_profile_enabled:
                await self._require_collection(client)
            else:
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
            if not self._locator_profile_enabled:
                must_conditions.append(
                    models.FieldCondition(
                        key="generic_identity_version",
                        match=models.MatchValue(value="stable.v1"),
                    )
                )
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
        except QdrantDistanceMismatchError:
            return VectorSearchResult.degraded("qdrant.distance_mismatch", retryable=False)
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

    async def search_locator_chunks(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        query_vector: tuple[float, ...],
        query_text: str,
        limit: int,
        filter_spec: dict[str, object],
    ) -> tuple[dict[str, object], ...]:
        return await _search_locator_chunks(
            self,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            query_vector=query_vector,
            query_text=query_text,
            limit=limit,
            filter_spec=filter_spec,
        )

    @property
    def _locator_profile_enabled(self) -> bool:
        return bool(self._index_profile_digest and self._index_generation)

    async def locator_profile_complete(self, expected: tuple[object, ...]) -> bool:
        return await _locator_profile_complete(self, expected)

    async def locator_profile_attestation(self) -> tuple[int, str]:
        return await _locator_profile_attestation(self)

    async def locator_profile_attestation_page(
        self, *, cursor: str | None, limit: int
    ) -> tuple[tuple[tuple[str, int, str], ...], str | None]:
        return await _locator_profile_attestation_page(self, cursor=cursor, limit=limit)

    async def locator_points_absent(self, chunk_ids: tuple[str, ...]) -> bool | None:
        return await _locator_points_absent(self, chunk_ids)

    async def _client(self):
        from qdrant_client import AsyncQdrantClient, models

        return (
            AsyncQdrantClient(
                url=self._url,
                api_key=self._api_key,
                timeout=10,
                trust_env=not _is_loopback_url(self._url),
            ),
            models,
        )

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
            if existing_size != self._vector_size:
                raise QdrantDimensionMismatchError
            if (
                _vector_distance_from_collection(
                    collection,
                    vector_name=self._dense_vector_name if self._hybrid_sparse_enabled else None,
                )
                != "cosine"
            ):
                raise QdrantDistanceMismatchError
            if (
                self._hybrid_sparse_enabled
                and collection is not None
                and (
                    existing_size is None
                    or not _sparse_vector_exists(collection, self._sparse_vector_name)
                )
            ):
                raise QdrantHybridSchemaMismatchError
            if self._locator_profile_enabled:
                await self._ensure_payload_indexes(client, models)
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
            if self._locator_profile_enabled:
                await self._ensure_payload_indexes(client, models)
            return
        await client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(
                size=self._vector_size,
                distance=models.Distance.COSINE,
            ),
        )
        if self._locator_profile_enabled:
            await self._ensure_payload_indexes(client, models)

    async def _ensure_payload_indexes(self, client, models) -> None:
        schema_type = getattr(models, "PayloadSchemaType", None)
        if schema_type is None or not hasattr(client, "create_payload_index"):
            raise QdrantLocatorPayloadError("Qdrant payload indexes are unsupported")
        collection = await self._get_collection_info(client)
        raw_schema = _mapping_from_object(getattr(collection, "payload_schema", None)) or {}
        for field_name, field_type in LOCATOR_PAYLOAD_SCHEMA.items():
            existing = raw_schema.get(field_name)
            if existing is not None:
                data_type = getattr(existing, "data_type", existing)
                normalized = str(getattr(data_type, "value", data_type)).casefold()
                if normalized != field_type:
                    raise QdrantLocatorPayloadError(
                        f"Qdrant payload index type mismatch for {field_name}"
                    )
                continue
            await client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=getattr(schema_type, field_type.upper()),
                wait=True,
            )

    async def _require_collection(self, client) -> None:
        """Validate a locator collection without performing a read-path mutation."""

        if not await client.collection_exists(self._collection_name):
            raise QdrantLocatorPayloadError("Qdrant locator collection is absent")
        collection = await self._get_collection_info(client)
        if (
            _vector_size_from_collection(
                collection,
                vector_name=self._dense_vector_name if self._hybrid_sparse_enabled else None,
            )
            != self._vector_size
        ):
            raise QdrantDimensionMismatchError
        if (
            _vector_distance_from_collection(
                collection,
                vector_name=self._dense_vector_name if self._hybrid_sparse_enabled else None,
            )
            != "cosine"
        ):
            raise QdrantDistanceMismatchError
        if not payload_schema_matches(collection):
            raise QdrantLocatorPayloadError("Qdrant locator payload schema is incomplete")

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

    def _vector_payload(self, item: VectorUpsertItem) -> dict[str, object]:
        payload = locator_payload(item)
        if self._locator_profile_enabled:
            payload.pop("chunk_id", None)
            payload["index_profile_digest"] = self._index_profile_digest
            payload["index_generation"] = self._index_generation
            return validate_locator_payload(
                payload,
                projection_version=self._projection_version,
                index_profile_digest=self._index_profile_digest or "",
                index_generation=self._index_generation or "",
            )
        version = payload.get("canonical_version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or not 1 <= version <= 9_007_199_254_740_991
        ):
            raise QdrantCanonicalVersionError
        payload["generic_identity_version"] = "stable.v1"
        return payload

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


async def _retrieve_canonical_versions(
    client: object,
    *,
    collection_name: str,
    point_ids: tuple[str, ...],
) -> tuple[int | None, ...]:
    observed = await client.retrieve(
        collection_name=collection_name,
        ids=list(point_ids),
        with_payload=["canonical_version"],
        with_vectors=False,
    )
    versions: dict[str, int] = {}
    for point in observed:
        point_id = str(getattr(point, "id", ""))
        payload = getattr(point, "payload", None)
        version = payload.get("canonical_version") if isinstance(payload, dict) else None
        if (
            point_id not in point_ids
            or point_id in versions
            or not isinstance(version, int)
            or isinstance(version, bool)
            or not 1 <= version <= 9_007_199_254_740_991
        ):
            raise RuntimeError("qdrant.canonical_version_observation_invalid")
        versions[point_id] = version
    return tuple(versions.get(point_id) for point_id in point_ids)
