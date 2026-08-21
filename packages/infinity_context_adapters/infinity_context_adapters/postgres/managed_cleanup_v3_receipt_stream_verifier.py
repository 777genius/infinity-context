"""Pure identity and streaming event checks for cleanup-v3 receipt preflight."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    ProjectionTargetIdentity,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    canonical_bytes,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_projection_evidence import iso8601
from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk


def verify_identity(
    authenticator: ProjectionReceiptAuthenticator,
    receipt: Mapping[str, object],
    link: Mapping[str, object],
    identity: Mapping[str, object],
) -> None:
    try:
        target = ProjectionTargetIdentity(
            kind=str(identity.get("kind")),
            canonical_source_id=str(identity.get("canonical_source_id")),
            physical_identity=str(identity.get("physical_identity")),
            lineage_root_sha256=str(identity.get("lineage_root_sha256")),
            target_authority_sha256=str(identity.get("target_authority_sha256")),
        )
    except ProjectionReceiptError:
        fail("identity_invalid")
    physical = identity.get("physical_identity")
    source_id = str(identity.get("canonical_source_id"))
    expected_physical = (
        qdrant_point_id_for_chunk(source_id)
        if identity.get("kind") == "qdrant_point_id"
        else f"fact:{source_id}"
        if identity.get("kind") == "graphiti_episode_name"
        else physical
    )
    if (
        identity.get("identity_sha256") != target.identity_sha256
        or identity.get("identity_commitment_sha256") != target.identity_commitment_sha256
        or not authenticator.verify(
            "projection-identity",
            target.identity_commitment_sha256,
            str(identity.get("identity_mac_sha256")),
        )
        or link.get("outbox_id") != receipt.get("outbox_id")
        or link.get("run_id_sha256") != receipt.get("run_id_sha256")
        or any(
            link.get(name) != identity.get(name)
            for name in ("kind", "identity_sha256", "identity_commitment_sha256")
        )
        or identity.get("lineage_root_sha256") != receipt.get("lineage_root_sha256")
        or identity.get("target_authority_sha256") != receipt.get("target_authority_sha256")
        or physical != expected_physical
    ):
        fail("identity_invalid")


def inventory_uses(
    receipt: Mapping[str, object], identity: Mapping[str, object]
) -> tuple[str, ...]:
    target = {
        "qdrant_point_id": "qdrant_target_identities",
        "graphiti_episode_name": "graphiti_target_names",
        "graphiti_episode_uuid": "graphiti_target_uuids",
    }.get(str(identity.get("kind")))
    lane, operation = str(receipt.get("lane")), str(receipt.get("operation"))
    allowed = {
        "qdrant": {"qdrant_point_id"},
        "graphiti": {"graphiti_episode_name", "graphiti_episode_uuid"},
    }.get(lane)
    if allowed is None or identity.get("kind") not in allowed:
        fail("identity_kind_invalid")
    result = [target] if target and operation == "upsert" else []
    if identity.get("kind") in {"qdrant_point_id", "graphiti_episode_uuid"}:
        result.append(f"{lane}_{operation}_jobs")
        if operation == "delete":
            result.append("cleanup_outbox_receipts")
    return tuple(result)


def validate_event_binding(
    context: ManagedCleanupV3Context,
    receipt: Mapping[str, object],
    outbox: Mapping[str, object],
    source_id: str | None,
    identity_count: int,
) -> None:
    lane, operation = str(receipt.get("lane")), str(receipt.get("operation"))
    event = outbox.get("event_type")
    aggregate_type, aggregate_id = outbox.get("aggregate_type"), outbox.get("aggregate_id")
    payload = object_value(outbox.get("payload_without_chunk_ids"))
    if lane == "qdrant" and operation == "upsert":
        valid = (
            event in {"vector.upsert_chunk", "vector.upsert_chunks"}
            and aggregate_type == "chunk"
            and aggregate_id == source_id
            and identity_count == 1
            and (
                (event == "vector.upsert_chunk" and payload == {"chunk_id": source_id})
                or (event == "vector.upsert_chunks" and not payload)
            )
        )
    elif lane == "qdrant" and operation == "delete":
        valid = (
            event == "vector.delete_chunks"
            and aggregate_type == "benchmark_run"
            and aggregate_id == context.run_id_sha256
            and payload
            == {
                "cleanup_run_id_sha256": context.run_id_sha256,
                "space_id": context.space_id,
            }
        )
    elif lane == "graphiti" and operation == "upsert":
        valid = (
            event == "graph.upsert_fact"
            and aggregate_type == "fact"
            and aggregate_id == source_id
            and payload
            == {
                "fact_id": source_id,
                "memory_scope_id": receipt.get("memory_scope_id"),
                "message_id": outbox.get("message_key"),
                "occurred_at": iso8601(outbox.get("created_at")),
                "space_id": context.space_id,
                "thread_id": receipt.get("thread_id"),
                "version": outbox.get("aggregate_version"),
            }
        )
    elif lane == "graphiti" and operation == "delete":
        valid = (
            event == "graph.delete_fact"
            and aggregate_type == "benchmark_run"
            and aggregate_id == source_id
            and payload
            == {
                "cleanup_run_id_sha256": context.run_id_sha256,
                "fact_id": source_id,
                "space_id": context.space_id,
            }
        )
    else:
        valid = False
    if not valid:
        fail("outbox_event_invalid")


def array_event(event_type: object, payload_count: object) -> bool:
    expected = event_type in {"vector.delete_chunks", "vector.upsert_chunks"}
    observed = payload_count is not None
    if observed is not expected:
        fail("outbox_payload_shape_invalid")
    return observed


def row_header(outbox, receipt):
    return {
        "outbox": {
            key: outbox.get(key)
            for key in (
                "id",
                "message_key",
                "event_type",
                "aggregate_type",
                "aggregate_id",
                "aggregate_version",
                "created_at",
                "status",
            )
        },
        "receipt": receipt,
    }


def link_evidence(link, identity):
    return {"link": link, "identity": identity}


def small_event(outbox) -> str:
    return sha256_value(
        {
            "aggregate_id": outbox.get("aggregate_id"),
            "aggregate_type": outbox.get("aggregate_type"),
            "aggregate_version": outbox.get("aggregate_version"),
            "created_at": iso8601(outbox.get("created_at")),
            "event_type": outbox.get("event_type"),
            "message_key": outbox.get("message_key"),
            "payload": outbox.get("payload_without_chunk_ids"),
            "schema": "memory_projection_outbox_event/v1",
        }
    )


def event_prefix(outbox):
    result = hashlib.sha256()
    result.update(b'{"aggregate_id":' + canonical_bytes(outbox.get("aggregate_id")))
    result.update(b',"aggregate_type":' + canonical_bytes(outbox.get("aggregate_type")))
    result.update(b',"aggregate_version":' + canonical_bytes(outbox.get("aggregate_version")))
    result.update(b',"created_at":' + canonical_bytes(iso8601(outbox.get("created_at"))))
    result.update(b',"event_type":' + canonical_bytes(outbox.get("event_type")))
    result.update(b',"message_key":' + canonical_bytes(outbox.get("message_key")))
    result.update(b',"payload":{"chunk_ids":[')
    return result


def finish_array_event(result, outbox):
    remainder = object_value(outbox.get("payload_without_chunk_ids"))
    result.update(b"]")
    for key in sorted(remainder):
        result.update(b"," + canonical_bytes(key) + b":" + canonical_bytes(remainder[key]))
    result.update(b'},"schema":"memory_projection_outbox_event/v1"}')
    return result.hexdigest()


def sha256_value(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def object_value(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        fail("evidence_shape_invalid")
    return dict(value)


def integer_value(value: object) -> int:
    if type(value) is not int:
        fail("integer_invalid")
    return value


def fail(suffix: str):
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_receipt_{suffix}")


__all__ = (
    "array_event",
    "event_prefix",
    "fail",
    "finish_array_event",
    "integer_value",
    "inventory_uses",
    "link_evidence",
    "object_value",
    "row_header",
    "sha256_value",
    "small_event",
    "validate_event_binding",
    "verify_identity",
)
