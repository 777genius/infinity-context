"""Pure projection receipt evidence checks used by cleanup v3 inventory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
)

from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk


def verify_projection_event(
    context: ManagedCleanupV3Context,
    lane: str,
    operation: str,
    outbox: Mapping[str, object],
    identity: Mapping[str, object],
    canonical: Mapping[str, object],
    proof: Sequence[object],
) -> None:
    event = outbox.get("event_type")
    aggregate_type = outbox.get("aggregate_type")
    aggregate_id = outbox.get("aggregate_id")
    source_id = identity.get("canonical_source_id")
    payload = outbox.get("payload_json")
    if not isinstance(payload, Mapping):
        _fail("outbox_payload_invalid")
    expected = {
        ("qdrant", "upsert"): ({"vector.upsert_chunk", "vector.upsert_chunks"}, "chunk"),
        ("qdrant", "delete"): ({"vector.delete_chunks"}, "benchmark_run"),
        ("graphiti", "upsert"): ({"graph.upsert_fact"}, "fact"),
        ("graphiti", "delete"): ({"graph.delete_fact"}, "benchmark_run"),
    }.get((lane, operation))
    if expected is None or event not in expected[0] or aggregate_type != expected[1]:
        _fail("outbox_event_invalid")
    if lane == "qdrant" and identity.get("physical_identity") != qdrant_point_id_for_chunk(
        str(source_id)
    ):
        _fail("physical_mapping_invalid")
    if lane == "qdrant" and operation == "upsert":
        expected_payload = (
            {"chunk_id": source_id}
            if event == "vector.upsert_chunk"
            else {"chunk_ids": [source_id]}
        )
        if aggregate_id != source_id or payload != expected_payload:
            _fail("outbox_payload_invalid")
    elif lane == "qdrant":
        proof_sources = sorted(
            str(item.get("canonical_source_id")) for item in proof if isinstance(item, Mapping)
        )
        if aggregate_id != context.run_id_sha256 or payload != {
            "chunk_ids": proof_sources,
            "space_id": context.space_id,
            "cleanup_run_id_sha256": context.run_id_sha256,
        }:
            _fail("outbox_payload_invalid")
    elif operation == "upsert":
        receipt_space = canonical.get("space_id")
        expected_payload = {
            "message_id": outbox.get("message_key"),
            "fact_id": source_id,
            "version": outbox.get("aggregate_version"),
            "space_id": receipt_space,
            "memory_scope_id": canonical.get("memory_scope_id"),
            "thread_id": canonical.get("thread_id"),
            "occurred_at": iso8601(outbox.get("created_at")),
        }
        if (
            aggregate_id != source_id
            or receipt_space != context.space_id
            or payload != expected_payload
            or outbox.get("aggregate_version") != canonical.get("version")
        ):
            _fail("outbox_payload_invalid")
    elif aggregate_id != source_id or payload != {
        "fact_id": source_id,
        "space_id": context.space_id,
        "cleanup_run_id_sha256": context.run_id_sha256,
    }:
        _fail("outbox_payload_invalid")


def verify_receipt_link(
    link: Mapping[str, object],
    receipt: Mapping[str, object],
    identity: Mapping[str, object],
    proof: Sequence[object],
) -> None:
    ordinal = link.get("ordinal")
    if (
        link.get("outbox_id") != receipt.get("outbox_id")
        or link.get("run_id_sha256") != receipt.get("run_id_sha256")
        or link.get("kind") != identity.get("kind")
        or link.get("identity_sha256") != identity.get("identity_sha256")
        or link.get("identity_commitment_sha256") != identity.get("identity_commitment_sha256")
        or type(ordinal) is not int
        or not 0 <= ordinal < len(proof)
    ):
        _fail("link_invalid")
    linked = proof[ordinal]
    if not isinstance(linked, Mapping) or any(
        linked.get(name) != link.get(name)
        for name in ("kind", "identity_sha256", "identity_commitment_sha256", "ordinal")
    ):
        _fail("link_invalid")


def receipt_identity_root(proof: Sequence[object]) -> str:
    normalized = []
    for expected_ordinal, raw in enumerate(proof):
        if not isinstance(raw, Mapping) or raw.get("ordinal") != expected_ordinal:
            _fail("identity_root_invalid")
        normalized.append(
            {
                "identity_commitment_sha256": raw.get("identity_commitment_sha256"),
                "identity_sha256": raw.get("identity_sha256"),
                "kind": raw.get("kind"),
                "ordinal": expected_ordinal,
            }
        )
    return _digest(normalized)


def receipt_sha256(receipt: Mapping[str, object], root: str) -> str:
    summary = {
        "aggregate_id": receipt.get("aggregate_id"),
        "aggregate_type": receipt.get("aggregate_type"),
        "aggregate_version": receipt.get("aggregate_version"),
        "context_sha256": receipt.get("context_sha256"),
        "identity_count": receipt.get("identity_count"),
        "lane": receipt.get("lane"),
        "lineage_root_sha256": receipt.get("lineage_root_sha256"),
        "memory_scope_id": receipt.get("memory_scope_id"),
        "ordered_identity_root_sha256": root,
        "operation": receipt.get("operation"),
        "outbox_event_commitment_sha256": receipt.get("outbox_event_commitment_sha256"),
        "outbox_id": receipt.get("outbox_id"),
        "persisted_at": iso8601(receipt.get("persisted_at")),
        "provider_completed_at": iso8601(receipt.get("provider_completed_at")),
        "schema": "memory_projection_result_receipt/v1",
        "run_id_sha256": receipt.get("run_id_sha256"),
        "result_state": receipt.get("result_state"),
        "space_id": receipt.get("space_id"),
        "target_authority_sha256": receipt.get("target_authority_sha256"),
        "thread_id": receipt.get("thread_id"),
        "worker_authority_sha256": receipt.get("worker_authority_sha256"),
    }
    return _digest(summary)


def verify_projection_locator(
    kind: str,
    locator: Mapping[str, object],
    outbox: Mapping[str, object],
    identity: Mapping[str, object],
    target_kinds: set[str],
) -> None:
    if kind in target_kinds:
        expected = {
            name: identity.get(name)
            for name in (
                "kind",
                "identity_sha256",
                "identity_commitment_sha256",
                "lineage_root_sha256",
                "target_authority_sha256",
            )
        }
    else:
        expected = {
            "physical_outbox_id": outbox.get("id"),
            "logical_target_identity_sha256": identity.get("identity_sha256"),
        }
    if dict(locator) != expected:
        _fail("locator_invalid")


def iso8601(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _fail("receipt_time_invalid")
    else:
        _fail("receipt_time_invalid")
    if parsed.tzinfo is None:
        _fail("receipt_time_invalid")
    return parsed.isoformat()


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_source_authentication_{suffix}")


__all__ = (
    "iso8601",
    "receipt_identity_root",
    "receipt_sha256",
    "verify_projection_event",
    "verify_projection_locator",
    "verify_receipt_link",
)
