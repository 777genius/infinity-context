"""Canonical registry authority around the exact managed HTTP policy lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkCleanupCompletionReceipt,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkProjectionSeal,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_http_policy_lifecycle import (
    MANAGED_HTTP_POLICY_ADAPTER_ID,
    ManagedComparisonHttpPolicyLifecycleAdapter,
    managed_http_policy_lifecycle_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    binding_snapshot,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    ManagedHttpPolicyRegistryMaterial,
    managed_http_policy_registry_material_sha256,
)
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    ManagedProjectionManifest,
    build_managed_projection_manifest,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
)

MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID = "managed-comparison-registry-policy-lifecycle-v1"


class ManagedRegistryPolicyLifecycleError(RuntimeError):
    """Stable secret-free lifecycle composition failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _CanonicalSourceCall:
    bindings: FullComparisonRunBindings
    cases: tuple[ManagedRunCase, ...]
    managed_attestation: VerifiedManagedCompositionAttestation
    managed_attestation_commitment_sha256: str
    ingest_receipts: tuple[object, ...]
    case_manifest_sha256: str


@final
class ManagedComparisonRegistryPolicyLifecycleAdapter:
    """Decorate exact policy I/O with canonical registry ownership and cleanup proof."""

    __slots__ = (
        "_binding_snapshot",
        "_bindings",
        "_canonical_receipts",
        "_cases",
        "_cleanup_receipt",
        "_completion_receipt",
        "_delegate",
        "_delegate_adapter_implementation",
        "_delete_in_flight",
        "_implementation",
        "_lock",
        "_next_delete",
        "_phase",
        "_projection_manifest",
        "_projection_sealed",
        "_registration",
        "_registration_commitment_sha256",
        "_registry",
        "_registry_material",
        "_registry_material_sha256",
        "_source_call",
        "_terminal_receipt",
        "_terminal_receipts",
    )

    def __init__(
        self,
        *,
        delegate: ManagedComparisonHttpPolicyLifecycleAdapter,
        registry: ManagedBenchmarkRegistryHttpAdapter,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        registration: ManagedBenchmarkRunRegistration,
    ) -> None:
        delegate_implementation = _trusted_delegate_implementation(delegate)
        if type(registry) is not ManagedBenchmarkRegistryHttpAdapter:
            _fail("managed_registry_policy_registry_invalid")
        if type(bindings) is not FullComparisonRunBindings:
            _fail("managed_registry_policy_bindings_invalid")
        if (
            type(cases) is not tuple
            or not cases
            or any(type(item) is not ManagedRunCase for item in cases)
        ):
            _fail("managed_registry_policy_cases_invalid")
        if type(registration) is not ManagedBenchmarkRunRegistration:
            _fail("managed_registry_policy_registration_invalid")
        _validate_registration(bindings, registration)
        self._bindings = bindings
        self._binding_snapshot = binding_snapshot(bindings)
        self._cases = cases
        self._registration = registration
        self._registration_commitment_sha256 = _registration_commitment_sha256(registration)
        self._registry = registry
        self._delegate_adapter_implementation = delegate_implementation
        self._implementation = managed_registry_policy_lifecycle_implementation_sha256(
            delegate_implementation
        )
        self._phase = "open"
        self._source_call: _CanonicalSourceCall | None = None
        self._canonical_receipts: tuple[object, ...] | None = None
        self._projection_manifest: ManagedProjectionManifest | None = None
        self._projection_sealed = False
        self._cleanup_receipt: ManagedBenchmarkCleanupReceipt | None = None
        self._terminal_receipt: object | None = None
        self._terminal_receipts: tuple[object, ...] | None = None
        self._completion_receipt: ManagedBenchmarkCleanupCompletionReceipt | None = None
        self._registry_material: ManagedHttpPolicyRegistryMaterial | None = None
        self._registry_material_sha256: str | None = None
        self._next_delete = 0
        self._delete_in_flight: tuple[str, str, int] | None = None
        self._lock = threading.RLock()
        self._delegate = delegate

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedComparisonRegistryPolicyLifecycleAdapter is final")

    def __repr__(self) -> str:
        return "ManagedComparisonRegistryPolicyLifecycleAdapter(<redacted>)"

    @property
    def adapter_id(self) -> str:
        return MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return self._implementation

    @property
    def terminal_completion_receipt(
        self,
    ) -> ManagedBenchmarkCleanupCompletionReceipt | None:
        """Return the immutable canonical completion proof only after finalization."""

        with self._lock:
            return self._completion_receipt

    def seal_canonical_source(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        ingest_receipts: tuple[object, ...],
        case_manifest_sha256: str,
    ) -> tuple[object, ...]:
        call = _CanonicalSourceCall(
            bindings,
            cases,
            managed_attestation,
            managed_attestation_commitment_sha256,
            ingest_receipts,
            case_manifest_sha256,
        )
        self._reserve_source(call)
        try:
            receipts = self._trusted_delegate().seal_canonical_source(
                bindings=bindings,
                cases=cases,
                managed_attestation=managed_attestation,
                managed_attestation_commitment_sha256=(managed_attestation_commitment_sha256),
                ingest_receipts=ingest_receipts,
                case_manifest_sha256=case_manifest_sha256,
            )
        except BaseException:
            self._set_phase("source-delegating", "source-delegate-failed")
            raise
        try:
            evidence = self._trusted_delegate().exact_projection_evidence
            projection = build_managed_projection_manifest(
                bindings=bindings,
                registration=self._registration,
                cases=cases,
                corpora=evidence.corpora,
                presence=evidence.presence,
            )
        except BaseException:
            self._set_phase("source-delegating", "source-build-failed")
            raise
        with self._lock:
            if self._phase != "source-delegating":
                _fail("managed_registry_policy_state_invalid")
            self._canonical_receipts = receipts
            self._projection_manifest = projection
            self._phase = "source-sealing"
        self._seal_registry_projection()
        with self._lock:
            receipts = self._canonical_receipts
            if self._phase != "source-sealed" or type(receipts) is not tuple:
                _fail("managed_registry_policy_state_invalid")
            return receipts

    def terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        pass_index: int,
    ) -> object:
        """Run one exact delete or freeze after an unrecoverable delegate failure.

        The exact delegate consumes its reserved operation even when provider I/O
        fails. Retrying it would therefore target a different lifecycle position.
        After such a failure every continuation is rejected with
        ``managed_registry_policy_delete_delegate_unrecoverable``.
        """

        self._validate_binding(bindings)
        operation = (backend_role, target_identity_sha256, pass_index)
        first = self._reserve_delete(operation)
        if first and self._cleanup_receipt is None:
            try:
                cleanup = self._registry.begin_cleanup()
                self._validate_cleanup_receipt(cleanup)
            except BaseException:
                with self._lock:
                    self._delete_in_flight = None
                    self._phase = "cleanup-begin-failed"
                raise
            with self._lock:
                if self._phase != "cleanup-beginning" or self._delete_in_flight != operation:
                    _fail("managed_registry_policy_state_invalid")
                self._cleanup_receipt = cleanup
                self._phase = "cleanup-active"
        try:
            receipt = self._trusted_delegate().terminal_delete(
                bindings=bindings,
                backend_role=backend_role,
                target_identity_sha256=target_identity_sha256,
                pass_index=pass_index,
            )
        except BaseException:
            with self._lock:
                if self._delete_in_flight != operation:
                    self._phase = "terminal"
                    _fail("managed_registry_policy_state_invalid")
                self._delete_in_flight = None
                self._phase = "delete-delegate-failed"
            raise
        with self._lock:
            if self._delete_in_flight != operation:
                self._phase = "terminal"
                _fail("managed_registry_policy_state_invalid")
            self._delete_in_flight = None
            self._next_delete += 1
            self._phase = "cleanup-active"
        return receipt

    def seal_terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        receipts: tuple[object, ...],
    ) -> object:
        self._validate_binding(bindings)
        recovery = self._reserve_terminal_seal(
            managed_attestation,
            managed_attestation_commitment_sha256,
            receipts,
        )
        if not recovery:
            try:
                terminal = self._trusted_delegate().seal_terminal_delete(
                    bindings=bindings,
                    managed_attestation=managed_attestation,
                    managed_attestation_commitment_sha256=(managed_attestation_commitment_sha256),
                    receipts=receipts,
                )
            except BaseException:
                self._set_phase("terminal-sealing", "terminal")
                raise
            with self._lock:
                if self._phase != "terminal-sealing":
                    _fail("managed_registry_policy_state_invalid")
                self._terminal_receipt = terminal
                self._phase = "finalizing"
        self._finalize_registry_cleanup()
        with self._lock:
            if self._phase != "cleanup-complete" or self._terminal_receipt is None:
                _fail("managed_registry_policy_state_invalid")
            return self._terminal_receipt

    def aggregate_policy(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        canonical_source: tuple[object, ...],
        terminal_delete: object,
    ) -> object:
        self._validate_binding(bindings)
        with self._lock:
            if (
                self._phase != "cleanup-complete"
                or self._completion_receipt is None
                or self._registry_material is None
                or self._registry_material_sha256 is None
                or terminal_delete is not self._terminal_receipt
                or canonical_source is not self._canonical_receipts
            ):
                _fail("managed_registry_policy_aggregate_phase_invalid")
            material = self._registry_material
            material_sha256 = self._registry_material_sha256
            self._phase = "binding-evidence"
        try:
            if not hmac.compare_digest(
                managed_http_policy_registry_material_sha256(material),
                material_sha256,
            ):
                _fail("managed_registry_policy_evidence_integrity_failed")
            delegate = self._trusted_delegate()
            delegate.bind_registry_completion_evidence(material=material)
            self._set_phase("binding-evidence", "aggregating")
            result = delegate.aggregate_policy(
                bindings=bindings,
                managed_attestation=managed_attestation,
                managed_attestation_commitment_sha256=(managed_attestation_commitment_sha256),
                canonical_source=canonical_source,
                terminal_delete=terminal_delete,
            )
        except BaseException:
            with self._lock:
                self._phase = "terminal"
            raise
        self._set_phase("aggregating", "aggregated")
        return result

    def _reserve_source(self, call: _CanonicalSourceCall) -> None:
        self._validate_binding(call.bindings)
        self._validate_source_call(call)
        with self._lock:
            if self._phase == "open":
                self._source_call = call
                self._phase = "source-delegating"
                return
            _fail("managed_registry_policy_canonical_source_replay")

    def _validate_source_call(self, call: _CanonicalSourceCall) -> None:
        if (
            type(call.cases) is not tuple
            or len(call.cases) != len(self._cases)
            or any(
                actual is not expected
                for actual, expected in zip(call.cases, self._cases, strict=True)
            )
            or type(call.managed_attestation_commitment_sha256) is not str
            or len(call.managed_attestation_commitment_sha256) != 64
            or type(call.ingest_receipts) is not tuple
            or type(call.case_manifest_sha256) is not str
            or len(call.case_manifest_sha256) != 64
        ):
            _fail("managed_registry_policy_canonical_source_invalid")

    def _seal_registry_projection(self) -> None:
        projection = self._projection_manifest
        if type(projection) is not ManagedProjectionManifest:
            _fail("managed_registry_policy_projection_unavailable")
        try:
            sealed = self._registry.seal_projection_manifest(
                projection_manifest=projection.projection_manifest,
                projection_manifest_sha256=projection.projection_manifest_sha256,
            )
            if (
                type(sealed) is not ManagedBenchmarkProjectionSeal
                or sealed.run_id_sha256 != self._registration.run_id_sha256
                or sealed.binding_commitment_sha256 != self._registration.binding_commitment_sha256
                or sealed.infinity_target_identity_sha256
                != self._registration.infinity_target_identity_sha256
                or sealed.projection_manifest_sha256 != projection.projection_manifest_sha256
            ):
                _fail("managed_registry_policy_projection_seal_invalid")
        except BaseException:
            self._set_phase("source-sealing", "source-seal-failed")
            raise
        with self._lock:
            self._projection_sealed = True
        self._set_phase("source-sealing", "source-sealed")

    def _reserve_delete(self, operation: tuple[str, str, int]) -> bool:
        expected = tuple(
            (role, self._target(role), attempt)
            for attempt in (1, 2)
            for role in ("infinity-context", "mem0")
        )
        with self._lock:
            if self._delete_in_flight is not None:
                _fail("managed_registry_policy_delete_in_progress")
            if self._phase == "delete-delegate-failed":
                _fail("managed_registry_policy_delete_delegate_unrecoverable")
            if self._next_delete >= len(expected):
                _fail("managed_registry_policy_delete_replay")
            if operation != expected[self._next_delete]:
                _fail("managed_registry_policy_delete_order_invalid")
            first = self._next_delete == 0
            allowed = (
                {
                    "source-sealed",
                    "source-seal-failed",
                    "source-build-failed",
                    "source-delegate-failed",
                    "cleanup-begin-failed",
                }
                if first
                else {"cleanup-active"}
            )
            if self._phase not in allowed:
                _fail("managed_registry_policy_delete_phase_invalid")
            self._delete_in_flight = operation
            if first:
                self._phase = "cleanup-beginning"
            return first

    def _validate_cleanup_receipt(self, receipt: object) -> None:
        if (
            type(receipt) is not ManagedBenchmarkCleanupReceipt
            or receipt.run_id_sha256 != self._registration.run_id_sha256
            or receipt.space_id != self._registration.space_id
            or receipt.space_slug != self._registration.space_slug
            or receipt.projection_cleanup not in {"pending", "blocked"}
            or (self._projection_sealed and receipt.projection_cleanup != "pending")
        ):
            _fail("managed_registry_policy_cleanup_receipt_invalid")

    def _reserve_terminal_seal(
        self,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        receipts: tuple[object, ...],
    ) -> bool:
        with self._lock:
            if self._phase == "finalize-failed":
                source = self._source_call
                if (
                    type(source) is not _CanonicalSourceCall
                    or managed_attestation is not source.managed_attestation
                    or managed_attestation_commitment_sha256
                    != source.managed_attestation_commitment_sha256
                    or type(receipts) is not tuple
                    or receipts is not self._terminal_receipts
                ):
                    _fail("managed_registry_policy_terminal_delete_replay")
                self._phase = "finalizing"
                return True
            if (
                self._phase != "cleanup-active"
                or self._next_delete != 4
                or self._delete_in_flight is not None
                or type(self._cleanup_receipt) is not ManagedBenchmarkCleanupReceipt
                or type(receipts) is not tuple
                or len(receipts) != 4
            ):
                _fail("managed_registry_policy_terminal_delete_phase_invalid")
            source = self._source_call
            if (
                type(source) is not _CanonicalSourceCall
                or managed_attestation is not source.managed_attestation
                or managed_attestation_commitment_sha256
                != source.managed_attestation_commitment_sha256
            ):
                _fail("managed_registry_policy_terminal_binding_invalid")
            self._terminal_receipts = receipts
            self._phase = "terminal-sealing"
            return False

    def _finalize_registry_cleanup(self) -> None:
        cleanup = self._cleanup_receipt
        if type(cleanup) is not ManagedBenchmarkCleanupReceipt:
            _fail("managed_registry_policy_cleanup_receipt_unavailable")
        try:
            completion = self._registry.finalize_cleanup(
                cleanup_initiation_receipt_sha256=cleanup.receipt_sha256,
            )
            self._validate_completion_receipt(completion, cleanup)
            material = self._registry_material_for(completion, cleanup)
            material_sha256 = managed_http_policy_registry_material_sha256(material)
        except BaseException:
            self._set_phase("finalizing", "finalize-failed")
            raise
        with self._lock:
            if self._phase != "finalizing":
                _fail("managed_registry_policy_state_invalid")
            self._completion_receipt = completion
            self._registry_material = material
            self._registry_material_sha256 = material_sha256
            self._phase = "cleanup-complete"

    def _registry_material_for(
        self,
        completion: ManagedBenchmarkCleanupCompletionReceipt,
        cleanup: ManagedBenchmarkCleanupReceipt,
    ) -> ManagedHttpPolicyRegistryMaterial:
        projection = self._projection_manifest
        if type(projection) is not ManagedProjectionManifest:
            _fail("managed_registry_policy_projection_unavailable")
        return ManagedHttpPolicyRegistryMaterial(
            registration_commitment_sha256=(self._registration_commitment_sha256),
            projection_manifest_sha256=projection.projection_manifest_sha256,
            cleanup_initiation_receipt_sha256=cleanup.receipt_sha256,
            completion_receipt_sha256=completion.receipt_sha256,
            projection_absence_proof_sha256=(completion.projection_absence_proof_sha256),
            wrapper_adapter_id=self.adapter_id,
            wrapper_implementation_sha256=self.implementation_sha256,
        )

    def _validate_completion_receipt(
        self,
        receipt: object,
        cleanup: ManagedBenchmarkCleanupReceipt,
    ) -> None:
        projection = self._projection_manifest
        if (
            type(receipt) is not ManagedBenchmarkCleanupCompletionReceipt
            or type(projection) is not ManagedProjectionManifest
            or receipt.run_id_sha256 != self._registration.run_id_sha256
            or receipt.space_id != self._registration.space_id
            or receipt.space_slug != self._registration.space_slug
            or receipt.state != "cleanup_complete"
            or receipt.disposition != "cleanup_complete"
            or receipt.projection_cleanup != "complete"
            or receipt.cleanup_initiation_receipt_sha256 != cleanup.receipt_sha256
            or receipt.projection_manifest_sha256 != projection.projection_manifest_sha256
        ):
            _fail("managed_registry_policy_completion_receipt_invalid")

    def _validate_binding(self, bindings: FullComparisonRunBindings) -> None:
        if bindings is not self._bindings or binding_snapshot(bindings) != self._binding_snapshot:
            _fail("managed_registry_policy_binding_changed")

    def _trusted_delegate(self) -> ManagedComparisonHttpPolicyLifecycleAdapter:
        current = _trusted_delegate_implementation(self._delegate)
        if not hmac.compare_digest(current, self._delegate_adapter_implementation):
            _fail("managed_registry_policy_delegate_changed")
        return self._delegate

    def _target(self, role: str) -> str:
        matches = tuple(
            item.target_identity_sha256
            for item in self._bindings.backend_targets
            if item.backend_role == role
        )
        if len(matches) != 1:
            _fail("managed_registry_policy_target_binding_invalid")
        return matches[0]

    def _set_phase(self, expected: str, value: str) -> None:
        with self._lock:
            if self._phase != expected:
                self._phase = "terminal"
                _fail("managed_registry_policy_state_invalid")
            self._phase = value


def managed_registry_policy_lifecycle_implementation_sha256(
    delegate_implementation_sha256: str | None = None,
) -> str:
    delegate = (
        managed_http_policy_lifecycle_implementation_sha256()
        if delegate_implementation_sha256 is None
        else delegate_implementation_sha256
    )
    material = {
        "adapter_id": MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID,
        "delegate": delegate,
        "projection_seal": "after-exact-canonical-source-before-retrieval",
        "canonical_cleanup": "before-first-infinity-delete",
        "completion": "after-terminal-delete-seal-before-aggregate",
        "validation_evidence": "exact-registry-completion-bound-before-delegate-aggregate",
        "delegate_delete_failure": "fail-closed-after-exact-delegate-consumption",
        "recovery": "exact-call-registry-default-idempotency",
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _trusted_delegate_implementation(delegate: object) -> str:
    if type(delegate) is not ManagedComparisonHttpPolicyLifecycleAdapter:
        _fail("managed_registry_policy_delegate_invalid")
    implementation = managed_http_policy_lifecycle_implementation_sha256()
    if delegate.adapter_id != MANAGED_HTTP_POLICY_ADAPTER_ID or not hmac.compare_digest(
        delegate.implementation_sha256, implementation
    ):
        _fail("managed_registry_policy_delegate_changed")
    return implementation


def _validate_registration(
    bindings: FullComparisonRunBindings,
    registration: ManagedBenchmarkRunRegistration,
) -> None:
    infinity_targets = tuple(
        item.target_identity_sha256
        for item in bindings.backend_targets
        if item.backend_role == "infinity-context"
    )
    if (
        registration.run_id_sha256 != hashlib.sha256(bindings.run_id.encode()).hexdigest()
        or registration.binding_commitment_sha256 != bindings.binding_commitment_sha256
        or len(infinity_targets) != 1
        or registration.infinity_target_identity_sha256 != infinity_targets[0]
        or registration.state != "active"
    ):
        _fail("managed_registry_policy_registration_mismatch")


def _registration_commitment_sha256(
    registration: ManagedBenchmarkRunRegistration,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "schema_version": registration.schema_version,
                "authority": registration.authority,
                "run_id_sha256": registration.run_id_sha256,
                "binding_commitment_sha256": (registration.binding_commitment_sha256),
                "infinity_target_identity_sha256": (registration.infinity_target_identity_sha256),
                "space_id": registration.space_id,
                "space_slug": registration.space_slug,
                "state": registration.state,
                "created": registration.created,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _fail(code: str) -> None:
    raise ManagedRegistryPolicyLifecycleError(code)


__all__ = (
    "MANAGED_REGISTRY_POLICY_LIFECYCLE_ADAPTER_ID",
    "ManagedComparisonRegistryPolicyLifecycleAdapter",
    "ManagedRegistryPolicyLifecycleError",
    "managed_registry_policy_lifecycle_implementation_sha256",
)
