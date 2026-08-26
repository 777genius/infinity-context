"""Fail-closed exact HTTP policy lifecycle for managed comparisons."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import final

import httpx

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
)
from infinity_context_server.memory_comparison_managed_http_derived_evidence import (
    ManagedDerivedEvidenceHttpClient,
)
from infinity_context_server.memory_comparison_managed_http_exact_cleanup import (
    ManagedInfinityExactCleanupCoordinator,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedInfinityHttpConfig,
)
from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    ManagedHttpPolicyExactCorpusBindings,
    binding_snapshot,
    project_cleanup_passes,
    project_corpus_material,
    project_exact_corpus_bindings,
    project_mem0_cleanup_commitments,
    project_validation_material,
)
from infinity_context_server.memory_comparison_managed_http_policy_receipts import (
    ManagedHttpPolicyCanonicalReceiptState,
    ManagedHttpPolicyCanonicalSourceReceipt,
    ManagedHttpPolicyDeleteReceipt,
    ManagedHttpPolicyDeleteReceiptState,
    ManagedHttpPolicyTerminalDeleteReceipt,
    ManagedHttpPolicyTerminalReceiptState,
    canonical_receipt_state,
    delete_receipt_state,
    issue_canonical_receipt,
    issue_delete_receipt,
    issue_terminal_receipt,
    receipt_registry_transaction,
    terminal_receipt_state,
)
from infinity_context_server.memory_comparison_managed_http_policy_registry_evidence import (
    ManagedHttpPolicyExactProjectionEvidence,
    ManagedHttpPolicyObservedCorpusEvidence,
    ManagedHttpPolicyRegistryEvidenceBinding,
)
from infinity_context_server.memory_comparison_managed_http_policy_support import (
    ManagedHttpPolicyLifecycleError,
    _attestation,
    _aware,
    _digest,
    _receipt,
)
from infinity_context_server.memory_comparison_managed_http_policy_validation import (
    ManagedHttpPolicyCorpusMaterial,
    ManagedHttpPolicyRegistryMaterial,
    VerifiedManagedHttpPolicyValidation,
    seal_managed_http_policy_validation,
)
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpRuntimeConfig,
)
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    ManagedInfinityHttpLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_ports import (
    ManagedV5CutoverIngestPort,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_cleanup import (
    project_managed_v5_infinity_cleanup,
)
from infinity_context_server.memory_comparison_managed_v5_ingest_identity_projector import (
    project_managed_infinity_v5_ingest_identities,
)
from infinity_context_server.memory_comparison_managed_v5_mem0_terminal_observation import (
    ManagedMem0TerminalObservation,
    run_mem0_cleanup_pass,
)
from infinity_context_server.memory_comparison_managed_v5_policy_identity import (
    managed_http_policy_production_blockers,
    managed_v5_policy_lifecycle_implementation_sha256,
    managed_v5_retryable_delete_failure,
    managed_v5_target_identity,
)

MANAGED_V5_POLICY_ADAPTER_ID = "managed-infinity-v5-policy-fail-closed-v1"
_retryable_delete_failure = managed_v5_retryable_delete_failure


@final
class ManagedInfinityV5PolicyLifecycleAdapter:
    """Own transport, evidence sequencing, and one-shot aggregate issuance."""

    def __init__(
        self,
        *,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
        composition_binding: ManagedRunnerCompositionBinding,
        infinity_lifecycle: ManagedInfinityHttpLifecycleAdapter,
        mem0_lifecycle: ManagedMem0V5ProductionLifecycleAdapter,
        ingest_port: ManagedV5CutoverIngestPort,
        infinity_config: ManagedInfinityHttpRuntimeConfig,
        deadline: datetime,
        infinity_derived_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        infinity_cleanup_transport_factory: Callable[[], httpx.BaseTransport] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(bindings) is not FullComparisonRunBindings:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_bindings_invalid")
        if (
            type(cases) is not tuple
            or not cases
            or any(type(case) is not ManagedRunCase for case in cases)
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_cases_invalid")
        transport_factories = {
            "infinity-derived": infinity_derived_transport_factory,
            "infinity-cleanup": infinity_cleanup_transport_factory,
        }
        if any(
            factory is not None and not callable(factory)
            for factory in transport_factories.values()
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_factory_invalid")
        if not callable(clock):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_clock_invalid")
        checked_deadline = _aware(deadline, "managed_http_policy_deadline_invalid")
        if _aware(clock(), "managed_http_policy_clock_invalid") >= checked_deadline:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_deadline_expired")
        if (
            type(composition_binding) is not ManagedRunnerCompositionBinding
            or type(infinity_lifecycle) is not ManagedInfinityHttpLifecycleAdapter
            or infinity_lifecycle.composition_binding is not composition_binding
            or type(mem0_lifecycle) is not ManagedMem0V5ProductionLifecycleAdapter
            or mem0_lifecycle.composition_binding is not composition_binding
            or type(ingest_port) is not ManagedV5CutoverIngestPort
            or ingest_port.composition_binding is not composition_binding
            or type(infinity_config) is not ManagedInfinityHttpRuntimeConfig
            or infinity_config.transport is not None
            or bindings.run_id != composition_binding.run_id
        ):
            raise ManagedHttpPolicyLifecycleError("managed_v5_policy_composition_invalid")
        targets = {
            item.backend_role: item.target_identity_sha256 for item in bindings.backend_targets
        }
        if (
            targets
            != {
                item.backend_role: item.target_identity_sha256
                for item in composition_binding.backend_targets
            }
            or targets.get("infinity-context") != infinity_config.target_identity_sha256
            or "mem0" not in targets
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_target_binding_invalid")
        infinity = ManagedInfinityHttpConfig(
            target_identity_sha256=infinity_config.target_identity_sha256,
            base_url=infinity_config.base_url,
            auth_token=infinity_config.auth_token,
            timeout_seconds=infinity_config.timeout_seconds,
        )
        self._bindings = bindings
        self._binding_snapshot = binding_snapshot(bindings)
        self._cases = cases
        self._composition_binding = composition_binding
        self._infinity_lifecycle = infinity_lifecycle
        self._mem0_lifecycle = mem0_lifecycle
        self._ingest_port = ingest_port
        self._deadline = checked_deadline
        self._infinity = infinity
        self._mem0_target = targets["mem0"]
        self._transport_factories = transport_factories
        self._owned_transports: list[httpx.BaseTransport] = []
        self._clock = clock
        self._derived_evidence = ManagedDerivedEvidenceHttpClient(
            config=infinity,
            transport_factory=lambda: self._new_transport("infinity-derived"),
        )
        self._exact_cleanup = ManagedInfinityExactCleanupCoordinator(
            config=infinity,
            derived_evidence=self._derived_evidence,
            transport_factory=lambda: self._new_transport("infinity-cleanup"),
        )
        self._corpora: tuple[ManagedHttpPolicyObservedCorpusEvidence, ...] = ()
        self._corpus_material: tuple[ManagedHttpPolicyCorpusMaterial, ...] = ()
        self._execution_case_manifest_sha256: str | None = None
        self._managed_attestation: VerifiedManagedCompositionAttestation | None = None
        self._managed_attestation_commitment_sha256: str | None = None
        self._registry_evidence = ManagedHttpPolicyRegistryEvidenceBinding()
        self._registry_delegate_capability_issued = False
        self._phase = "open"
        self._closed = False
        self._next_delete = 0
        self._delete_in_flight: tuple[str, str, int] | None = None
        self._mem0_terminal_observation: ManagedMem0TerminalObservation | None = None
        self._lock = threading.RLock()

    @property
    def adapter_id(self) -> str:
        return MANAGED_V5_POLICY_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return managed_v5_policy_lifecycle_implementation_sha256()

    @property
    def exact_projection_evidence(self) -> ManagedHttpPolicyExactProjectionEvidence:
        """Expose the sealed, immutable manifest inputs without transport internals."""

        with self._lock:
            phase, evidence = self._phase, self._corpora
        return self._registry_evidence.exact_projection_evidence(
            phase=phase,
            evidence=evidence,
        )

    @property
    def mem0_terminal_observation(self) -> ManagedMem0TerminalObservation:
        """Return only the authenticated pass-two cleanup readback evidence."""

        with self._lock:
            value = self._mem0_terminal_observation
        if type(value) is not ManagedMem0TerminalObservation:
            raise ManagedHttpPolicyLifecycleError(
                "managed_v5_policy_mem0_terminal_observation_unavailable"
            )
        return value

    def issue_registry_delegate_capability(self) -> object:
        """Issue the sole exact registry authority for this open composition."""

        with self._lock:
            if self._phase != "open" or self._registry_delegate_capability_issued:
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_registry_delegate_capability_invalid"
                )
            self._registry_delegate_capability_issued = True
        try:
            from infinity_context_server import (
                memory_comparison_managed_policy_delegate_capability as delegate_capability,
            )

            return delegate_capability._issue_managed_v5_policy_delegate_capability(
                delegate=self,
                bindings=self._bindings,
                cases=self._cases,
            )
        except BaseException:
            with self._lock:
                self._phase = "terminal"
            raise

    def _registry_delegate_composition_for_capability(
        self,
    ) -> tuple[
        FullComparisonRunBindings,
        tuple[object, ...],
        tuple[ManagedRunCase, ...],
        str,
    ]:
        """Return the exact reserved composition to the capability issuer only."""

        with self._lock:
            return (
                self._bindings,
                self._binding_snapshot,
                self._cases,
                self._phase,
            )

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
        self._validate_call(bindings, cases)
        self._bind_attestation(
            managed_attestation,
            managed_attestation_commitment_sha256,
            allow_initial=True,
        )
        execution_manifest = _digest(
            case_manifest_sha256,
            "managed_http_policy_execution_manifest_invalid",
        )
        with self._lock:
            if self._phase != "open":
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_canonical_source_replay")
            self._phase = "consuming-ingest-evidence"
        cleanup_ready = False
        try:
            corpora = tuple(
                case
                for index, case in enumerate(cases)
                if case.corpus_id not in {prior.corpus_id for prior in cases[:index]}
            )
            if type(ingest_receipts) is not tuple or len(ingest_receipts) != 2 * len(corpora):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_v5_policy_ingest_receipt_coverage_invalid"
                )
            infinity_receipts = ingest_receipts[: len(corpora)]
            pending_receipts = ingest_receipts[len(corpora) :]
            infinity_evidence = self._infinity_lifecycle.consume_exact_ingest_receipts(
                receipts=infinity_receipts,
                cases=corpora,
            )
            mem0_receipts = self._ingest_port.consume_exact_mem0_receipts(pending_receipts)
            mem0_projection = self._mem0_lifecycle.consume_exact_receipts_for_projection(
                mem0_receipts
            )
            bundles = project_managed_infinity_v5_ingest_identities(
                composition_binding=self._composition_binding,
                cases=cases,
                infinity_evidence=infinity_evidence,
                mem0_projection=mem0_projection,
            )
            evidence = self._registry_evidence.observe_corpora(
                bundles=bundles,
                infinity_target_identity_sha256=self._infinity.target_identity_sha256,
                mem0_target_identity_sha256=self._mem0_target,
                observe_presence=self._derived_evidence.observe_presence,
            )
            self._bind_cleanup_evidence(evidence, execution_manifest)
            cleanup_ready = True
            unordered_material = {
                item.bundle.corpus_id: project_corpus_material(item.bundle, item.presence)
                for item in evidence
            }
            corpus_material = tuple(
                unordered_material[case.corpus_id]
                for index, case in enumerate(cases)
                if case.corpus_id not in {prior.corpus_id for prior in cases[:index]}
            )
            material_by_corpus = {item.corpus_id: item for item in corpus_material}
        except ManagedHttpPolicyLifecycleError:
            with self._lock:
                self._phase = "cleanup-only" if cleanup_ready else "terminal"
            raise
        except BaseException:
            with self._lock:
                self._phase = "cleanup-only" if cleanup_ready else "terminal"
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_ingest_evidence_consumption_failed"
            ) from None
        receipts: list[object] = []
        with self._lock:
            for ordinal, case in enumerate(cases):
                receipt = self._issue_canonical_receipt(
                    ManagedHttpPolicyCanonicalReceiptState(
                        owner=self,
                        ordinal=ordinal,
                        case_id=case.case_id,
                        corpus_id=case.corpus_id,
                        run_id=bindings.run_id,
                        binding_commitment_sha256=bindings.binding_commitment_sha256,
                        managed_attestation_commitment_sha256=(
                            managed_attestation_commitment_sha256
                        ),
                        execution_case_manifest_sha256=execution_manifest,
                        corpus=material_by_corpus[case.corpus_id],
                        phase="live",
                    )
                )
                receipts.append(receipt)
            self._corpus_material = corpus_material
            self._phase = "canonical-source-sealed"
        return tuple(receipts)

    def terminal_delete(
        self,
        *,
        bindings: FullComparisonRunBindings,
        backend_role: str,
        target_identity_sha256: str,
        pass_index: int,
    ) -> object:
        self._validate_binding(bindings)
        expected = tuple(
            (role, self._target(role), attempt)
            for attempt in (1, 2)
            for role in ("infinity-context", "mem0")
        )
        with self._lock:
            if self._delete_in_flight is not None:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_in_progress")
            if self._phase not in {
                "canonical-source-sealed",
                "cleanup-only",
                "terminal-cleanup",
            }:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_phase_invalid")
            if self._next_delete >= len(expected):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_replay")
            operation = (backend_role, target_identity_sha256, pass_index)
            if operation != expected[self._next_delete]:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_order_invalid")
            self._delete_in_flight = operation

        receipt = None
        failure: ManagedHttpPolicyLifecycleError | None = None
        for attempt in range(2):
            try:
                if backend_role == "infinity-context":
                    state = self._delete_infinity(target_identity_sha256, pass_index)
                else:
                    state = self._delete_mem0_v5(target_identity_sha256, pass_index)
                receipt = self._issue_delete_receipt(state)
                failure = None
                break
            except ManagedHttpPolicyLifecycleError as exc:
                current = exc
            except BaseException:
                current = ManagedHttpPolicyLifecycleError(
                    f"managed_http_policy_{backend_role.replace('-', '_')}_delete_failed"
                )
            if failure is None:
                failure = current
            if attempt != 0 or not managed_v5_retryable_delete_failure(current):
                break
            try:
                self._ensure_deadline()
            except ManagedHttpPolicyLifecycleError:
                break

        with self._lock:
            if self._delete_in_flight != operation:
                self._delete_in_flight = None
                self._phase = "terminal"
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_state_invalid")
            self._delete_in_flight = None
            if failure is None:
                self._next_delete += 1
                self._phase = "terminal-cleanup"
            else:
                self._phase = "cleanup-only"
        if failure is not None:
            raise failure from None
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
        self._bind_attestation(
            managed_attestation,
            managed_attestation_commitment_sha256,
            allow_initial=False,
        )
        if type(receipts) is not tuple or len(receipts) != 4:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_coverage_invalid")
        expected = (
            ("infinity-context", 1),
            ("mem0", 1),
            ("infinity-context", 2),
            ("mem0", 2),
        )
        with self._lock:
            if self._phase != "terminal-cleanup" or self._next_delete != 4:
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_terminal_delete_phase_invalid"
                )
        with receipt_registry_transaction():
            states = tuple(_receipt(delete_receipt_state, receipt) for receipt in receipts)
            if any(state.owner is not self for state in states):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_owner_invalid")
            if tuple((state.backend_role, state.pass_index) for state in states) != expected:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_coverage_invalid")
            if any(state.phase != "live" for state in states):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_delete_receipt_replay")
            exact = self._exact_corpus_bindings()
            if any(
                state.target_identity_sha256 != self._target(state.backend_role)
                or state.run_id != self._bindings.run_id
                or state.binding_commitment_sha256 != self._bindings.binding_commitment_sha256
                or state.source_scope_count != len(self._corpora)
                or state.corpus_manifest_sha256 != exact.manifest_sha256
                or state.mem0_created_memory_ids != exact.mem0_created_memory_ids
                or state.source_pairs != exact.source_pairs
                for state in states
            ):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_terminal_manifest_binding_invalid"
                )
            infinity_states = tuple(
                state for state in states if state.backend_role == "infinity-context"
            )
            mem0_states = tuple(state for state in states if state.backend_role == "mem0")
            if not all(
                state.canonical_absent and state.backend_verified_absent
                for state in infinity_states
            ):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_infinity_exact_absence_failed"
                )
            if not all(state.backend_verified_absent for state in mem0_states):
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_mem0_absence_failed")
            cleanup_passes = project_cleanup_passes(
                tuple(
                    (
                        state.backend_role,
                        state.target_identity_sha256,
                        state.pass_index,
                        state.cleanup_commitment_sha256,
                        state.exact_absence_commitment_sha256,
                        state.corpus_absence_commitments,
                        state.backend_verified_absent
                        and (state.backend_role != "infinity-context" or state.canonical_absent),
                    )
                    for state in states
                )
            )
            for state in states:
                state.phase = "consumed"
            receipt = issue_terminal_receipt(
                ManagedHttpPolicyTerminalReceiptState(
                    owner=self,
                    run_id=self._bindings.run_id,
                    binding_commitment_sha256=self._bindings.binding_commitment_sha256,
                    managed_attestation_commitment_sha256=(managed_attestation_commitment_sha256),
                    execution_case_manifest_sha256=self._execution_manifest(),
                    cleanup_passes=cleanup_passes,
                    phase="live",
                )
            )
        with self._lock:
            self._phase = "terminal-delete-sealed"
        return receipt

    def bind_registry_completion_evidence(
        self,
        *,
        material: ManagedHttpPolicyRegistryMaterial,
    ) -> None:
        """Bind one exact wrapper completion proof before aggregate issuance."""

        with self._lock:
            self._registry_evidence.bind_completion(
                material=material,
                phase=self._phase,
            )

    def aggregate_policy(
        self,
        *,
        bindings: FullComparisonRunBindings,
        managed_attestation: VerifiedManagedCompositionAttestation,
        managed_attestation_commitment_sha256: str,
        canonical_source: tuple[object, ...],
        terminal_delete: object,
    ) -> VerifiedManagedHttpPolicyValidation:
        self._validate_binding(bindings)
        self._bind_attestation(
            managed_attestation,
            managed_attestation_commitment_sha256,
            allow_initial=False,
        )
        if type(canonical_source) is not tuple or len(canonical_source) != len(self._cases):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_canonical_coverage_invalid")
        with self._lock:
            if self._phase != "terminal-delete-sealed":
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_aggregate_replay")
            registry_evidence = self._registry_evidence
            self._phase = "aggregating"
        try:
            with receipt_registry_transaction():
                canonical = tuple(
                    _receipt(canonical_receipt_state, item) for item in canonical_source
                )
                terminal = _receipt(terminal_receipt_state, terminal_delete)
                expected = tuple(
                    (ordinal, case.case_id, case.corpus_id)
                    for ordinal, case in enumerate(self._cases)
                )
                if (
                    tuple((item.ordinal, item.case_id, item.corpus_id) for item in canonical)
                    != expected
                ):
                    raise ManagedHttpPolicyLifecycleError(
                        "managed_http_policy_canonical_order_invalid"
                    )
                manifest = self._execution_manifest()
                if any(
                    item.owner is not self
                    or item.phase != "live"
                    or item.run_id != bindings.run_id
                    or item.binding_commitment_sha256 != bindings.binding_commitment_sha256
                    or item.managed_attestation_commitment_sha256
                    != managed_attestation_commitment_sha256
                    or item.execution_case_manifest_sha256 != manifest
                    or item.corpus != self._corpus_for(item.corpus_id)
                    for item in canonical
                ):
                    raise ManagedHttpPolicyLifecycleError(
                        "managed_http_policy_canonical_binding_invalid"
                    )
                if (
                    terminal.owner is not self
                    or terminal.phase != "live"
                    or terminal.run_id != bindings.run_id
                    or terminal.binding_commitment_sha256 != bindings.binding_commitment_sha256
                    or terminal.managed_attestation_commitment_sha256
                    != managed_attestation_commitment_sha256
                    or terminal.execution_case_manifest_sha256 != manifest
                ):
                    raise ManagedHttpPolicyLifecycleError(
                        "managed_http_policy_terminal_binding_invalid"
                    )
                material = project_validation_material(
                    bindings=bindings,
                    managed_attestation_commitment_sha256=(managed_attestation_commitment_sha256),
                    adapter_id=self.adapter_id,
                    implementation_sha256=self.implementation_sha256,
                    execution_case_manifest_sha256=manifest,
                    cases=self._cases,
                    corpora=self._corpus_material,
                    cleanup_passes=terminal.cleanup_passes,
                )
                material = registry_evidence.bind_validation_material(material)
                for item in canonical:
                    item.phase = "consumed"
                terminal.phase = "consumed"
            validation = seal_managed_http_policy_validation(material=material)
            if type(validation) is not VerifiedManagedHttpPolicyValidation:
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_validation_type_invalid")
        except ManagedHttpPolicyLifecycleError:
            with self._lock:
                self._phase = "terminal"
            raise
        except BaseException:
            with self._lock:
                self._phase = "terminal"
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_validation_seal_failed"
            ) from None
        with self._lock:
            self._phase = "aggregated"
        return validation

    def _delete_infinity(
        self,
        target: str,
        pass_index: int,
    ) -> ManagedHttpPolicyDeleteReceiptState:
        return project_managed_v5_infinity_cleanup(
            owner=self,
            bindings=self._bindings,
            corpora=self._corpora,
            coordinator=self._exact_cleanup,
            exact_bindings=self._exact_corpus_bindings(),
            target=target,
            pass_index=pass_index,
        )

    def _delete_mem0_v5(self, target: str, pass_index: int) -> ManagedHttpPolicyDeleteReceiptState:
        if not self._corpora:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_exact_cleanup_state_unavailable"
            )
        try:
            payload, observation = run_mem0_cleanup_pass(self._mem0_lifecycle, pass_index)
        except Exception:
            raise ManagedHttpPolicyLifecycleError("managed_v5_policy_mem0_cleanup_failed") from None
        if observation is not None:
            with self._lock:
                current = self._mem0_terminal_observation
                if current is not None and current != observation:
                    raise ManagedHttpPolicyLifecycleError(
                        "managed_v5_policy_mem0_terminal_observation_changed"
                    )
                self._mem0_terminal_observation = observation
        commitments = project_mem0_cleanup_commitments(
            tuple(corpus.bundle for corpus in self._corpora),
            run_id=self._bindings.run_id,
            target_identity_sha256=target,
            pass_index=pass_index,
            acknowledgement={"managed_v5_cleanup": payload},
        )
        return ManagedHttpPolicyDeleteReceiptState(
            self,
            self._bindings.run_id,
            self._bindings.binding_commitment_sha256,
            "mem0",
            target,
            pass_index,
            len(self._corpora),
            len(self._exact_corpus_bindings().mem0_created_memory_ids) if pass_index == 1 else 0,
            False,
            True,
            self._exact_corpus_bindings().manifest_sha256,
            self._exact_corpus_bindings().mem0_created_memory_ids,
            self._exact_corpus_bindings().source_pairs,
            commitments.cleanup_commitment_sha256,
            commitments.corpus_absence_commitments,
            commitments.exact_absence_commitment_sha256,
            "live",
        )

    def _bind_attestation(
        self,
        value: object,
        commitment: object,
        *,
        allow_initial: bool,
    ) -> None:
        _attestation(value, commitment)
        with self._lock:
            if self._managed_attestation is None and allow_initial:
                self._managed_attestation = value
                self._managed_attestation_commitment_sha256 = commitment
                return
            if (
                value is not self._managed_attestation
                or commitment != self._managed_attestation_commitment_sha256
            ):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_attestation_binding_invalid"
                )

    def _execution_manifest(self) -> str:
        value = self._execution_case_manifest_sha256
        if value is None:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_execution_manifest_unavailable"
            )
        return value

    def _corpus_for(self, corpus_id: str) -> ManagedHttpPolicyCorpusMaterial:
        return self._registry_evidence.corpus_material_for(
            corpora=self._corpus_material,
            corpus_id=corpus_id,
        )

    def _bind_cleanup_evidence(
        self,
        evidence: tuple[ManagedHttpPolicyObservedCorpusEvidence, ...],
        execution_manifest: str,
    ) -> None:
        self._registry_evidence.validate_corpus_evidence(
            evidence=evidence,
            expected_corpus_ids={case.corpus_id for case in self._cases},
        )
        with self._lock:
            if self._phase != "consuming-ingest-evidence":
                raise ManagedHttpPolicyLifecycleError("managed_http_policy_canonical_source_replay")
            self._corpora = evidence
            self._execution_case_manifest_sha256 = execution_manifest

    def _issue_canonical_receipt(
        self,
        state: ManagedHttpPolicyCanonicalReceiptState,
    ) -> ManagedHttpPolicyCanonicalSourceReceipt:
        try:
            receipt = issue_canonical_receipt(state)
        except BaseException:
            with self._lock:
                self._phase = "cleanup-only"
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_canonical_receipt_issuance_failed"
            ) from None
        if type(receipt) is not ManagedHttpPolicyCanonicalSourceReceipt:
            with self._lock:
                self._phase = "cleanup-only"
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_canonical_receipt_issuance_failed"
            )
        return receipt

    def _issue_delete_receipt(
        self,
        state: ManagedHttpPolicyDeleteReceiptState,
    ) -> ManagedHttpPolicyDeleteReceipt:
        try:
            receipt = issue_delete_receipt(state)
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_delete_receipt_issuance_failed"
            ) from None
        if type(receipt) is not ManagedHttpPolicyDeleteReceipt:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_delete_receipt_issuance_failed"
            )
        return receipt

    def _exact_corpus_bindings(self) -> ManagedHttpPolicyExactCorpusBindings:
        try:
            return project_exact_corpus_bindings(tuple(corpus.bundle for corpus in self._corpora))
        except ValueError as exc:
            raise ManagedHttpPolicyLifecycleError(str(exc)) from None

    def _new_transport(self, role: str) -> httpx.BaseTransport:
        with self._lock:
            if self._closed:
                raise ManagedHttpPolicyLifecycleError("managed_v5_policy_closed")
        factory = self._transport_factories[role]
        try:
            transport = (
                httpx.HTTPTransport(retries=0, trust_env=False) if factory is None else factory()
            )
        except BaseException:
            raise ManagedHttpPolicyLifecycleError(
                "managed_http_policy_transport_factory_failed"
            ) from None
        if not isinstance(transport, httpx.BaseTransport):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_transport_factory_invalid")
        with self._lock:
            if any(item is transport for item in self._owned_transports):
                raise ManagedHttpPolicyLifecycleError(
                    "managed_http_policy_transport_ownership_invalid"
                )
            self._owned_transports.append(transport)
        return transport

    def close(self) -> None:
        """Release owned Infinity clients only; backend cleanup remains explicit."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            transports = tuple(reversed(self._owned_transports))
            self._owned_transports.clear()
        failed = False
        for transport in transports:
            try:
                transport.close()
            except BaseException:
                failed = True
        if failed:
            raise ManagedHttpPolicyLifecycleError("managed_v5_policy_close_failed")

    def _validate_call(
        self,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        self._validate_binding(bindings)
        if (
            type(cases) is not tuple
            or len(cases) != len(self._cases)
            or any(
                actual is not expected for actual, expected in zip(cases, self._cases, strict=True)
            )
        ):
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_case_binding_invalid")

    def _validate_binding(self, bindings: FullComparisonRunBindings) -> None:
        self._ensure_deadline()
        if bindings is not self._bindings or binding_snapshot(bindings) != self._binding_snapshot:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_binding_changed")

    def _ensure_deadline(self) -> None:
        if _aware(self._clock(), "managed_http_policy_clock_invalid") >= self._deadline:
            raise ManagedHttpPolicyLifecycleError("managed_http_policy_deadline_expired")

    def _target(self, role: str) -> str:
        return managed_v5_target_identity(self._bindings, role)


__all__ = (
    "MANAGED_V5_POLICY_ADAPTER_ID",
    "ManagedInfinityV5PolicyLifecycleAdapter",
    "ManagedHttpPolicyExactProjectionEvidence",
    "ManagedHttpPolicyCanonicalSourceReceipt",
    "ManagedHttpPolicyDeleteReceipt",
    "ManagedHttpPolicyLifecycleError",
    "ManagedHttpPolicyTerminalDeleteReceipt",
    "managed_http_policy_production_blockers",
    "managed_v5_policy_lifecycle_implementation_sha256",
)
