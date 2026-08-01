"""Stateful HTTP transport adapter for the canonical benchmark run registry."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import final

import httpx
from infinity_context_core.application.use_cases.benchmark_runs import (
    validate_projection_manifest,
)

from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    REGISTRY_RUNS_PATH,
    ManagedBenchmarkCleanupCounts,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkProjectionSeal,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRegistryHttpError,
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
from infinity_context_server.memory_comparison_managed_benchmark_registry_wire import (
    fresh_io_deadline,
    parse_cleanup_receipt,
    parse_projection_seal,
    parse_registration,
    read_json_envelope,
    remaining_io_timeout,
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
    }
)


@dataclass(frozen=True, slots=True)
class _RegistrationAttempt:
    run_id_sha256: str
    binding_commitment_sha256: str
    space_slug: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class _CleanupAttempt:
    registration: ManagedBenchmarkRunRegistration
    idempotency_key: str


@final
class ManagedBenchmarkRegistryHttpAdapter:
    """Own one client and its exact register, optional seal, and cleanup sequence.

    A successful registration grants cleanup authority immediately. If the seal PUT
    fails or an HTTP outcome cannot be verified, exact same-key recovery remains
    available through fresh bounded cleanup/recovery attempts. Nonterminal close is
    refused with a fixed cleanup-required code, leaving the client open for recovery.
    """

    __slots__ = (
        "_client",
        "_close_attempted",
        "_close_warning_code",
        "_cleanup_attempt",
        "_config",
        "_lock",
        "_phase",
        "_registration",
        "_registration_attempt",
    )

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

    def register(
        self,
        *,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        space_slug: str,
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
        key = _validated_idempotency_key(
            idempotency_key,
            operation="register",
            run_id_sha256=run_id,
            binding_commitment_sha256=binding,
            target_identity_sha256=self._config.target_identity_sha256,
        )
        attempt = _RegistrationAttempt(run_id, binding, slug, key)
        recovering = self._reserve_registration(attempt)
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, status = self._request(
                "POST",
                REGISTRY_RUNS_PATH,
                payload={
                    "schema_version": "memory-comparison-run-registration.v1",
                    "run_id_sha256": run_id,
                    "binding_commitment_sha256": binding,
                    "infinity_target_identity_sha256": self._config.target_identity_sha256,
                    "space_slug": slug,
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
            self._phase = "registered"
        return registration

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
            )
        except Exception:
            fail("managed_benchmark_registry_manifest_invalid")
        self._reserve_exact("registered", "sealing")
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, _ = self._request(
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
        self._advance("sealing", "sealed")
        return sealed

    def begin_cleanup(
        self,
        *,
        idempotency_key: str | None = None,
    ) -> ManagedBenchmarkCleanupReceipt:
        """Start cleanup after registration, regardless of seal outcome."""

        registration = self._registration_for(_CLEANUP_REGISTRATION_PHASES)
        key = _validated_idempotency_key(
            idempotency_key,
            operation="begin-cleanup",
            run_id_sha256=registration.run_id_sha256,
            binding_commitment_sha256=registration.binding_commitment_sha256,
            target_identity_sha256=registration.infinity_target_identity_sha256,
        )
        attempt = _CleanupAttempt(registration, key)
        previous_phase = self._reserve_cleanup(attempt)
        dispatched = False

        def mark_dispatched() -> None:
            nonlocal dispatched
            dispatched = True

        try:
            data, _ = self._request(
                "DELETE",
                f"{REGISTRY_RUNS_PATH}/{registration.run_id_sha256}",
                payload={
                    "schema_version": "memory-comparison-run-cleanup.v1",
                    "binding_commitment_sha256": registration.binding_commitment_sha256,
                    "infinity_target_identity_sha256": (
                        registration.infinity_target_identity_sha256
                    ),
                    "space_id": registration.space_id,
                    "space_slug": registration.space_slug,
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
        self._advance("cleaning", "complete")
        self._close_client(suppress_failure=True)
        return receipt

    def close(self) -> None:
        """Release only terminal clients; recoverable cleanup cannot be abandoned."""

        with self._lock:
            cleanup_required = self._phase in _CLEANUP_REQUIRED_PHASES
            if not cleanup_required and self._phase not in {"complete", "failed", "closed"}:
                self._phase = "closed"
        if cleanup_required:
            fail("managed_benchmark_registry_cleanup_required")
        self._close_client(suppress_failure=False)

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

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object],
        idempotency_key: str | None,
        accepted_statuses: frozenset[int],
        deadline: datetime,
        on_dispatch: Callable[[], None],
    ) -> tuple[dict[str, object], int]:
        timeout = remaining_io_timeout(
            deadline=deadline,
            timeout_seconds=float(self._config.timeout_seconds),
            clock=self._config.clock,
        )
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        url = f"{self._config.base_url.rstrip('/')}/{path}"
        try:
            on_dispatch()
            with self._client.stream(
                method,
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.status_code not in accepted_statuses:
                    fail("managed_benchmark_registry_response_rejected")
                data = read_json_envelope(
                    response,
                    deadline=deadline,
                    clock=self._config.clock,
                )
                status = response.status_code
        except ManagedBenchmarkRegistryHttpError:
            raise
        except KeyboardInterrupt:
            raise KeyboardInterrupt() from None
        except SystemExit as error:
            safe_code = error.code if type(error.code) is int or error.code is None else 1
            raise SystemExit(safe_code) from None
        except BaseException:
            fail("managed_benchmark_registry_request_failed")
        return data, status

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

    def _reserve_exact(self, expected_phase: str, active_phase: str) -> None:
        self._reserve_any(frozenset({expected_phase}), active_phase)

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

    def _reserve_any(self, expected_phases: frozenset[str], active_phase: str) -> None:
        with self._lock:
            if self._phase not in expected_phases:
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._phase = active_phase

    def _advance(self, active_phase: str, next_phase: str) -> None:
        with self._lock:
            if self._phase != active_phase:
                self._phase = "failed"
                fail("managed_benchmark_registry_lifecycle_invalid")
            self._phase = next_phase

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
            else:
                self._phase = "failed"

    def _mark_seal_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "sealing":
                self._phase = "seal_outcome_unknown"
            else:
                self._phase = "failed"

    def _mark_cleanup_outcome_unknown(self) -> None:
        with self._lock:
            if self._phase == "cleaning":
                self._phase = "cleanup_outcome_unknown"
            else:
                self._phase = "failed"

    def _terminal_preserving_primary(self) -> None:
        with self._lock:
            self._phase = "failed"
        self._close_client(suppress_failure=True)

    def _close_client(self, *, suppress_failure: bool) -> None:
        with self._lock:
            if self._close_attempted:
                return
            self._close_attempted = True
        try:
            self._client.close()
        except BaseException as error:
            with self._lock:
                self._close_warning_code = "managed_benchmark_registry_close_failed"
            if suppress_failure:
                return
            if isinstance(error, KeyboardInterrupt):
                raise KeyboardInterrupt() from None
            if isinstance(error, SystemExit):
                safe_code = error.code if type(error.code) is int or error.code is None else 1
                raise SystemExit(safe_code) from None
            fail("managed_benchmark_registry_close_failed")


__all__ = (
    "ManagedBenchmarkCleanupCounts",
    "ManagedBenchmarkCleanupReceipt",
    "ManagedBenchmarkProjectionSeal",
    "ManagedBenchmarkRegistryHttpAdapter",
    "ManagedBenchmarkRegistryHttpConfig",
    "ManagedBenchmarkRegistryHttpError",
    "ManagedBenchmarkRunRegistration",
    "managed_benchmark_registry_idempotency_key",
)
