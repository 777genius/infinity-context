"""Exact wire parsing and verification for the managed benchmark registry."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    FINALIZE_ABORT_RESPONSE_SCHEMA_VERSION,
    FINALIZE_CLEANUP_RESPONSE_SCHEMA_VERSION,
    REGISTRATION_SCHEMA_VERSION,
    ManagedBenchmarkAbortCompletionReceipt,
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkCleanupCounts,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedAbortReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkPersistedCompletionReceipt,
    ManagedBenchmarkProjectionSeal,
    ManagedBenchmarkRunLifecycleSnapshot,
    ManagedBenchmarkRunRegistration,
    canonical_id,
    digest,
    fail,
    utc_timestamp,
)

MAX_RESPONSE_BYTES = 2_000_000
_COUNT_KEYS = (
    "facts",
    "documents",
    "chunks",
    "episodes",
    "threads",
    "memory_scopes",
    "obsolete_upsert_jobs",
    "vector_delete_jobs",
    "graph_delete_jobs",
    "cognee_delete_jobs",
)
_OUTBOX_KEYS = (
    "vector_delete_outbox_ids",
    "graph_delete_outbox_ids",
    "cognee_delete_outbox_ids",
)


def remaining_io_timeout(
    *,
    deadline: datetime,
    timeout_seconds: float,
    clock: Callable[[], datetime],
) -> float:
    """Bound the next synchronous I/O phase without claiming total cancellation."""

    remaining = (deadline.astimezone(UTC) - _clock_utc(clock)).total_seconds()
    if not math.isfinite(remaining) or remaining <= 0:
        fail("managed_benchmark_registry_deadline_expired")
    return min(float(timeout_seconds), remaining)


def fresh_io_deadline(
    *,
    timeout_seconds: float,
    clock: Callable[[], datetime],
) -> datetime:
    """Create one fresh finite wall-clock window for a retryable operation."""

    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(float(timeout_seconds))
        or float(timeout_seconds) <= 0
    ):
        fail("managed_benchmark_registry_recovery_window_invalid")
    try:
        return _clock_utc(clock) + timedelta(seconds=float(timeout_seconds))
    except (OverflowError, ValueError):
        fail("managed_benchmark_registry_recovery_window_invalid")


def read_json_envelope(
    response: httpx.Response,
    *,
    deadline: datetime,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    """Read a bounded exact JSON envelope while enforcing the absolute deadline."""

    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if content_type != "application/json" or encoding not in {"", "identity"}:
        fail("managed_benchmark_registry_response_invalid")
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            fail("managed_benchmark_registry_response_invalid")
        if declared < 0 or declared > MAX_RESPONSE_BYTES:
            fail("managed_benchmark_registry_response_too_large")

    body = bytearray()
    iterator = iter(response.iter_bytes())
    while True:
        _require_before_deadline(deadline, clock)
        try:
            chunk = next(iterator)
        except StopIteration:
            break
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            fail("managed_benchmark_registry_response_too_large")
        _require_before_deadline(deadline, clock)
    decoded = _decode_json(bytes(body))
    envelope = _exact_object(
        decoded,
        frozenset({"data"}),
        "managed_benchmark_registry_response_invalid",
    )
    return _object(envelope["data"])


def parse_registration(
    data: object,
    *,
    status: int,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    target_identity_sha256: str,
    space_slug: str,
) -> ManagedBenchmarkRunRegistration:
    value = _exact_object(
        data,
        frozenset(
            {
                "schema_version",
                "authority",
                "run_id_sha256",
                "binding_commitment_sha256",
                "infinity_target_identity_sha256",
                "space_id",
                "space_slug",
                "state",
                "created",
            }
        ),
        "managed_benchmark_registry_registration_response_invalid",
    )
    created = value["created"]
    state = value["state"]
    if (
        value["schema_version"] != REGISTRATION_SCHEMA_VERSION
        or value["authority"] != "infinity_canonical"
        or value["run_id_sha256"] != run_id_sha256
        or value["binding_commitment_sha256"] != binding_commitment_sha256
        or value["infinity_target_identity_sha256"] != target_identity_sha256
        or value["space_slug"] != space_slug
        or state not in {"active", "cleanup_pending", "cleanup_complete", "cleanup_aborted"}
        or type(created) is not bool
        or status != (201 if created else 200)
        or (created and state != "active")
    ):
        fail("managed_benchmark_registry_registration_response_invalid")
    return ManagedBenchmarkRunRegistration(
        schema_version=REGISTRATION_SCHEMA_VERSION,
        authority="infinity_canonical",
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        infinity_target_identity_sha256=target_identity_sha256,
        space_id=canonical_id(
            value["space_id"],
            "managed_benchmark_registry_registration_response_invalid",
        ),
        space_slug=space_slug,
        state=state,
        created=created,
    )


def parse_projection_seal(
    data: object,
    *,
    registration: ManagedBenchmarkRunRegistration,
    projection_manifest_sha256: str,
) -> ManagedBenchmarkProjectionSeal:
    value = _exact_object(
        data,
        frozenset(
            {
                "schema_version",
                "authority",
                "run_id_sha256",
                "binding_commitment_sha256",
                "infinity_target_identity_sha256",
                "projection_manifest_sha256",
                "state",
                "projection_cleanup_state",
                "replayed",
            }
        ),
        "managed_benchmark_registry_manifest_response_invalid",
    )
    replayed = value["replayed"]
    if (
        value["schema_version"] != "memory-comparison-projection-manifest-seal-response.v1"
        or value["authority"] != "infinity_canonical"
        or value["run_id_sha256"] != registration.run_id_sha256
        or value["binding_commitment_sha256"] != registration.binding_commitment_sha256
        or value["infinity_target_identity_sha256"] != registration.infinity_target_identity_sha256
        or value["projection_manifest_sha256"] != projection_manifest_sha256
        or value["state"] != "active"
        or value["projection_cleanup_state"] != "sealed"
        or type(replayed) is not bool
    ):
        fail("managed_benchmark_registry_manifest_response_invalid")
    return ManagedBenchmarkProjectionSeal(
        registration.run_id_sha256,
        registration.binding_commitment_sha256,
        registration.infinity_target_identity_sha256,
        projection_manifest_sha256,
        replayed,
    )


def parse_cleanup_receipt(
    data: object,
    *,
    registration: ManagedBenchmarkRunRegistration,
) -> ManagedBenchmarkCleanupReceipt:
    value = _exact_object(
        data,
        frozenset(
            {
                "schema_version",
                "authority",
                "run_id_sha256",
                "space_id",
                "space_slug",
                "state",
                "disposition",
                "projection_cleanup",
                "counts",
                *_OUTBOX_KEYS,
                "receipt_sha256",
                "replayed",
            }
        ),
        "managed_benchmark_registry_cleanup_response_invalid",
    )
    counts_value = _exact_object(
        value["counts"],
        frozenset(_COUNT_KEYS),
        "managed_benchmark_registry_cleanup_response_invalid",
    )
    if any(type(counts_value[key]) is not int or counts_value[key] < 0 for key in _COUNT_KEYS):
        fail("managed_benchmark_registry_cleanup_response_invalid")
    outboxes = tuple(_positive_int_list(value[key]) for key in _OUTBOX_KEYS)
    flattened = tuple(item for lane in outboxes for item in lane)
    if len(flattened) != len(set(flattened)):
        fail("managed_benchmark_registry_cleanup_response_invalid")
    replayed = value["replayed"]
    receipt_sha256 = digest(
        value["receipt_sha256"],
        "managed_benchmark_registry_cleanup_response_invalid",
    )
    projection_cleanup = value["projection_cleanup"]
    if (
        value["schema_version"] != "memory-comparison-run-cleanup-response.v1"
        or value["authority"] != "infinity_canonical"
        or value["run_id_sha256"] != registration.run_id_sha256
        or value["space_id"] != registration.space_id
        or value["space_slug"] != registration.space_slug
        or value["state"] != "cleanup_pending"
        or value["disposition"] != "cleanup_pending"
        or projection_cleanup not in {"pending", "blocked"}
        or type(replayed) is not bool
        or counts_value["vector_delete_jobs"] != len(outboxes[0])
        or counts_value["graph_delete_jobs"] != len(outboxes[1])
        or counts_value["cognee_delete_jobs"] != len(outboxes[2])
    ):
        fail("managed_benchmark_registry_cleanup_response_invalid")
    receipt_material = {
        "run_id_sha256": value["run_id_sha256"],
        "space_id": value["space_id"],
        "space_slug": value["space_slug"],
        "disposition": value["disposition"],
        "projection_cleanup": projection_cleanup,
        "counts": counts_value,
        "vector_delete_outbox_ids": list(outboxes[0]),
        "graph_delete_outbox_ids": list(outboxes[1]),
        "cognee_delete_outbox_ids": list(outboxes[2]),
    }
    if not hmac.compare_digest(receipt_sha256, _json_sha256(receipt_material)):
        fail("managed_benchmark_registry_cleanup_response_invalid")
    counts = ManagedBenchmarkCleanupCounts(**counts_value)
    if projection_cleanup not in {"pending", "blocked"}:
        fail("managed_benchmark_registry_cleanup_response_invalid")
    return ManagedBenchmarkCleanupReceipt(
        run_id_sha256=registration.run_id_sha256,
        space_id=registration.space_id,
        space_slug=registration.space_slug,
        projection_cleanup=projection_cleanup,
        counts=counts,
        vector_delete_outbox_ids=outboxes[0],
        graph_delete_outbox_ids=outboxes[1],
        cognee_delete_outbox_ids=outboxes[2],
        receipt_sha256=receipt_sha256,
        replayed=replayed,
    )


def parse_cleanup_completion_receipt(
    data: object,
    *,
    registration: ManagedBenchmarkRunRegistration,
    cleanup_initiation_receipt_sha256: str,
    projection_manifest_sha256: str,
) -> ManagedBenchmarkCleanupCompletionReceipt:
    """Verify the server-owned terminal cleanup authority and receipt digest."""

    value = _exact_object(
        data,
        frozenset(
            {
                "schema_version",
                "authority",
                "run_id_sha256",
                "space_id",
                "space_slug",
                "state",
                "disposition",
                "projection_cleanup",
                "projection_manifest_sha256",
                "cleanup_initiation_receipt_sha256",
                "projection_absence_proof_sha256",
                "completed_at",
                "receipt_sha256",
                "replayed",
            }
        ),
        "managed_benchmark_registry_finalize_response_invalid",
    )
    initiation_digest = digest(
        cleanup_initiation_receipt_sha256,
        "managed_benchmark_registry_finalize_response_invalid",
    )
    expected_manifest = digest(
        projection_manifest_sha256,
        "managed_benchmark_registry_finalize_response_invalid",
    )
    proof_digest = digest(
        value["projection_absence_proof_sha256"],
        "managed_benchmark_registry_finalize_response_invalid",
    )
    receipt_digest = digest(
        value["receipt_sha256"],
        "managed_benchmark_registry_finalize_response_invalid",
    )
    completed_at = utc_timestamp(
        value["completed_at"],
        "managed_benchmark_registry_finalize_response_invalid",
    )
    replayed = value["replayed"]
    if (
        value["schema_version"] != FINALIZE_CLEANUP_RESPONSE_SCHEMA_VERSION
        or value["authority"] != "infinity_canonical"
        or value["run_id_sha256"] != registration.run_id_sha256
        or value["space_id"] != registration.space_id
        or value["space_slug"] != registration.space_slug
        or value["state"] != "cleanup_complete"
        or value["disposition"] != "cleanup_complete"
        or value["projection_cleanup"] != "complete"
        or value["projection_manifest_sha256"] != expected_manifest
        or value["cleanup_initiation_receipt_sha256"] != initiation_digest
        or type(replayed) is not bool
    ):
        fail("managed_benchmark_registry_finalize_response_invalid")
    receipt_material = {
        "run_id_sha256": registration.run_id_sha256,
        "space_id": registration.space_id,
        "space_slug": registration.space_slug,
        "disposition": "cleanup_complete",
        "projection_cleanup": "complete",
        "projection_manifest_sha256": expected_manifest,
        "cleanup_initiation_receipt_sha256": initiation_digest,
        "projection_absence_proof_sha256": proof_digest,
        "completed_at": completed_at,
    }
    if not hmac.compare_digest(receipt_digest, _json_sha256(receipt_material)):
        fail("managed_benchmark_registry_finalize_response_invalid")
    return ManagedBenchmarkCleanupCompletionReceipt(
        schema_version=FINALIZE_CLEANUP_RESPONSE_SCHEMA_VERSION,
        authority="infinity_canonical",
        run_id_sha256=registration.run_id_sha256,
        space_id=registration.space_id,
        space_slug=registration.space_slug,
        state="cleanup_complete",
        disposition="cleanup_complete",
        projection_cleanup="complete",
        projection_manifest_sha256=expected_manifest,
        cleanup_initiation_receipt_sha256=initiation_digest,
        projection_absence_proof_sha256=proof_digest,
        completed_at=completed_at,
        receipt_sha256=receipt_digest,
        replayed=replayed,
    )


def parse_abort_completion_receipt(
    data: object,
    *,
    registration: ManagedBenchmarkRunRegistration,
    cleanup_initiation_receipt_sha256: str,
) -> ManagedBenchmarkAbortCompletionReceipt:
    value = _exact_object(
        data,
        frozenset(
            {
                "schema_version",
                "authority",
                "run_id_sha256",
                "binding_commitment_sha256",
                "infinity_target_identity_sha256",
                "space_id",
                "space_slug",
                "state",
                "disposition",
                "projection_cleanup",
                "cleanup_initiation_receipt_sha256",
                "cleanup_verification_sha256",
                "completed_at",
                "receipt_sha256",
                "replayed",
            }
        ),
        "managed_benchmark_registry_abort_response_invalid",
    )
    initiation = digest(
        cleanup_initiation_receipt_sha256,
        "managed_benchmark_registry_abort_response_invalid",
    )
    verification = digest(
        value["cleanup_verification_sha256"],
        "managed_benchmark_registry_abort_response_invalid",
    )
    receipt = digest(
        value["receipt_sha256"],
        "managed_benchmark_registry_abort_response_invalid",
    )
    completed_at = utc_timestamp(
        value["completed_at"],
        "managed_benchmark_registry_abort_response_invalid",
    )
    replayed = value["replayed"]
    if (
        value["schema_version"] != FINALIZE_ABORT_RESPONSE_SCHEMA_VERSION
        or value["authority"] != "infinity_canonical"
        or value["run_id_sha256"] != registration.run_id_sha256
        or value["binding_commitment_sha256"] != registration.binding_commitment_sha256
        or value["infinity_target_identity_sha256"] != registration.infinity_target_identity_sha256
        or value["space_id"] != registration.space_id
        or value["space_slug"] != registration.space_slug
        or value["state"] != "cleanup_aborted"
        or value["disposition"] != "abort_complete"
        or value["projection_cleanup"] != "unsealed_abort_complete"
        or value["cleanup_initiation_receipt_sha256"] != initiation
        or type(replayed) is not bool
    ):
        fail("managed_benchmark_registry_abort_response_invalid")
    material = {
        key: item
        for key, item in value.items()
        if key not in {"schema_version", "authority", "state", "replayed", "receipt_sha256"}
    }
    if not hmac.compare_digest(receipt, _json_sha256(material)):
        fail("managed_benchmark_registry_abort_response_invalid")
    return ManagedBenchmarkAbortCompletionReceipt(
        schema_version=FINALIZE_ABORT_RESPONSE_SCHEMA_VERSION,
        authority="infinity_canonical",
        run_id_sha256=registration.run_id_sha256,
        binding_commitment_sha256=registration.binding_commitment_sha256,
        infinity_target_identity_sha256=registration.infinity_target_identity_sha256,
        space_id=registration.space_id,
        space_slug=registration.space_slug,
        state="cleanup_aborted",
        disposition="abort_complete",
        projection_cleanup="unsealed_abort_complete",
        cleanup_initiation_receipt_sha256=initiation,
        cleanup_verification_sha256=verification,
        completed_at=completed_at,
        receipt_sha256=receipt,
        replayed=replayed,
    )


def parse_lifecycle_snapshot(
    data: object,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    target_identity_sha256: str,
    space_slug: str,
) -> ManagedBenchmarkRunLifecycleSnapshot:
    """Parse one exact server-owned lifecycle snapshot for restart recovery."""

    value = _exact_object(
        data,
        frozenset(
            {
                "schema_version",
                "authority",
                "run_id_sha256",
                "binding_commitment_sha256",
                "infinity_target_identity_sha256",
                "space_id",
                "space_slug",
                "state",
                "projection_cleanup_state",
                "projection_manifest_sha256",
                "cleanup_receipt",
                "completion_receipt",
            }
        ),
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    expected_run = digest(
        run_id_sha256,
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    expected_binding = digest(
        binding_commitment_sha256,
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    expected_target = digest(
        target_identity_sha256,
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    expected_slug = space_slug
    space_id = canonical_id(
        value["space_id"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    if (
        value["schema_version"] != "memory-comparison-run-lifecycle-response.v1"
        or value["authority"] != "infinity_canonical"
        or value["run_id_sha256"] != expected_run
        or value["binding_commitment_sha256"] != expected_binding
        or value["infinity_target_identity_sha256"] != expected_target
        or value["space_slug"] != expected_slug
    ):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    manifest_value = value["projection_manifest_sha256"]
    manifest = (
        None
        if manifest_value is None
        else digest(
            manifest_value,
            "managed_benchmark_registry_lifecycle_response_invalid",
        )
    )
    cleanup = _parse_persisted_cleanup_receipt(
        value["cleanup_receipt"],
        run_id_sha256=expected_run,
        space_id=space_id,
        space_slug=expected_slug,
    )
    completion = _parse_persisted_completion_receipt(
        value["completion_receipt"],
        run_id_sha256=expected_run,
        space_id=space_id,
        space_slug=expected_slug,
    )
    return ManagedBenchmarkRunLifecycleSnapshot(
        schema_version="memory-comparison-run-lifecycle-response.v1",
        authority="infinity_canonical",
        run_id_sha256=expected_run,
        binding_commitment_sha256=expected_binding,
        infinity_target_identity_sha256=expected_target,
        space_id=space_id,
        space_slug=expected_slug,
        state=value["state"],
        projection_cleanup_state=value["projection_cleanup_state"],
        projection_manifest_sha256=manifest,
        cleanup_receipt=cleanup,
        completion_receipt=completion,
    )


def _parse_persisted_cleanup_receipt(
    data: object,
    *,
    run_id_sha256: str,
    space_id: str,
    space_slug: str,
) -> ManagedBenchmarkPersistedCleanupReceipt | None:
    if data is None:
        return None
    value = _exact_object(
        data,
        frozenset(
            {
                "run_id_sha256",
                "space_id",
                "space_slug",
                "disposition",
                "projection_cleanup",
                "counts",
                *_OUTBOX_KEYS,
                "receipt_sha256",
            }
        ),
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    counts_value = _exact_object(
        value["counts"],
        frozenset(_COUNT_KEYS),
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    if any(type(counts_value[key]) is not int or counts_value[key] < 0 for key in _COUNT_KEYS):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    outboxes = tuple(
        _positive_int_list_for(value[key], "managed_benchmark_registry_lifecycle_response_invalid")
        for key in _OUTBOX_KEYS
    )
    flattened = tuple(item for lane in outboxes for item in lane)
    receipt_sha256 = digest(
        value["receipt_sha256"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    if (
        value["run_id_sha256"] != run_id_sha256
        or value["space_id"] != space_id
        or value["space_slug"] != space_slug
        or value["disposition"] != "cleanup_pending"
        or value["projection_cleanup"] not in {"pending", "blocked"}
        or len(flattened) != len(set(flattened))
        or counts_value["vector_delete_jobs"] != len(outboxes[0])
        or counts_value["graph_delete_jobs"] != len(outboxes[1])
        or counts_value["cognee_delete_jobs"] != len(outboxes[2])
    ):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    material = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not hmac.compare_digest(receipt_sha256, _json_sha256(material)):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    return ManagedBenchmarkPersistedCleanupReceipt(
        run_id_sha256=run_id_sha256,
        space_id=space_id,
        space_slug=space_slug,
        disposition="cleanup_pending",
        projection_cleanup=value["projection_cleanup"],
        counts=ManagedBenchmarkCleanupCounts(**counts_value),
        vector_delete_outbox_ids=outboxes[0],
        graph_delete_outbox_ids=outboxes[1],
        cognee_delete_outbox_ids=outboxes[2],
        receipt_sha256=receipt_sha256,
    )


def _parse_persisted_completion_receipt(
    data: object,
    *,
    run_id_sha256: str,
    space_id: str,
    space_slug: str,
) -> ManagedBenchmarkPersistedCompletionReceipt | ManagedBenchmarkPersistedAbortReceipt | None:
    if data is None:
        return None
    if type(data) is dict and data.get("disposition") == "abort_complete":
        return _parse_persisted_abort_receipt(
            data,
            run_id_sha256=run_id_sha256,
            space_id=space_id,
            space_slug=space_slug,
        )
    value = _exact_object(
        data,
        frozenset(
            {
                "run_id_sha256",
                "space_id",
                "space_slug",
                "disposition",
                "projection_cleanup",
                "projection_manifest_sha256",
                "cleanup_initiation_receipt_sha256",
                "projection_absence_proof_sha256",
                "completed_at",
                "receipt_sha256",
            }
        ),
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    manifest = digest(
        value["projection_manifest_sha256"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    initiation = digest(
        value["cleanup_initiation_receipt_sha256"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    proof = digest(
        value["projection_absence_proof_sha256"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    receipt = digest(
        value["receipt_sha256"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    completed_at = utc_timestamp(
        value["completed_at"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    if (
        value["run_id_sha256"] != run_id_sha256
        or value["space_id"] != space_id
        or value["space_slug"] != space_slug
        or value["disposition"] != "cleanup_complete"
        or value["projection_cleanup"] != "complete"
    ):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    material = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not hmac.compare_digest(receipt, _json_sha256(material)):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    return ManagedBenchmarkPersistedCompletionReceipt(
        run_id_sha256=run_id_sha256,
        space_id=space_id,
        space_slug=space_slug,
        disposition="cleanup_complete",
        projection_cleanup="complete",
        projection_manifest_sha256=manifest,
        cleanup_initiation_receipt_sha256=initiation,
        projection_absence_proof_sha256=proof,
        completed_at=completed_at,
        receipt_sha256=receipt,
    )


def _parse_persisted_abort_receipt(
    data: object,
    *,
    run_id_sha256: str,
    space_id: str,
    space_slug: str,
) -> ManagedBenchmarkPersistedAbortReceipt:
    value = _exact_object(
        data,
        frozenset(
            {
                "run_id_sha256",
                "binding_commitment_sha256",
                "infinity_target_identity_sha256",
                "space_id",
                "space_slug",
                "disposition",
                "projection_cleanup",
                "cleanup_initiation_receipt_sha256",
                "cleanup_verification_sha256",
                "completed_at",
                "receipt_sha256",
            }
        ),
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    digest_keys = (
        "run_id_sha256",
        "binding_commitment_sha256",
        "infinity_target_identity_sha256",
        "cleanup_initiation_receipt_sha256",
        "cleanup_verification_sha256",
        "receipt_sha256",
    )
    parsed = {
        key: digest(value[key], "managed_benchmark_registry_lifecycle_response_invalid")
        for key in digest_keys
    }
    completed_at = utc_timestamp(
        value["completed_at"],
        "managed_benchmark_registry_lifecycle_response_invalid",
    )
    if (
        parsed["run_id_sha256"] != run_id_sha256
        or value["space_id"] != space_id
        or value["space_slug"] != space_slug
        or value["disposition"] != "abort_complete"
        or value["projection_cleanup"] != "unsealed_abort_complete"
    ):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    material = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not hmac.compare_digest(parsed["receipt_sha256"], _json_sha256(material)):
        fail("managed_benchmark_registry_lifecycle_response_invalid")
    return ManagedBenchmarkPersistedAbortReceipt(
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=parsed["binding_commitment_sha256"],
        infinity_target_identity_sha256=parsed["infinity_target_identity_sha256"],
        space_id=space_id,
        space_slug=space_slug,
        disposition="abort_complete",
        projection_cleanup="unsealed_abort_complete",
        cleanup_initiation_receipt_sha256=parsed["cleanup_initiation_receipt_sha256"],
        cleanup_verification_sha256=parsed["cleanup_verification_sha256"],
        completed_at=completed_at,
        receipt_sha256=parsed["receipt_sha256"],
    )


def _require_before_deadline(
    deadline: datetime,
    clock: Callable[[], datetime],
) -> None:
    remaining_io_timeout(deadline=deadline, timeout_seconds=float("inf"), clock=clock)


def _clock_utc(clock: Callable[[], datetime]) -> datetime:
    try:
        now = clock()
    except KeyboardInterrupt:
        raise KeyboardInterrupt() from None
    except SystemExit as error:
        safe_code = error.code if type(error.code) is int or error.code is None else 1
        raise SystemExit(safe_code) from None
    except BaseException:
        fail("managed_benchmark_registry_clock_failed")
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        fail("managed_benchmark_registry_clock_failed")
    return now.astimezone(UTC)


def _decode_json(body: bytes) -> object:
    try:
        return json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("managed_benchmark_registry_response_invalid")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail("managed_benchmark_registry_response_invalid")
        result[key] = value
    return result


def _exact_object(value: object, keys: frozenset[str], code: str) -> dict[str, object]:
    result = _object(value)
    if set(result) != keys:
        fail(code)
    return result


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        fail("managed_benchmark_registry_response_invalid")
    return value


def _positive_int_list(value: object) -> tuple[int, ...]:
    if type(value) is not list or any(type(item) is not int or item <= 0 for item in value):
        fail("managed_benchmark_registry_cleanup_response_invalid")
    return tuple(value)


def _positive_int_list_for(value: object, code: str) -> tuple[int, ...]:
    if type(value) is not list or any(type(item) is not int or item <= 0 for item in value):
        fail(code)
    return tuple(value)


def _json_sha256(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "fresh_io_deadline",
    "parse_abort_completion_receipt",
    "parse_cleanup_completion_receipt",
    "parse_cleanup_receipt",
    "parse_lifecycle_snapshot",
    "parse_projection_seal",
    "parse_registration",
    "read_json_envelope",
    "remaining_io_timeout",
)
