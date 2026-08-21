"""Stateful HTTP transport adapter for the canonical benchmark run registry."""

from __future__ import annotations

import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import final

import httpx
from infinity_context_core.application.use_cases.benchmark_runs import (
    validate_projection_manifest,
)
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    ManagedBenchmarkCleanupTargetAuthority,
    validate_managed_benchmark_cleanup_plan,
    validate_managed_benchmark_cleanup_target_authority,
)

from infinity_context_server.memory_comparison_managed_benchmark_registry_abort_http import (
    finalize_unsealed_abort as _finalize_unsealed_abort,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    FINALIZE_CLEANUP_REQUEST_SCHEMA_VERSION,
    REGISTRY_RUNS_PATH,
    ManagedBenchmarkAbortCompletionReceipt,
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkCleanupCounts,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkPersistedAbortReceipt,
    ManagedBenchmarkPersistedCleanupReceipt,
    ManagedBenchmarkPersistedCompletionReceipt,
    ManagedBenchmarkProjectionSeal,
    ManagedBenchmarkRecoveryAuthorityTransfer,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRegistryHttpError,
    ManagedBenchmarkRunLifecycleSnapshot,
    ManagedBenchmarkRunRegistration,
    digest,
    fail,
    managed_benchmark_registry_idempotency_key,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    idempotency_key as _validated_idempotency_key,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    space_slug as _validated_space_slug,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_recovery_http import (
    recover_lifecycle as _recover_lifecycle,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_recovery_http import (
    recover_lifecycle_or_missing as _recover_lifecycle_or_missing,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_transfer import (
    relinquish_recovery_authority as _relinquish_recovery_authority,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_transport import (
    close_registry_transport,
    request_registry_json,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_wire import (
    fresh_io_deadline,
    parse_cleanup_completion_receipt,
    parse_cleanup_receipt,
    parse_projection_seal,
    parse_registration,
)

_CLEANUP_READY_PHASES = frozenset({"registered", "sealed", "seal_outcome_unknown"})
_CLEANUP_REGISTRATION_PHASES = _CLEANUP_READY_PHASES | frozenset({"cleanup_outcome_unknown"})
_CLEANUP_REQUIRED_PHASES = frozenset(
    {
        "registering",
        "registration_outcome_unknown",
        "registered",
        "sealing",
        "sealed",
        "seal_outcome_unknown",
        "cleaning",
        "cleanup_outcome_unknown",
        "pending",
        "finalizing",
        "finalize_outcome_unknown",
        "recovery_required",
        "recovering",
        "recovery_outcome_unknown",
    }
)


@dataclass(frozen=True, slots=True)
class _RegistrationAttempt:
    run_id_sha256: str
    binding_commitment_sha256: str
    space_slug: str
    idempotency_key: str
    cleanup_plan_sha256: str


@dataclass(frozen=True, slots=True)
class _CleanupAttempt:
    registration: ManagedBenchmarkRunRegistration
    idempotency_key: str
    seal_attempt_sha256: str | None
    confirm_seal_from_pending_cleanup: bool


@dataclass(frozen=True, slots=True)
class _FinalizeAttempt:
    registration: ManagedBenchmarkRunRegistration
    cleanup_initiation_receipt_sha256: str
    projection_manifest_sha256: str
    idempotency_key: str


@final
class ManagedBenchmarkRegistryHttpAdapter:
    """Own one client and its exact register, optional seal, and cleanup sequence.

    A successful registration grants cleanup authority immediately. If the seal PUT
    fails or an HTTP outcome cannot be verified, exact same-key recovery remains
    available through fresh bounded cleanup/recovery attempts. Nonterminal close is
    refused with a fixed cleanup-required code until exact recovery authority is transferred.
    """

    __slots__ = (
        "_abort_finalize_idempotency_key",
        "_client",
        "_close_attempted",
        "_close_warning_code",
        "_cleanup_attempt",
        "_cleanup_receipt",
        "_completion_receipt",
        "_config",
        "_finalize_attempt",
        "_lifecycle_state",
        "_lock",
        "_phase",
        "_projection_manifest_sha256",
        "_recovered_cleanup_receipt",
        "_recovered_completion_receipt",
        "_recovery_attempt",
        "_registration",
        "_registration_attempt",
        "_seal_attempt_sha256",
    )
    _request = request_registry_json

    def __init__(self, config: ManagedBenchmarkRegistryHttpConfig) -> None:
        if type(config) is not ManagedBenchmarkRegistryHttpConfig:
            fail("managed_benchmark_registry_config_invalid")
        transport = config.transport
        if transport is None:
            try:
                transport = httpx.HTTPTransport(retries=0, trust_env=False)
            except Exception:
                fail("managed_benchmark_registry_client_failed")
        try:
            client = httpx.Client(
                headers={"Authorization": f"Bearer {config.admin_bearer_token}"},
                timeout=float(config.timeout_seconds),
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            )
        except Exception:
            with suppress(Exception):
                transport.close()
            fail("managed_benchmark_registry_client_failed")
        self._config = config
        self._client = client
        self._lock = threading.Lock()
        self._phase = "ready"
        self._registration: ManagedBenchmarkRunRegistration | None = None
        self._registration_attempt: _RegistrationAttempt | None = None
        self._cleanup_attempt: _CleanupAttempt | None = None
        self._cleanup_receipt: (
            ManagedBenchmarkCleanupReceipt | ManagedBenchmarkPersistedCleanupReceipt | None
        ) = None
        self._completion_receipt: (
            ManagedBenchmarkAbortCompletionReceipt
            | ManagedBenchmarkPersistedAbortReceipt
            | ManagedBenchmarkCleanupCompletionReceipt
            | ManagedBenchmarkPersistedCompletionReceipt
            | None
        ) = None
        self._finalize_attempt: _FinalizeAttempt | None = None
        self._abort_finalize_idempotency_key: str | None = None
        self._projection_manifest_sha256: str | None = None
        self._seal_attempt_sha256: str | None = None
        self._recovery_attempt: object | None = None
        self._recovered_cleanup_receipt: ManagedBenchmarkPersistedCleanupReceipt | None = None
        self._recovered_completion_receipt: (
            ManagedBenchmarkPersistedCompletionReceipt
            | ManagedBenchmarkPersistedAbortReceipt
            | None
        ) = None
        self._lifecycle_state: str | None = None
        self._close_attempted = False
        self._close_warning_code: str | None = None

    def __repr__(self) -> str:
        return "ManagedBenchmarkRegistryHttpAdapter(<redacted>)"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedBenchmarkRegistryHttpAdapter is final")

    def __copy__(self) -> object:
        raise TypeError("ManagedBenchmarkRegistryHttpAdapter is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("ManagedBenchmarkRegistryHttpAdapter is noncopyable")

    @property
    def retries(self) -> int:
        return 0

    @property
    def cleanup_required(self) -> bool:
        with self._lock:
            return self._phase in _CLEANUP_REQUIRED_PHASES

    @property
    def close_warning_code(self) -> str | None:
        with self._lock:
            return self._close_warning_code

    @property
    def lifecycle_state(self) -> str | None:
        with self._lock:
            return self._lifecycle_state

    @property
    def recovered_cleanup_receipt(self) -> ManagedBenchmarkPersistedCleanupReceipt | None:
        with self._lock:
            return self._recovered_cleanup_receipt

    @property
    def cleanup_receipt(
        self,
    ) -> ManagedBenchmarkCleanupReceipt | ManagedBenchmarkPersistedCleanupReceipt | None:
        with self._lock:
            return self._cleanup_receipt

    @property
    def recovered_completion_receipt(
        self,
    ) -> ManagedBenchmarkPersistedCompletionReceipt | ManagedBenchmarkPersistedAbortReceipt | None:
        with self._lock:
            return self._recovered_completion_receipt

    def register(
        self,
        *,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        space_slug: str,
        cleanup_plan: ManagedBenchmarkCleanupPlan,
        idempotency_key: str | None = None,
    ) -> ManagedBenchmarkRunRegistration:
        run_id = digest(run_id_sha256, "managed_benchmark_registry_registration_invalid")
        binding = digest(
            binding_commitment_sha256,
            "managed_benchmark_registry_registration_invalid",
        )
        slug = _validated_space_slug(
            space_slug,
            "managed_benchmark_registry_registration_invalid",
        )
        if type(cleanup_plan) is not ManagedBenchmarkCleanupPlan:
            fail("managed_benchmark_registry_registration_invalid")
        try:
            plan = validate_managed_benchmark_cleanup_plan(
                cleanup_plan.value,
                cleanup_plan.sha256,
                run_id_sha256=run_id,
                binding_commitment_sha256=binding,
                infinity_target_identity_sha256=self._config.target_identity_sha256,
                space_slug=slug,
            )
        except Exception:
            fail("managed_benchmark_registry_registration_invalid")
        key = _validated_idempotency_key(
            idempotency_key,
            operation="register",
            run_id_sha256=run_id,
            binding_commitment_sha256=binding,
            target_identity_sha256=self._config.target_identity_sha256,
        )
        attempt = _RegistrationAttempt(run_id, binding, slug, key, plan.sha256)
        recovering = self._reserve_registration(attempt)
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, status = request_registry_json(
                self,
                "POST",
                REGISTRY_RUNS_PATH,
                payload={
                    "schema_version": "memory-comparison-run-registration.v2",
                    "run_id_sha256": run_id,
                    "binding_commitment_sha256": binding,
                    "infinity_target_identity_sha256": self._config.target_identity_sha256,
                    "space_slug": slug,
                    "cleanup_plan": plan.value,
                    "cleanup_plan_sha256": plan.sha256,
                },
                idempotency_key=key,
                accepted_statuses=frozenset({200, 201}),
                deadline=(
                    fresh_io_deadline(
                        timeout_seconds=self._config.cleanup_recovery_timeout_seconds,
                        clock=self._config.clock,
                    )
                    if recovering
                    else self._config.benchmark_deadline
                ),
                on_dispatch=mark_dispatched,
            )
            registration = parse_registration(
                data,
                status=status,
                run_id_sha256=run_id,
                binding_commitment_sha256=binding,
                target_identity_sha256=self._config.target_identity_sha256,
                space_slug=slug,
                cleanup_plan_sha256=plan.sha256,
            )
        except BaseException:
            if dispatched:
                self._mark_registration_outcome_unknown()
            elif recovering:
                self._restore_phase("registering", "registration_outcome_unknown")
            else:
                self._terminal_preserving_primary()
            raise
        with self._lock:
            if self._phase != "registering":
                self._phase = "failed"
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._registration = registration
            if registration.created:
                self._phase = "registered"
                self._lifecycle_state = "active"
            else:
                self._phase = "recovery_required"
                self._lifecycle_state = "unknown"
        if not registration.created:
            _recover_lifecycle(
                self,
                run_id_sha256=run_id,
                binding_commitment_sha256=binding,
                space_slug=slug,
                cleanup_plan_sha256=plan.sha256,
            )
        return registration

    def prepare_cleanup_target_authority(self) -> ManagedBenchmarkCleanupTargetAuthority:
        with self._lock:
            if self._phase != "ready":
                fail("managed_benchmark_registry_lifecycle_invalid")
        data, _ = request_registry_json(
            self,
            "POST",
            f"{REGISTRY_RUNS_PATH}/cleanup-target-authority",
            payload={
                "schema_version": "memory-comparison-cleanup-target-authority-request.v1",
                "infinity_target_identity_sha256": self._config.target_identity_sha256,
            },
            idempotency_key=None,
            accepted_statuses=frozenset({200}),
            deadline=self._config.benchmark_deadline,
            on_dispatch=lambda: None,
        )
        try:
            return validate_managed_benchmark_cleanup_target_authority(
                data,
                infinity_target_identity_sha256=self._config.target_identity_sha256,
            )
        except Exception:
            fail("managed_benchmark_registry_registration_invalid")

    def recover_lifecycle(
        self,
        *,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        space_slug: str,
        cleanup_plan_sha256: str,
    ) -> ManagedBenchmarkRunLifecycleSnapshot:
        """Recover one canonical lifecycle after a process restart or lost GET."""

        return _recover_lifecycle(
            self,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            space_slug=space_slug,
            cleanup_plan_sha256=cleanup_plan_sha256,
        )

    def recover_lifecycle_or_missing(
        self,
        *,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        space_slug: str,
        cleanup_plan_sha256: str,
    ) -> ManagedBenchmarkRunLifecycleSnapshot | None:
        """Return None only for an authenticated exact lifecycle 404."""

        return _recover_lifecycle_or_missing(
            self,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            space_slug=space_slug,
            cleanup_plan_sha256=cleanup_plan_sha256,
        )

    def seal_projection_manifest(
        self,
        *,
        projection_manifest: dict[str, object],
        projection_manifest_sha256: str,
    ) -> ManagedBenchmarkProjectionSeal:
        registration = self._registration_for(frozenset({"registered"}))
        manifest_digest = digest(
            projection_manifest_sha256,
            "managed_benchmark_registry_manifest_invalid",
        )
        try:
            canonical_manifest = validate_projection_manifest(
                projection_manifest,
                manifest_digest,
                run_id_sha256=registration.run_id_sha256,
                binding_commitment_sha256=registration.binding_commitment_sha256,
                infinity_target_identity_sha256=registration.infinity_target_identity_sha256,
                space_id=registration.space_id,
                cleanup_plan_sha256=registration.cleanup_plan_sha256,
            )
        except Exception:
            fail("managed_benchmark_registry_manifest_invalid")
        self._reserve_seal(manifest_digest)
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, _ = request_registry_json(
                self,
                "PUT",
                f"{REGISTRY_RUNS_PATH}/{registration.run_id_sha256}/projection-manifest",
                payload={
                    "schema_version": "memory-comparison-projection-manifest-seal.v1",
                    "projection_manifest_sha256": manifest_digest,
                    "projection_manifest": canonical_manifest,
                },
                idempotency_key=None,
                accepted_statuses=frozenset({200}),
                deadline=self._config.benchmark_deadline,
                on_dispatch=mark_dispatched,
            )
            sealed = parse_projection_seal(
                data,
                registration=registration,
                projection_manifest_sha256=manifest_digest,
            )
        except BaseException:
            if dispatched:
                self._mark_seal_outcome_unknown()
            else:
                self._restore_phase("sealing", "registered")
            raise
        self._record_projection_seal(sealed)
        return sealed

    def begin_cleanup(
        self,
        *,
        idempotency_key: str | None = None,
    ) -> ManagedBenchmarkCleanupReceipt:
        """Start cleanup after registration, regardless of seal outcome."""

        registration, seal_attempt_sha256, confirm_seal = self._cleanup_context()
        key = _validated_idempotency_key(
            idempotency_key,
            operation="begin-cleanup",
            run_id_sha256=registration.run_id_sha256,
            binding_commitment_sha256=registration.binding_commitment_sha256,
            target_identity_sha256=registration.infinity_target_identity_sha256,
        )
        attempt = _CleanupAttempt(
            registration,
            key,
            seal_attempt_sha256,
            confirm_seal,
        )
        previous_phase = self._reserve_cleanup(attempt)
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, _ = request_registry_json(
                self,
                "DELETE",
                f"{REGISTRY_RUNS_PATH}/{registration.run_id_sha256}",
                payload={
                    "schema_version": "memory-comparison-run-cleanup.v2",
                    "binding_commitment_sha256": registration.binding_commitment_sha256,
                    "infinity_target_identity_sha256": (
                        registration.infinity_target_identity_sha256
                    ),
                    "space_id": registration.space_id,
                    "space_slug": registration.space_slug,
                    "cleanup_plan_sha256": registration.cleanup_plan_sha256,
                },
                idempotency_key=key,
                accepted_statuses=frozenset({200}),
                deadline=fresh_io_deadline(
                    timeout_seconds=self._config.cleanup_recovery_timeout_seconds,
                    clock=self._config.clock,
                ),
                on_dispatch=mark_dispatched,
            )
            receipt = parse_cleanup_receipt(data, registration=registration)
        except BaseException:
            if dispatched:
                self._mark_cleanup_outcome_unknown()
            else:
                self._restore_phase("cleaning", previous_phase)
            raise
        self._record_cleanup_receipt(receipt, attempt)
        return receipt

    def finalize_cleanup(
        self,
        *,
        cleanup_initiation_receipt_sha256: str,
        idempotency_key: str | None = None,
    ) -> ManagedBenchmarkCleanupCompletionReceipt:
        """Ask canonical authority to prove terminal projection absence."""

        initiation_digest = digest(
            cleanup_initiation_receipt_sha256,
            "managed_benchmark_registry_finalize_invalid",
        )
        registration, projection_manifest_sha256 = self._finalize_context(initiation_digest)
        key = _validated_idempotency_key(
            idempotency_key,
            operation="finalize-cleanup",
            run_id_sha256=registration.run_id_sha256,
            binding_commitment_sha256=registration.binding_commitment_sha256,
            target_identity_sha256=registration.infinity_target_identity_sha256,
        )
        attempt = _FinalizeAttempt(
            registration,
            initiation_digest,
            projection_manifest_sha256,
            key,
        )
        recovering = self._reserve_finalize(attempt)
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, _ = request_registry_json(
                self,
                "POST",
                (f"{REGISTRY_RUNS_PATH}/{registration.run_id_sha256}/cleanup/finalize"),
                payload={
                    "schema_version": FINALIZE_CLEANUP_REQUEST_SCHEMA_VERSION,
                    "receipt_sha256": initiation_digest,
                    "cleanup_plan_sha256": registration.cleanup_plan_sha256,
                },
                idempotency_key=key,
                accepted_statuses=frozenset({200}),
                deadline=fresh_io_deadline(
                    timeout_seconds=self._config.cleanup_recovery_timeout_seconds,
                    clock=self._config.clock,
                ),
                on_dispatch=mark_dispatched,
            )
            receipt = parse_cleanup_completion_receipt(
                data,
                registration=registration,
                cleanup_initiation_receipt_sha256=initiation_digest,
                projection_manifest_sha256=projection_manifest_sha256,
            )
        except BaseException:
            if dispatched:
                self._mark_finalize_outcome_unknown()
            elif recovering:
                self._restore_phase("finalizing", "finalize_outcome_unknown")
            else:
                self._restore_phase("finalizing", "pending")
            raise
        self._record_completion_receipt(receipt)
        self._close_client(suppress_failure=True)
        return receipt

    def finalize_unsealed_abort(
        self,
        *,
        cleanup_initiation_receipt_sha256: str,
        idempotency_key: str | None = None,
    ) -> ManagedBenchmarkAbortCompletionReceipt:
        """Finalize exact manifestless cleanup without any provider probe."""
        return _finalize_unsealed_abort(
            self,
            cleanup_initiation_receipt_sha256=cleanup_initiation_receipt_sha256,
            idempotency_key=idempotency_key,
        )

    def close(self) -> None:
        """Release only terminal clients; recoverable cleanup cannot be abandoned."""

        with self._lock:
            cleanup_required = self._phase in _CLEANUP_REQUIRED_PHASES
            if not cleanup_required and self._phase not in {"complete", "failed", "closed"}:
                self._phase = "closed"
        if cleanup_required:
            fail("managed_benchmark_registry_cleanup_required")
        self._close_client(suppress_failure=False)

    def relinquish_recovery_authority(
        self,
        *,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        infinity_target_identity_sha256: str,
        space_slug: str,
        cleanup_plan_sha256: str,
    ) -> ManagedBenchmarkRecoveryAuthorityTransfer:
        """Close this client after durable transfer of its exact recovery identity."""

        return _relinquish_recovery_authority(
            self,
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=binding_commitment_sha256,
            infinity_target_identity_sha256=infinity_target_identity_sha256,
            space_slug=space_slug,
            cleanup_plan_sha256=cleanup_plan_sha256,
        )

    def __enter__(self) -> ManagedBenchmarkRegistryHttpAdapter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        has_primary_error = bool(exc_info and exc_info[0] is not None)
        if has_primary_error:
            with self._lock:
                cleanup_required = self._phase in _CLEANUP_REQUIRED_PHASES
                if not cleanup_required and self._phase not in {"complete", "failed", "closed"}:
                    self._phase = "closed"
            primary = exc_info[1] if len(exc_info) > 1 else None
            if cleanup_required and isinstance(primary, BaseException):
                primary.add_note("managed_benchmark_registry_cleanup_required")
            else:
                self._close_client(suppress_failure=True)
            return
        self.close()

    def _registration_for(
        self,
        expected_phases: frozenset[str],
    ) -> ManagedBenchmarkRunRegistration:
        with self._lock:
            if (
                self._phase not in expected_phases
                or type(self._registration) is not ManagedBenchmarkRunRegistration
            ):
                fail("managed_benchmark_registry_lifecycle_invalid")
            return self._registration

    def _reserve_seal(self, projection_manifest_sha256: str) -> None:
        with self._lock:
            if self._phase != "registered":
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._seal_attempt_sha256 = projection_manifest_sha256
            self._phase = "sealing"

    def _cleanup_context(
        self,
    ) -> tuple[ManagedBenchmarkRunRegistration, str | None, bool]:
        with self._lock:
            if (
                self._phase not in _CLEANUP_REGISTRATION_PHASES
                or type(self._registration) is not ManagedBenchmarkRunRegistration
            ):
                fail("managed_benchmark_registry_lifecycle_invalid")
            if self._phase == "seal_outcome_unknown":
                if type(self._seal_attempt_sha256) is not str:
                    fail("managed_benchmark_registry_lifecycle_invalid")
                return self._registration, self._seal_attempt_sha256, True
            if self._phase == "cleanup_outcome_unknown":
                if type(self._cleanup_attempt) is not _CleanupAttempt:
                    fail("managed_benchmark_registry_lifecycle_invalid")
                return (
                    self._registration,
                    self._cleanup_attempt.seal_attempt_sha256,
                    self._cleanup_attempt.confirm_seal_from_pending_cleanup,
                )
            return self._registration, self._projection_manifest_sha256, False

    def _reserve_registration(self, attempt: _RegistrationAttempt) -> bool:
        with self._lock:
            recovering = self._phase == "registration_outcome_unknown"
            if self._phase == "ready":
                self._registration_attempt = attempt
            elif not recovering or self._registration_attempt != attempt:
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._phase = "registering"
            return recovering

    def _reserve_cleanup(self, attempt: _CleanupAttempt) -> str:
        with self._lock:
            previous_phase = self._phase
            if previous_phase == "cleanup_outcome_unknown":
                if self._cleanup_attempt != attempt:
                    fail("managed_benchmark_registry_lifecycle_invalid")
            elif previous_phase in _CLEANUP_READY_PHASES:
                self._cleanup_attempt = attempt
            else:
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._phase = "cleaning"
            return previous_phase

    def _finalize_context(
        self,
        cleanup_initiation_receipt_sha256: str,
    ) -> tuple[ManagedBenchmarkRunRegistration, str]:
        with self._lock:
            if (
                self._phase not in {"pending", "finalize_outcome_unknown"}
                or type(self._registration) is not ManagedBenchmarkRunRegistration
                or type(self._cleanup_receipt)
                not in {
                    ManagedBenchmarkCleanupReceipt,
                    ManagedBenchmarkPersistedCleanupReceipt,
                }
                or self._cleanup_receipt.receipt_sha256 != cleanup_initiation_receipt_sha256
                or type(self._projection_manifest_sha256) is not str
            ):
                fail("managed_benchmark_registry_lifecycle_invalid")
            return self._registration, self._projection_manifest_sha256

    def _reserve_finalize(self, attempt: _FinalizeAttempt) -> bool:
        with self._lock:
            recovering = self._phase == "finalize_outcome_unknown"
            if self._phase == "pending":
                self._finalize_attempt = attempt
            elif not recovering or self._finalize_attempt != attempt:
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._phase = "finalizing"
            return recovering

    def _record_projection_seal(self, seal: ManagedBenchmarkProjectionSeal) -> None:
        with self._lock:
            if (
                self._phase != "sealing"
                or self._seal_attempt_sha256 != seal.projection_manifest_sha256
            ):
                self._phase = "failed"
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._projection_manifest_sha256 = seal.projection_manifest_sha256
            self._lifecycle_state = "active"
            self._phase = "sealed"

    def _record_cleanup_receipt(
        self,
        receipt: ManagedBenchmarkCleanupReceipt,
        attempt: _CleanupAttempt,
    ) -> None:
        with self._lock:
            if self._phase != "cleaning" or self._cleanup_attempt != attempt:
                self._phase = "failed"
                fail("managed_benchmark_registry_lifecycle_invalid")
            if (
                self._projection_manifest_sha256 is None
                and attempt.confirm_seal_from_pending_cleanup
                and receipt.projection_cleanup == "pending"
                and type(attempt.seal_attempt_sha256) is str
            ):
                self._projection_manifest_sha256 = attempt.seal_attempt_sha256
            self._cleanup_receipt = receipt
            self._lifecycle_state = "cleanup_pending"
            self._phase = "pending"

    def _record_completion_receipt(
        self,
        receipt: ManagedBenchmarkCleanupCompletionReceipt,
    ) -> None:
        with self._lock:
            if self._phase != "finalizing":
                self._phase = "failed"
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._completion_receipt = receipt
            self._lifecycle_state = "cleanup_complete"
            self._phase = "complete"

    def _restore_phase(self, active_phase: str, previous_phase: str) -> None:
        with self._lock:
            if self._phase == active_phase:
                self._phase = previous_phase
            else:
                self._phase = "failed"

    def _mark_registration_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "registering":
                self._phase = "registration_outcome_unknown"
                self._lifecycle_state = "unknown"
            else:
                self._phase = "failed"

    def _mark_seal_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "sealing":
                self._phase = "seal_outcome_unknown"
                self._lifecycle_state = "unknown"
            else:
                self._phase = "failed"

    def _mark_cleanup_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "cleaning":
                self._phase = "cleanup_outcome_unknown"
                self._lifecycle_state = "unknown"
            else:
                self._phase = "failed"

    def _mark_finalize_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "finalizing":
                self._phase = "finalize_outcome_unknown"
                self._lifecycle_state = "unknown"
            else:
                self._phase = "failed"

    def _mark_recovery_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "recovering":
                self._phase = "recovery_outcome_unknown"
                self._lifecycle_state = "unknown"
            else:
                self._phase = "failed"

    def _terminal_preserving_primary(self) -> None:
        with self._lock:
            self._phase = "failed"
            self._lifecycle_state = "failed"
        self._close_client(suppress_failure=True)

    def _close_client(self, *, suppress_failure: bool) -> None:
        close_registry_transport(self, suppress_failure=suppress_failure)


__all__ = (
    "ManagedBenchmarkAbortCompletionReceipt",
    "ManagedBenchmarkCleanupCompletionReceipt",
    "ManagedBenchmarkCleanupCounts",
    "ManagedBenchmarkCleanupReceipt",
    "ManagedBenchmarkPersistedCleanupReceipt",
    "ManagedBenchmarkPersistedAbortReceipt",
    "ManagedBenchmarkPersistedCompletionReceipt",
    "ManagedBenchmarkProjectionSeal",
    "ManagedBenchmarkRecoveryAuthorityTransfer",
    "ManagedBenchmarkRunLifecycleSnapshot",
    "ManagedBenchmarkRegistryHttpAdapter",
    "ManagedBenchmarkRegistryHttpConfig",
    "ManagedBenchmarkRegistryHttpError",
    "ManagedBenchmarkRunRegistration",
    "managed_benchmark_registry_idempotency_key",
)
