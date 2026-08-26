"""Bounded Qdrant runtime operations for the Contract-C locator profile."""

import hashlib
import json
import math

from infinity_context_core.features.context_building.public import (
    accumulate_attestation_digest,
    finalize_attestation_digest,
)

from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk
from infinity_context_adapters.qdrant.locator_profile import (
    QdrantLocatorPayloadError,
    expected_locator_payload,
    locator_filter,
    payload_schema_matches,
    validate_locator_payload,
)


async def search_locator_chunks(
    adapter,
    *,
    space_id,
    memory_scope_id,
    thread_id,
    query_vector,
    query_text,
    limit,
    filter_spec,
):
    if not adapter._locator_profile_enabled:
        raise QdrantLocatorPayloadError("locator index profile is not configured")
    if limit <= 0:
        return ()
    if not query_vector:
        raise QdrantLocatorPayloadError("locator query vector is empty")
    client = None
    try:
        client, models = await adapter._client()
        await adapter._require_collection(client)
        thread_condition = (
            {"key": "thread_id", "is_null": True}
            if thread_id is None
            else {"key": "thread_id", "match": thread_id}
        )
        exact_spec = {
            "must": [
                *list(filter_spec.get("must", ())),
                {"key": "space_id", "match": space_id},
                {"key": "memory_scope_id", "match": memory_scope_id},
                thread_condition,
                {"key": "projection_version", "match": adapter._projection_version},
                {"key": "index_profile_digest", "match": adapter._index_profile_digest},
                {"key": "index_generation", "match": adapter._index_generation},
            ],
            "must_not": list(filter_spec.get("must_not", ())),
            "should": list(filter_spec.get("should", ())),
            "minimum_should_match": filter_spec.get("minimum_should_match"),
        }
        points = await adapter._search(
            client,
            models,
            query_vector,
            query_text,
            locator_filter(models, exact_spec),
            limit,
        )
        result = []
        for point in points:
            payload = validate_locator_payload(
                getattr(point, "payload", None),
                projection_version=adapter._projection_version or "",
                index_profile_digest=adapter._index_profile_digest or "",
                index_generation=adapter._index_generation or "",
            )
            identity = payload.get("canonical_identity")
            version = payload.get("canonical_version")
            if (
                not isinstance(identity, str)
                or not identity
                or not isinstance(version, int)
                or isinstance(version, bool)
                or version < 1
            ):
                raise QdrantLocatorPayloadError("locator point lacks canonical identity/version")
            result.append(
                {
                    "canonical_identity": identity,
                    "canonical_version": version,
                    "score": float(point.score),
                }
            )
        return tuple(result)
    finally:
        await _close_client(client)


async def locator_profile_complete(adapter, expected: tuple[object, ...]) -> bool:
    if not adapter._locator_profile_enabled:
        return False
    client = None
    try:
        client, models = await adapter._client()
        if not await client.collection_exists(adapter._collection_name):
            return False
        collection = await adapter._get_collection_info(client)
        if not payload_schema_matches(collection):
            return False
        exact_filter = locator_filter(
            models,
            {
                "must": [
                    {"key": "projection_version", "match": adapter._projection_version},
                    {"key": "index_profile_digest", "match": adapter._index_profile_digest},
                    {"key": "index_generation", "match": adapter._index_generation},
                ],
                "must_not": [],
            },
        )
        expected_payloads = {}
        for row in expected:
            payload = expected_locator_payload(
                row,
                projection_version=adapter._projection_version or "",
                index_profile_digest=adapter._index_profile_digest or "",
                index_generation=adapter._index_generation or "",
            )
            identity = payload["canonical_identity"]
            if identity in expected_payloads:
                return False
            expected_payloads[identity] = payload
        observed = {}
        offset = None
        while True:
            points, offset = await client.scroll(
                collection_name=adapter._collection_name,
                scroll_filter=exact_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = getattr(point, "payload", None)
                try:
                    payload = validate_locator_payload(
                        payload,
                        projection_version=adapter._projection_version or "",
                        index_profile_digest=adapter._index_profile_digest or "",
                        index_generation=adapter._index_generation or "",
                    )
                except QdrantLocatorPayloadError:
                    return False
                identity = payload.get("canonical_identity")
                if not isinstance(identity, str) or identity in observed:
                    return False
                if expected_payloads.get(identity) != payload:
                    return False
                observed[identity] = payload
            if offset is None:
                break
        return set(observed) == set(expected_payloads)
    except Exception:
        return False
    finally:
        await _close_client(client)


async def locator_profile_attestation(adapter) -> tuple[int, str]:
    """Return a deterministic digest of the actual derived profile payloads."""

    if not adapter._locator_profile_enabled:
        raise QdrantLocatorPayloadError("locator index profile is not configured")
    client = None
    try:
        client, models = await adapter._client()
        if not await client.collection_exists(adapter._collection_name):
            return 0, hashlib.sha256(b"").hexdigest()
        exact_filter = locator_filter(
            models,
            {
                "must": [
                    {"key": "projection_version", "match": adapter._projection_version},
                    {
                        "key": "index_profile_digest",
                        "match": adapter._index_profile_digest,
                    },
                    {"key": "index_generation", "match": adapter._index_generation},
                ],
                "must_not": [],
            },
        )
        accumulator = "0" * 64
        count = 0
        offset = None
        while True:
            points, offset = await client.scroll(
                collection_name=adapter._collection_name,
                scroll_filter=exact_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = validate_locator_payload(
                    getattr(point, "payload", None),
                    projection_version=adapter._projection_version or "",
                    index_profile_digest=adapter._index_profile_digest or "",
                    index_generation=adapter._index_generation or "",
                )
                shared_payload = dict(payload)
                shared_payload.pop("index_profile_digest")
                shared_payload.pop("index_generation")
                payload_digest = hashlib.sha256(
                    json.dumps(shared_payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                accumulator = accumulate_attestation_digest(
                    accumulator,
                    str(payload["canonical_identity"]),
                    int(payload["canonical_version"]),
                    payload_digest,
                )
                count += 1
            if offset is None:
                break
        return count, finalize_attestation_digest(count, accumulator)
    finally:
        await _close_client(client)


async def locator_profile_attestation_page(
    adapter, *, cursor: str | None, limit: int
) -> tuple[tuple[tuple[str, int, str], ...], str | None]:
    """Read at most one Qdrant page; callers own durable continuation state."""

    if not 1 <= limit <= 1000:
        raise ValueError("locator attestation page limit must be within 1..1000")
    if not adapter._locator_profile_enabled:
        raise QdrantLocatorPayloadError("locator index profile is not configured")
    client = None
    try:
        client, models = await adapter._client()
        if not await client.collection_exists(adapter._collection_name):
            return (), None
        exact_filter = locator_filter(
            models,
            {
                "must": [
                    {"key": "projection_version", "match": adapter._projection_version},
                    {"key": "index_profile_digest", "match": adapter._index_profile_digest},
                    {"key": "index_generation", "match": adapter._index_generation},
                ],
                "must_not": [],
            },
        )
        points, next_cursor = await client.scroll(
            collection_name=adapter._collection_name,
            scroll_filter=exact_filter,
            limit=limit,
            offset=cursor,
            with_payload=True,
            with_vectors=True,
        )
        rows = []
        expected_point_ids = []
        for point in points:
            payload = validate_locator_payload(
                getattr(point, "payload", None),
                projection_version=adapter._projection_version or "",
                index_profile_digest=adapter._index_profile_digest or "",
                index_generation=adapter._index_generation or "",
            )
            shared_payload = dict(payload)
            shared_payload.pop("index_profile_digest")
            shared_payload.pop("index_generation")
            identity = str(payload["canonical_identity"])
            expected_id = qdrant_point_id_for_chunk(identity)
            if str(getattr(point, "id", "")) != expected_id:
                raise QdrantLocatorPayloadError("locator point id is not retrievable identity")
            _require_dense_vector(adapter, getattr(point, "vector", None))
            expected_point_ids.append(expected_id)
            rows.append(
                (
                    identity,
                    int(payload["canonical_version"]),
                    hashlib.sha256(
                        json.dumps(shared_payload, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                )
            )
        if expected_point_ids:
            retrieved = await client.retrieve(
                collection_name=adapter._collection_name,
                ids=expected_point_ids,
                with_payload=False,
                with_vectors=False,
            )
            retrieved_ids = {str(getattr(point, "id", "")) for point in retrieved}
            if retrieved_ids != set(expected_point_ids):
                raise QdrantLocatorPayloadError("locator page contains unretrievable point")
        # Qdrant point ids for locator rows are UUID strings. Reject an opaque
        # cursor instead of persisting an adapter object that cannot be resumed.
        encoded_cursor = None if next_cursor is None else str(next_cursor)
        return tuple(rows), encoded_cursor
    finally:
        await _close_client(client)


async def locator_points_absent(adapter, chunk_ids: tuple[str, ...]) -> bool | None:
    """Return None when absence cannot be established without a blind mutation."""

    client = None
    try:
        client, _ = await adapter._client()
        if not await client.collection_exists(adapter._collection_name):
            return True
        from infinity_context_adapters.qdrant.identity_evidence import (
            qdrant_point_id_for_chunk,
        )

        points = await client.retrieve(
            collection_name=adapter._collection_name,
            ids=[qdrant_point_id_for_chunk(value) for value in chunk_ids],
            with_payload=False,
            with_vectors=False,
        )
        return not points
    except Exception:
        return None
    finally:
        await _close_client(client)


async def _close_client(client) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result


def _require_dense_vector(adapter, value) -> None:
    dense = value
    if isinstance(value, dict):
        dense = value.get(adapter._dense_vector_name)
    if (
        not isinstance(dense, (list, tuple))
        or len(dense) != adapter._vector_size
        or any(
            isinstance(component, bool)
            or not isinstance(component, (int, float))
            or not math.isfinite(component)
            for component in dense
        )
    ):
        raise QdrantLocatorPayloadError("locator dense vector integrity failed")


__all__ = (
    "locator_points_absent",
    "locator_profile_attestation",
    "locator_profile_attestation_page",
    "locator_profile_complete",
    "search_locator_chunks",
)
