"""Exact Qdrant payload schema and filter primitives for Retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from infinity_context_core.ports.adapters import VectorUpsertItem

LOCATOR_PAYLOAD_SCHEMA = {
    "actor_keys": "keyword",
    "canonical_identity": "keyword",
    "canonical_version": "integer",
    "category": "keyword",
    "chunk_key": "keyword",
    "document_key": "keyword",
    "end_at": "datetime",
    "index_generation": "keyword",
    "index_profile_digest": "keyword",
    "kind": "keyword",
    "lifecycle_status": "keyword",
    "locator": "keyword",
    "memory_scope_id": "keyword",
    "projection_generation": "keyword",
    "projection_version": "keyword",
    "relative_end_ms": "integer",
    "relative_start_ms": "integer",
    "sequence_ordinal": "integer",
    "source_key": "keyword",
    "space_id": "keyword",
    "start_at": "datetime",
    "tags": "keyword",
    "thread_id": "keyword",
}


class QdrantLocatorPayloadError(RuntimeError):
    pass


def validate_locator_payload(
    payload: object, *, projection_version: str, index_profile_digest: str, index_generation: str
) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != set(LOCATOR_PAYLOAD_SCHEMA):
        raise QdrantLocatorPayloadError("locator point payload fields are not exact")
    string_fields = {
        "actor_keys",
        "tags",
    }
    for key in (
        set(LOCATOR_PAYLOAD_SCHEMA)
        - string_fields
        - {
            "canonical_version",
            "sequence_ordinal",
            "relative_start_ms",
            "relative_end_ms",
            "start_at",
            "end_at",
            "thread_id",
        }
    ):
        if not isinstance(payload[key], str) or not payload[key]:
            raise QdrantLocatorPayloadError(f"locator payload {key} is malformed")
    for key, maximum in {
        "space_id": 80,
        "memory_scope_id": 80,
        "canonical_identity": 80,
        "document_key": 80,
        "chunk_key": 80,
        "locator": 256,
        "source_key": 256,
        "projection_generation": 256,
        "kind": 256,
        "category": 256,
    }.items():
        if len(payload[key]) > maximum:
            raise QdrantLocatorPayloadError(f"locator payload {key} is malformed")
    for key in string_fields:
        value = payload[key]
        if (
            not isinstance(value, list)
            or not all(isinstance(item, str) and item for item in value)
            or len(value) > 100
            or any(len(item) > 256 for item in value)
            or value != sorted(set(value), key=lambda item: item.encode("utf-8"))
        ):
            raise QdrantLocatorPayloadError(f"locator payload {key} is malformed")
    for key, minimum, maximum in (
        ("canonical_version", 1, 9_007_199_254_740_991),
        ("sequence_ordinal", 0, 2_147_483_647),
    ):
        value = payload[key]
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise QdrantLocatorPayloadError(f"locator payload {key} is malformed")
    _paired_nullable_integers(payload, "relative_start_ms", "relative_end_ms")
    _paired_nullable_strings(payload, "start_at", "end_at")
    thread_id = payload["thread_id"]
    if thread_id is not None and (
        not isinstance(thread_id, str) or not thread_id or len(thread_id) > 80
    ):
        raise QdrantLocatorPayloadError("locator payload thread_id is malformed")
    if (
        payload["projection_version"] != projection_version
        or payload["index_profile_digest"] != index_profile_digest
        or payload["index_generation"] != index_generation
        or payload["lifecycle_status"] != "active"
        or payload["canonical_identity"] != payload["chunk_key"]
    ):
        raise QdrantLocatorPayloadError("locator payload profile or identity is malformed")
    return payload


def _paired_nullable_integers(payload, start_key: str, end_key: str) -> None:
    start, end = payload[start_key], payload[end_key]
    if (start is None) != (end is None):
        raise QdrantLocatorPayloadError("locator relative interval is incomplete")
    if start is not None and (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or not 0 <= start <= end <= 9_007_199_254_740_991
    ):
        raise QdrantLocatorPayloadError("locator relative interval is malformed")


def _paired_nullable_strings(payload, start_key: str, end_key: str) -> None:
    start, end = payload[start_key], payload[end_key]
    if (start is None) != (end is None):
        raise QdrantLocatorPayloadError("locator absolute interval is incomplete")
    if start is None:
        return
    if not isinstance(start, str) or not isinstance(end, str):
        raise QdrantLocatorPayloadError("locator absolute interval is malformed")
    try:
        start_value = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_value = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QdrantLocatorPayloadError("locator absolute interval is malformed") from exc
    if start_value.utcoffset() is None or end_value.utcoffset() is None or start_value > end_value:
        raise QdrantLocatorPayloadError("locator absolute interval is malformed")


def locator_filter(models, spec: dict[str, object]):
    def condition(item: object):
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ValueError("Qdrant locator filter condition is malformed")
        key = item["key"]
        if item.get("is_null") is True:
            return models.IsNullCondition(is_null=models.PayloadField(key=key))
        if "match" in item:
            return models.FieldCondition(key=key, match=models.MatchValue(value=item["match"]))
        if "match_any" in item:
            return models.FieldCondition(
                key=key, match=models.MatchAny(any=list(item["match_any"]))
            )
        range_values = {name: item[name] for name in ("gte", "lte") if name in item}
        range_type = (
            models.Range
            if key in {"relative_start_ms", "relative_end_ms"}
            else getattr(models, "DatetimeRange", models.Range)
        )
        return models.FieldCondition(key=key, range=range_type(**range_values))

    def nested(item: object):
        if not isinstance(item, dict):
            raise ValueError("Qdrant locator nested filter is malformed")
        return models.Filter(
            must=[condition(value) for value in item.get("must", ())],
            must_not=[condition(value) for value in item.get("must_not", ())],
        )

    must = spec.get("must", ())
    must_not = spec.get("must_not", ())
    should = spec.get("should", ())
    if any(isinstance(value, str | bytes) for value in (must, must_not, should)):
        raise ValueError("Qdrant locator filter lists are malformed")
    kwargs = dict(
        must=[condition(item) for item in must],
        must_not=[condition(item) for item in must_not],
        should=[nested(item) for item in should],
    )
    minimum = spec.get("minimum_should_match")
    if minimum is not None:
        min_should = getattr(models, "MinShould", None)
        if min_should is None:
            raise ValueError("Qdrant minimum-should-match is unsupported")
        kwargs["min_should"] = min_should(conditions=kwargs.pop("should"), min_count=minimum)
    return models.Filter(**kwargs)


def payload_schema_matches(collection: object | None) -> bool:
    if collection is None:
        return False
    schema = _mapping(getattr(collection, "payload_schema", None))
    if schema is None or set(schema) != set(LOCATOR_PAYLOAD_SCHEMA):
        return False
    for field_name, expected in LOCATOR_PAYLOAD_SCHEMA.items():
        value = schema.get(field_name)
        if value is None:
            return False
        data_type = getattr(value, "data_type", value)
        normalized = str(getattr(data_type, "value", data_type)).casefold()
        if normalized != expected:
            return False
    return True


def locator_payload(item: VectorUpsertItem) -> dict[str, object]:
    metadata: dict[str, object] = dict(item.metadata)
    authoritative = {
        "chunk_id": item.chunk_id,
        "space_id": item.space_id,
        "memory_scope_id": item.memory_scope_id,
        "thread_id": item.thread_id,
        "projection_version": item.projection_version,
    }
    for key, expected in authoritative.items():
        if key in metadata and metadata[key] != expected:
            raise QdrantLocatorPayloadError(
                f"locator payload {key} conflicts with its canonical envelope"
            )
    for key in ("actor_keys", "tags"):
        value = metadata.get(key)
        if isinstance(value, str):
            metadata[key] = value.split("\u001f") if value else []
    for key in ("sequence_ordinal", "canonical_version", "relative_start_ms", "relative_end_ms"):
        value = metadata.get(key)
        if isinstance(value, str) and value.isdecimal():
            metadata[key] = int(value)
    return {**metadata, **authoritative}


def expected_locator_payload(
    row: object, *, projection_version: str, index_profile_digest: str, index_generation: str
) -> dict[str, object]:
    """Render the exact typed derived payload from one authoritative PG row."""

    get = row.get if isinstance(row, Mapping) else lambda name: getattr(row, name)
    start = get("retrieval_start_at")
    end = get("retrieval_end_at")
    return {
        "space_id": get("space_id"),
        "memory_scope_id": get("memory_scope_id"),
        "thread_id": get("thread_id"),
        "projection_version": projection_version,
        "locator": get("retrieval_locator"),
        "source_key": get("retrieval_source_key"),
        "projection_generation": get("retrieval_projection_generation"),
        "sequence_ordinal": get("retrieval_sequence_ordinal"),
        "actor_keys": list(get("retrieval_actor_keys_json") or ()),
        "start_at": None if start is None else start.isoformat(),
        "end_at": None if end is None else end.isoformat(),
        "relative_start_ms": get("retrieval_relative_start_ms"),
        "relative_end_ms": get("retrieval_relative_end_ms"),
        "kind": get("retrieval_kind"),
        "category": get("retrieval_category"),
        "tags": list(get("retrieval_tags_json") or ()),
        "canonical_identity": get("id"),
        "canonical_version": get("retrieval_version"),
        "lifecycle_status": "active",
        "document_key": get("document_id"),
        "chunk_key": get("id"),
        "index_profile_digest": index_profile_digest,
        "index_generation": index_generation,
    }


def _mapping(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else None
    raw = getattr(value, "__dict__", None)
    return raw if isinstance(raw, dict) else None


__all__ = (
    "LOCATOR_PAYLOAD_SCHEMA",
    "QdrantLocatorPayloadError",
    "locator_filter",
    "locator_payload",
    "expected_locator_payload",
    "payload_schema_matches",
    "validate_locator_payload",
)
