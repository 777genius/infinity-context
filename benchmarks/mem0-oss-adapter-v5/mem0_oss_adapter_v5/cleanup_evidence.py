"""Private authenticated evidence needed to replay exact cleanup."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict
from pathlib import Path

from .cleanup import CleanupReceipt
from .domain import canonical_json_bytes
from .mem0_storage import EntityLinkProjection, StorageSnapshot, VectorProjection

SCHEMA = "mem0-oss-adapter-v5.cleanup-evidence.v1"


def encode(
    *,
    unit_identity_sha256: str,
    before: StorageSnapshot,
    runtime_receipt_sha256: str | None,
    receipt: CleanupReceipt | None,
    hmac_key: bytes,
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "unit_identity_sha256": unit_identity_sha256,
        "sealed_before": asdict(before),
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
) -> tuple[StorageSnapshot, str | None, CleanupReceipt | None]:
    root = _exact(
        value,
        {
            "schema_version",
            "unit_identity_sha256",
            "sealed_before",
            "runtime_receipt_sha256",
            "cleanup_receipt",
            "evidence_hmac_sha256",
        },
    )
    signature = _digest(root.pop("evidence_hmac_sha256"))
    expected = hmac.new(hmac_key, canonical_json_bytes(root), hashlib.sha256).hexdigest()
    if (
        not hmac.compare_digest(signature, expected)
        or root["schema_version"] != SCHEMA
        or root["unit_identity_sha256"] != unit_identity_sha256
    ):
        raise ValueError("cleanup_evidence_invalid")
    result_sha = root["runtime_receipt_sha256"]
    return (
        _snapshot(root["sealed_before"]),
        None if result_sha is None else _digest(result_sha),
        _receipt(root["cleanup_receipt"]),
    )


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
        provider_memory_ids=_text_tuple(raw["provider_memory_ids"]),
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


def path_for(directory: Path, operation_id: str) -> Path:
    return directory / f"{operation_id}.cleanup.json"


__all__ = ("decode", "encode", "path_for")
