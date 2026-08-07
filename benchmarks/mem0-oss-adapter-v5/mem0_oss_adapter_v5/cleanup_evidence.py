"""Private authenticated, content-free evidence for exact cleanup replay."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict
from pathlib import Path

from .cleanup import (
    CleanupReceipt,
    CleanupSeal,
    EntityProjectionSeal,
    ProjectionSeal,
    seal_cleanup_snapshot,
)
from .domain import canonical_json_bytes
from .mem0_storage import EntityLinkProjection, StorageSnapshot, VectorProjection

SCHEMA = "mem0-oss-adapter-v5.cleanup-evidence.v2"
LEGACY_SCHEMA = "mem0-oss-adapter-v5.cleanup-evidence.v1"


def encode(
    *,
    unit_identity_sha256: str,
    before: CleanupSeal,
    runtime_receipt_sha256: str | None,
    receipt: CleanupReceipt | None,
    hmac_key: bytes,
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "unit_identity_sha256": unit_identity_sha256,
        "cleanup_seal": asdict(before),
        "runtime_receipt_sha256": runtime_receipt_sha256,
        "cleanup_receipt": asdict(receipt) if receipt is not None else None,
    }
    payload["evidence_hmac_sha256"] = hmac.new(
        hmac_key, canonical_json_bytes(payload), hashlib.sha256
    ).hexdigest()
    return canonical_json_bytes(payload)


def decode(
    value: object,
    *,
    unit_identity_sha256: str,
    hmac_key: bytes,
) -> tuple[CleanupSeal, str | None, CleanupReceipt | None]:
    if type(value) is not dict:
        raise ValueError("cleanup_evidence_invalid")
    schema = value.get("schema_version")
    sealed_key = "cleanup_seal" if schema == SCHEMA else "sealed_before"
    root = _exact(
        value,
        {
            "schema_version",
            "unit_identity_sha256",
            sealed_key,
            "runtime_receipt_sha256",
            "cleanup_receipt",
            "evidence_hmac_sha256",
        },
    )
    signature = _digest(root.pop("evidence_hmac_sha256"))
    expected = hmac.new(hmac_key, canonical_json_bytes(root), hashlib.sha256).hexdigest()
    if (
        not hmac.compare_digest(signature, expected)
        or schema not in {SCHEMA, LEGACY_SCHEMA}
        or root["unit_identity_sha256"] != unit_identity_sha256
    ):
        raise ValueError("cleanup_evidence_invalid")
    result_sha = root["runtime_receipt_sha256"]
    seal = (
        _seal(root[sealed_key])
        if schema == SCHEMA
        else seal_cleanup_snapshot(_snapshot(root[sealed_key]))
    )
    return (
        seal,
        None if result_sha is None else _digest(result_sha),
        _receipt(root["cleanup_receipt"]),
    )


def _seal(value: object) -> CleanupSeal:
    raw = _exact(
        value,
        {
            "before_commitment_sha256",
            "provider_memory_ids",
            "vector_projections",
            "history_memory_ids",
            "message_ids",
            "entity_link_projections",
        },
    )
    provider_ids = _identity_tuple(raw["provider_memory_ids"])
    vectors = _projection_tuple(raw["vector_projections"])
    history_ids = _identity_tuple(raw["history_memory_ids"])
    message_ids = _identity_tuple(raw["message_ids"])
    entities = _entity_projection_tuple(raw["entity_link_projections"])
    if tuple(value.identity for value in vectors) != provider_ids:
        raise ValueError("cleanup_evidence_invalid")
    return CleanupSeal(
        before_commitment_sha256=_digest(raw["before_commitment_sha256"]),
        provider_memory_ids=provider_ids,
        vector_projections=vectors,
        history_memory_ids=history_ids,
        message_ids=message_ids,
        entity_link_projections=entities,
    )


def _projection_tuple(value: object) -> tuple[ProjectionSeal, ...]:
    if type(value) is not list or len(value) > 10_000:
        raise ValueError("cleanup_evidence_invalid")
    result = tuple(
        ProjectionSeal(
            identity=_text(item["identity"]),
            projection_sha256=_digest(item["projection_sha256"]),
        )
        for entry in value
        for item in (_exact(entry, {"identity", "projection_sha256"}),)
    )
    if result != tuple(sorted(result, key=lambda item: item.identity)) or len(
        {item.identity for item in result}
    ) != len(result):
        raise ValueError("cleanup_evidence_invalid")
    return result


def _entity_projection_tuple(value: object) -> tuple[EntityProjectionSeal, ...]:
    if type(value) is not list or len(value) > 10_000:
        raise ValueError("cleanup_evidence_invalid")
    result = tuple(
        EntityProjectionSeal(
            entity_id=_text(item["entity_id"]),
            linked_provider_memory_ids=_identity_tuple(item["linked_provider_memory_ids"]),
        )
        for entry in value
        for item in (_exact(entry, {"entity_id", "linked_provider_memory_ids"}),)
    )
    if result != tuple(sorted(result, key=lambda item: item.entity_id)) or len(
        {item.entity_id for item in result}
    ) != len(result):
        raise ValueError("cleanup_evidence_invalid")
    return result


def _snapshot(value: object) -> StorageSnapshot:
    raw = _exact(value, {"vectors", "history_memory_ids", "message_ids", "entity_links"})
    vectors_raw, entities_raw = raw["vectors"], raw["entity_links"]
    if type(vectors_raw) is not list or type(entities_raw) is not list:
        raise ValueError("cleanup_evidence_invalid")
    vectors = tuple(
        VectorProjection(
            provider_memory_id=_text(item["provider_memory_id"]),
            extraction_memory_id=_text(item["extraction_memory_id"]),
            text=_text(item["text"], maximum=16_384),
            attributed_to=None if item["attributed_to"] is None else _text(item["attributed_to"]),
            linked_memory_ids=_text_tuple(item["linked_memory_ids"]),
        )
        for entry in vectors_raw
        for item in (
            _exact(
                entry,
                {
                    "provider_memory_id",
                    "extraction_memory_id",
                    "text",
                    "attributed_to",
                    "linked_memory_ids",
                },
            ),
        )
    )
    entities = tuple(
        EntityLinkProjection(
            entity_id=_text(item["entity_id"]),
            linked_provider_memory_ids=_text_tuple(item["linked_provider_memory_ids"]),
        )
        for entry in entities_raw
        for item in (_exact(entry, {"entity_id", "linked_provider_memory_ids"}),)
    )
    return StorageSnapshot(
        vectors=vectors,
        history_memory_ids=_text_tuple(raw["history_memory_ids"]),
        message_ids=_text_tuple(raw["message_ids"]),
        entity_links=entities,
    )


def _receipt(value: object) -> CleanupReceipt | None:
    if value is None:
        return None
    raw = _exact(
        value,
        {
            "before_commitment_sha256",
            "after_commitment_sha256",
            "tombstone_commitment_sha256",
            "provider_memory_ids",
            "runtime_receipt_removed",
        },
    )
    removed = raw["runtime_receipt_removed"]
    if type(removed) is not bool:
        raise ValueError("cleanup_evidence_invalid")
    return CleanupReceipt(
        before_commitment_sha256=_digest(raw["before_commitment_sha256"]),
        after_commitment_sha256=_digest(raw["after_commitment_sha256"]),
        tombstone_commitment_sha256=_digest(raw["tombstone_commitment_sha256"]),
        provider_memory_ids=_identity_tuple(raw["provider_memory_ids"]),
        runtime_receipt_removed=removed,
    )


def _exact(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("cleanup_evidence_invalid")
    return value


def _digest(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("cleanup_evidence_invalid")
    return value


def _text(value: object, *, maximum: int = 512) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError("cleanup_evidence_invalid")
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 10_000:
        raise ValueError("cleanup_evidence_invalid")
    return tuple(_text(item, maximum=16_384) for item in value)


def _identity_tuple(value: object) -> tuple[str, ...]:
    result = _text_tuple(value)
    if result != tuple(sorted(result)) or len(set(result)) != len(result):
        raise ValueError("cleanup_evidence_invalid")
    return result


def path_for(directory: Path, operation_id: str) -> Path:
    return directory / f"{operation_id}.cleanup.json"


__all__ = ("LEGACY_SCHEMA", "SCHEMA", "decode", "encode", "path_for")
