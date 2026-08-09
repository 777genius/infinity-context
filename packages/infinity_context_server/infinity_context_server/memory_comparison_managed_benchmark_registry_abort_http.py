"""Manifestless abort finalization for the managed benchmark registry adapter."""

from __future__ import annotations

from typing import Any

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    FINALIZE_ABORT_REQUEST_SCHEMA_VERSION,
    REGISTRY_RUNS_PATH,
    ManagedBenchmarkAbortCompletionReceipt,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkRunRegistration,
    digest,
    fail,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    idempotency_key as validated_idempotency_key,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_wire import (
    fresh_io_deadline,
    parse_abort_completion_receipt,
)


def finalize_unsealed_abort(
    adapter: Any,
    *,
    cleanup_initiation_receipt_sha256: str,
    idempotency_key: str | None,
) -> ManagedBenchmarkAbortCompletionReceipt:
    initiation = digest(
        cleanup_initiation_receipt_sha256,
        "managed_benchmark_registry_abort_invalid",
    )
    registration, recovering = _reserve(adapter, initiation, idempotency_key)
    dispatched = False

    def mark_dispatched() -> None:
        nonlocal dispatched
        dispatched = True

    try:
        data, _ = adapter._request(
            "POST",
            f"{REGISTRY_RUNS_PATH}/{registration.run_id_sha256}/cleanup/abort/finalize",
            payload={
                "schema_version": FINALIZE_ABORT_REQUEST_SCHEMA_VERSION,
                "binding_commitment_sha256": registration.binding_commitment_sha256,
                "infinity_target_identity_sha256": (registration.infinity_target_identity_sha256),
                "space_id": registration.space_id,
                "space_slug": registration.space_slug,
                "receipt_sha256": initiation,
                "cleanup_plan_sha256": registration.cleanup_plan_sha256,
            },
            idempotency_key=adapter._abort_finalize_idempotency_key,
            accepted_statuses=frozenset({200}),
            deadline=fresh_io_deadline(
                timeout_seconds=adapter._config.cleanup_recovery_timeout_seconds,
                clock=adapter._config.clock,
            ),
            on_dispatch=mark_dispatched,
        )
        receipt = parse_abort_completion_receipt(
            data,
            registration=registration,
            cleanup_initiation_receipt_sha256=initiation,
        )
    except BaseException:
        outcome_unknown = dispatched or recovering
        with adapter._lock:
            adapter._phase = "finalize_outcome_unknown" if outcome_unknown else "pending"
            adapter._lifecycle_state = "unknown" if outcome_unknown else "cleanup_pending"
        raise
    with adapter._lock:
        if adapter._phase != "finalizing":
            adapter._phase = "failed"
            fail("managed_benchmark_registry_lifecycle_invalid")
        adapter._completion_receipt = receipt
        adapter._lifecycle_state = "cleanup_aborted"
        adapter._phase = "complete"
    adapter._close_client(suppress_failure=True)
    return receipt


def _reserve(
    adapter: Any,
    initiation: str,
    raw_idempotency_key: str | None,
) -> tuple[ManagedBenchmarkRunRegistration, bool]:
    with adapter._lock:
        registration = adapter._registration
        cleanup = adapter._cleanup_receipt
        if (
            adapter._phase not in {"pending", "finalize_outcome_unknown"}
            or type(registration) is not ManagedBenchmarkRunRegistration
            or type(cleanup)
            not in {ManagedBenchmarkCleanupReceipt, ManagedBenchmarkPersistedCleanupReceipt}
            or cleanup.receipt_sha256 != initiation
            or cleanup.projection_cleanup != "blocked"
            or adapter._projection_manifest_sha256 is not None
        ):
            fail("managed_benchmark_registry_lifecycle_invalid")
        key = validated_idempotency_key(
            raw_idempotency_key,
            operation="finalize-abort",
            run_id_sha256=registration.run_id_sha256,
            binding_commitment_sha256=registration.binding_commitment_sha256,
            target_identity_sha256=registration.infinity_target_identity_sha256,
        )
        recovering = adapter._phase == "finalize_outcome_unknown"
        if recovering:
            if adapter._abort_finalize_idempotency_key != key:
                fail("managed_benchmark_registry_lifecycle_invalid")
        else:
            adapter._abort_finalize_idempotency_key = key
        adapter._phase = "finalizing"
        return registration, recovering


__all__ = ("finalize_unsealed_abort",)
