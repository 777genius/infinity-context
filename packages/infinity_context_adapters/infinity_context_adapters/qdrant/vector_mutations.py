"""Qdrant vector mutations kept separate from retrieval orchestration."""

from __future__ import annotations

from infinity_context_core.ports.adapters import VectorWriteResult

from infinity_context_adapters.qdrant.generation_fence import (
    QdrantCanonicalVersionError,
    delete_older_or_unversioned,
    generic_point_id_for_write,
)
from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk
from infinity_context_adapters.qdrant.locator_profile import QdrantLocatorPayloadError
from infinity_context_adapters.qdrant.vector_schema import (
    QdrantDimensionMismatchError,
    QdrantDistanceMismatchError,
    QdrantHybridSchemaMismatchError,
    QdrantHybridUnsupportedError,
    QdrantSparseEncodingError,
)


class QdrantVectorMutationMixin:
    """Provider mutation methods shared by generic and profile collections."""

    async def upsert_chunks(self, items):
        if not items:
            return VectorWriteResult.ok(0)
        client = None
        try:
            payloads = [self._vector_payload(item) for item in items]
            client, models = await self._client()
            await self._ensure_collection(client, models)
            points = [
                models.PointStruct(
                    id=(
                        qdrant_point_id_for_chunk(item.chunk_id)
                        if self._locator_profile_enabled
                        else generic_point_id_for_write(item)
                    ),
                    vector=self._point_vector(models, item),
                    payload=payload,
                )
                for item, payload in zip(items, payloads, strict=True)
            ]
            await client.upsert(collection_name=self._collection_name, points=points, wait=True)
            if not self._locator_profile_enabled:
                for item, payload in zip(items, payloads, strict=True):
                    await delete_older_or_unversioned(
                        client,
                        models,
                        collection_name=self._collection_name,
                        chunk_ids=(item.chunk_id,),
                        canonical_version=int(payload["canonical_version"]),
                        preserve_stable=True,
                    )
            return VectorWriteResult.ok(len(points))
        except QdrantLocatorPayloadError:
            return VectorWriteResult.degraded("qdrant.locator_profile_invalid", retryable=False)
        except QdrantCanonicalVersionError:
            return VectorWriteResult.degraded("qdrant.canonical_version_invalid", retryable=False)
        except QdrantDimensionMismatchError:
            return VectorWriteResult.degraded("qdrant.dimension_mismatch", retryable=False)
        except QdrantDistanceMismatchError:
            return VectorWriteResult.degraded("qdrant.distance_mismatch", retryable=False)
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

    async def delete_chunks_if_version(
        self,
        chunk_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> VectorWriteResult:
        """Delete only stable points still carrying the tombstoned version."""

        if not chunk_ids:
            return VectorWriteResult.ok(0)
        client = None
        try:
            client, models = await self._client()
            if not await client.collection_exists(self._collection_name):
                return VectorWriteResult.ok(0)
            point_ids = [qdrant_point_id_for_chunk(chunk_id) for chunk_id in chunk_ids]
            selector = models.FilterSelector(
                filter=models.Filter(
                    must=(
                        models.HasIdCondition(has_id=point_ids),
                        models.FieldCondition(
                            key="canonical_version",
                            match=models.MatchValue(value=canonical_version),
                        ),
                    )
                )
            )
            await client.delete(
                collection_name=self._collection_name,
                points_selector=selector,
                wait=True,
            )
            remaining = await client.retrieve(
                collection_name=self._collection_name,
                ids=point_ids,
                with_payload=["canonical_version"],
                with_vectors=False,
                consistency="all",
            )
            diagnostic = _versioned_delete_observation_diagnostic(
                remaining,
                expected_point_ids=set(point_ids),
                canonical_version=canonical_version,
            )
            if diagnostic is not None:
                code, retryable = diagnostic
                return VectorWriteResult.degraded(code, retryable=retryable)
            return VectorWriteResult.ok(len(chunk_ids))
        except Exception:
            return VectorWriteResult.degraded("qdrant.delete_failed", retryable=True)
        finally:
            await _close_client(client)

    async def delete_chunks_before_version(
        self,
        chunk_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> VectorWriteResult:
        """Repair legacy/unversioned and older generic points from canonical truth."""

        if not chunk_ids:
            return VectorWriteResult.ok(0)
        client = None
        try:
            client, models = await self._client()
            if not await client.collection_exists(self._collection_name):
                return VectorWriteResult.ok(0)
            await delete_older_or_unversioned(
                client,
                models,
                collection_name=self._collection_name,
                chunk_ids=chunk_ids,
                canonical_version=canonical_version,
                preserve_stable=False,
            )
            return VectorWriteResult.ok(len(chunk_ids))
        except Exception:
            return VectorWriteResult.degraded("qdrant.rebuild_delete_failed", retryable=True)
        finally:
            await _close_client(client)


def _versioned_delete_observation_diagnostic(
    records: object,
    *,
    expected_point_ids: set[str],
    canonical_version: int,
) -> tuple[str, bool] | None:
    """Prove the requested generation absent without accepting legacy points."""

    if not isinstance(records, (list, tuple)):
        return ("qdrant.delete_observation_failed", True)
    observed_ids: set[str] = set()
    for record in records:
        point_id = str(getattr(record, "id", ""))
        if not point_id or point_id not in expected_point_ids or point_id in observed_ids:
            return ("qdrant.delete_observation_failed", True)
        observed_ids.add(point_id)
        payload = getattr(record, "payload", None)
        if not isinstance(payload, dict):
            return ("qdrant.delete_rebuild_required", False)
        observed_version = payload.get("canonical_version")
        if (
            not isinstance(observed_version, int)
            or isinstance(observed_version, bool)
            or not 1 <= observed_version <= 9_007_199_254_740_991
        ):
            return ("qdrant.delete_rebuild_required", False)
        if observed_version < canonical_version:
            return ("qdrant.delete_rebuild_required", False)
        if observed_version == canonical_version:
            return ("qdrant.delete_generation_remaining", True)
    return None


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    for method_name in ("aclose", "close"):
        close = getattr(client, method_name, None)
        if not callable(close):
            continue
        result = close()
        if hasattr(result, "__await__"):
            await result
        return


__all__ = ("QdrantVectorMutationMixin",)
