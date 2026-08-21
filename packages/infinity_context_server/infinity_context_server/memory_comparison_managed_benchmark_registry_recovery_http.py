"""Bounded lifecycle recovery for the managed benchmark registry adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    REGISTRATION_SCHEMA_VERSION,
    REGISTRY_RUNS_PATH,
    ManagedBenchmarkRunLifecycleSnapshot,
    ManagedBenchmarkRunRegistration,
    digest,
    fail,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    space_slug as validated_space_slug,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_wire import (
    fresh_io_deadline,
    parse_lifecycle_snapshot,
)


@dataclass(frozen=True, slots=True)
class _LifecycleRecoveryAttempt:
    run_id_sha256: str
    binding_commitment_sha256: str
    space_slug: str
    cleanup_plan_sha256: str


def recover_lifecycle(
    adapter: Any,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    space_slug: str,
    cleanup_plan_sha256: str,
) -> ManagedBenchmarkRunLifecycleSnapshot:
    """Recover and install one canonical lifecycle using a fresh bounded GET."""

    snapshot = _recover_lifecycle(
        adapter,
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        space_slug=space_slug,
        cleanup_plan_sha256=cleanup_plan_sha256,
        allow_missing=False,
    )
    if snapshot is None:
        fail("managed_benchmark_registry_response_rejected")
    return snapshot


def recover_lifecycle_or_missing(
    adapter: Any,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    space_slug: str,
    cleanup_plan_sha256: str,
) -> ManagedBenchmarkRunLifecycleSnapshot | None:
    """Recover lifecycle, returning None only for an exact 404 response."""

    return _recover_lifecycle(
        adapter,
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        space_slug=space_slug,
        cleanup_plan_sha256=cleanup_plan_sha256,
        allow_missing=True,
    )


def _recover_lifecycle(
    adapter: Any,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    space_slug: str,
    cleanup_plan_sha256: str,
    allow_missing: bool,
) -> ManagedBenchmarkRunLifecycleSnapshot | None:

    attempt = _LifecycleRecoveryAttempt(
        digest(run_id_sha256, "managed_benchmark_registry_recovery_invalid"),
        digest(
            binding_commitment_sha256,
            "managed_benchmark_registry_recovery_invalid",
        ),
        validated_space_slug(
            space_slug,
            "managed_benchmark_registry_recovery_invalid",
        ),
        digest(cleanup_plan_sha256, "managed_benchmark_registry_recovery_invalid"),
    )
    previous_phase = _reserve(adapter, attempt)
    dispatched = False

    def mark_dispatched() -> None:
        nonlocal dispatched
        dispatched = True

    try:
        data, status = adapter._request(
            "GET",
            f"{REGISTRY_RUNS_PATH}/{attempt.run_id_sha256}/cleanup",
            payload=None,
            idempotency_key=None,
            accepted_statuses=frozenset({200}),
            deadline=fresh_io_deadline(
                timeout_seconds=adapter._config.cleanup_recovery_timeout_seconds,
                clock=adapter._config.clock,
            ),
            on_dispatch=mark_dispatched,
            missing_statuses=frozenset({404}) if allow_missing else frozenset(),
        )
        if status == 404:
            with adapter._lock:
                adapter._phase = previous_phase
                adapter._recovery_attempt = None
            return None
        snapshot = parse_lifecycle_snapshot(
            data,
            run_id_sha256=attempt.run_id_sha256,
            binding_commitment_sha256=attempt.binding_commitment_sha256,
            target_identity_sha256=adapter._config.target_identity_sha256,
            space_slug=attempt.space_slug,
            expected_cleanup_plan_sha256=attempt.cleanup_plan_sha256,
        )
        _bootstrap(adapter, snapshot)
    except BaseException:
        if dispatched:
            adapter._mark_recovery_outcome_unknown()
        else:
            adapter._restore_phase("recovering", previous_phase)
        raise
    if snapshot.state in {"cleanup_complete", "cleanup_aborted"}:
        adapter._close_client(suppress_failure=True)
    return snapshot


__all__ = ("recover_lifecycle", "recover_lifecycle_or_missing")


def _reserve(adapter: Any, attempt: _LifecycleRecoveryAttempt) -> str:
    with adapter._lock:
        previous_phase = adapter._phase
        if previous_phase == "ready":
            adapter._recovery_attempt = attempt
        elif previous_phase == "recovery_required":
            registration = adapter._registration
            if (
                type(registration) is not ManagedBenchmarkRunRegistration
                or registration.run_id_sha256 != attempt.run_id_sha256
                or registration.binding_commitment_sha256 != attempt.binding_commitment_sha256
                or registration.space_slug != attempt.space_slug
                or registration.cleanup_plan_sha256 != attempt.cleanup_plan_sha256
            ):
                fail("managed_benchmark_registry_lifecycle_invalid")
            adapter._recovery_attempt = attempt
        elif previous_phase != "recovery_outcome_unknown" or adapter._recovery_attempt != attempt:
            fail("managed_benchmark_registry_lifecycle_invalid")
        adapter._phase = "recovering"
        return previous_phase


def _bootstrap(
    adapter: Any,
    snapshot: ManagedBenchmarkRunLifecycleSnapshot,
) -> None:
    with adapter._lock:
        if adapter._phase != "recovering":
            adapter._phase = "failed"
            fail("managed_benchmark_registry_lifecycle_invalid")
        previous_registration = adapter._registration
        state_order = {
            "active": 0,
            "cleanup_pending": 1,
            "cleanup_complete": 2,
            "cleanup_aborted": 2,
        }
        if type(previous_registration) is ManagedBenchmarkRunRegistration and (
            previous_registration.run_id_sha256 != snapshot.run_id_sha256
            or previous_registration.binding_commitment_sha256 != snapshot.binding_commitment_sha256
            or previous_registration.infinity_target_identity_sha256
            != snapshot.infinity_target_identity_sha256
            or previous_registration.space_id != snapshot.space_id
            or previous_registration.space_slug != snapshot.space_slug
            or previous_registration.cleanup_plan_sha256 != snapshot.cleanup_plan_sha256
            or state_order[snapshot.state] < state_order[previous_registration.state]
        ):
            fail("managed_benchmark_registry_lifecycle_response_invalid")
        adapter._registration = ManagedBenchmarkRunRegistration(
            schema_version=REGISTRATION_SCHEMA_VERSION,
            authority="infinity_canonical",
            run_id_sha256=snapshot.run_id_sha256,
            binding_commitment_sha256=snapshot.binding_commitment_sha256,
            infinity_target_identity_sha256=snapshot.infinity_target_identity_sha256,
            space_id=snapshot.space_id,
            space_slug=snapshot.space_slug,
            state=snapshot.state,
            created=False,
            cleanup_plan_sha256=snapshot.cleanup_plan_sha256,
            cleanup_plan_state="sealed",
        )
        adapter._projection_manifest_sha256 = snapshot.projection_manifest_sha256
        adapter._cleanup_receipt = snapshot.cleanup_receipt
        adapter._completion_receipt = snapshot.completion_receipt
        adapter._recovered_cleanup_receipt = snapshot.cleanup_receipt
        adapter._recovered_completion_receipt = snapshot.completion_receipt
        adapter._lifecycle_state = snapshot.state
        if snapshot.state == "active":
            adapter._phase = (
                "sealed" if snapshot.projection_cleanup_state == "sealed" else "registered"
            )
        elif snapshot.state == "cleanup_pending":
            adapter._phase = "pending"
        else:
            adapter._phase = "complete"


__all__ = ("recover_lifecycle",)
