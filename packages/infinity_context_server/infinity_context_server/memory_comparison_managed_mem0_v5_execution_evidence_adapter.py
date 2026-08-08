"""Managed Mem0 v5 implementation of the neutral execution-evidence port."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import NoReturn, final

from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    FullExecutionCleanStateEvidence,
    FullExecutionCleanStateEvidenceDescriptor,
    FullExecutionTransportEvidence,
    FullExecutionTransportEvidenceDescriptor,
    inspect_full_execution_clean_state_evidence,
    inspect_full_execution_transport_evidence,
    issue_managed_mem0_v5_full_execution_transport_evidence,
    issue_managed_mem0_v5_ready_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
    issue_full_execution_validation_session_from_evidence,
    seal_full_execution_validation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
    validate_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_managed_infinity_clean_state_source import (
    ManagedInfinityCleanStateEvidenceSource,
    authenticate_managed_infinity_clean_state_evidence_source,
    consume_managed_infinity_clean_state_evidence_source,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lifecycle_adapter import (
    ManagedMem0V5LifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
)


class ManagedMem0V5ExecutionEvidenceAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _AdapterState:
    binding: ManagedRunnerCompositionBinding
    lifecycle: ManagedMem0V5LifecycleAdapter
    infinity_source: ManagedInfinityCleanStateEvidenceSource
    infinity_source_implementation_sha256: str
    infinity_clean_state_evidence: FullExecutionCleanStateEvidence | None
    infinity_descriptor: FullExecutionCleanStateEvidenceDescriptor | None
    phase: str
    case_snapshot: tuple[tuple[str, str], ...]
    transport_evidence: FullExecutionTransportEvidence | None
    transport_descriptor: FullExecutionTransportEvidenceDescriptor | None
    mem0_evidence: FullExecutionCleanStateEvidence | None
    mem0_descriptor: FullExecutionCleanStateEvidenceDescriptor | None
    integrity_mac: bytes


_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)
_STATES: weakref.WeakKeyDictionary[ManagedMem0V5ExecutionEvidenceAdapter, _AdapterState]


@final
class ManagedMem0V5ExecutionEvidenceAdapter:
    """One-shot provider-free evidence orchestration for a managed v5 run."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        lifecycle: ManagedMem0V5LifecycleAdapter,
        infinity_clean_state_source: ManagedInfinityCleanStateEvidenceSource,
    ) -> None:
        try:
            source_implementation = authenticate_managed_infinity_clean_state_evidence_source(
                infinity_clean_state_source,
                composition_binding=composition_binding,
            )
            valid = (
                type(composition_binding) is ManagedRunnerCompositionBinding
                and type(lifecycle) is ManagedMem0V5LifecycleAdapter
                and lifecycle.composition_binding is composition_binding
                and type(infinity_clean_state_source) is ManagedInfinityCleanStateEvidenceSource
            )
        except Exception:
            valid = False
        if not valid:
            raise ManagedMem0V5ExecutionEvidenceAdapterError(
                "managed_mem0_v5_execution_evidence_composition_invalid"
            )
        _store(
            self,
            _AdapterState(
                composition_binding,
                lifecycle,
                infinity_clean_state_source,
                source_implementation,
                None,
                None,
                "new",
                (),
                None,
                None,
                None,
                None,
                b"",
            ),
        )

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _state(self).binding

    def consume_ready_evidence(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        state = self._require_composition(composition_binding, bindings)
        snapshot, corpus_ids = _validate_cases(cases)
        if state.phase != "new":
            self._fail("state_invalid")
        try:
            lifecycle_corpus_ids = state.lifecycle._validate_execution_cases_for_adapter(
                composition_binding=state.binding,
                cases=cases,
            )
        except Exception:
            self._fail("cases_invalid")
        if lifecycle_corpus_ids != corpus_ids:
            self._fail("cases_invalid")
        state = _begin(self, state, expected="new", phase="consuming")
        try:
            infinity = consume_managed_infinity_clean_state_evidence_source(
                state.infinity_source,
                composition_binding=state.binding,
                corpus_ids=corpus_ids,
                producer_implementation_sha256=(state.infinity_source_implementation_sha256),
            )
            infinity_descriptor = inspect_full_execution_clean_state_evidence(infinity)
            if not _infinity_matches(
                infinity,
                infinity_descriptor,
                state.binding,
                corpus_ids,
            ):
                raise TypeError
            handoff = state.lifecycle._consume_ready_execution_material_for_adapter(
                composition_binding=state.binding,
                cases=cases,
            )
            if handoff.corpus_ids != corpus_ids:
                raise TypeError
            transport = issue_managed_mem0_v5_full_execution_transport_evidence(
                coverage=handoff.coverage
            )
            mem0 = issue_managed_mem0_v5_ready_full_execution_clean_state_evidence(
                claim=handoff.ready_clean_state_claim
            )
            transport_descriptor = inspect_full_execution_transport_evidence(transport)
            mem0_descriptor = inspect_full_execution_clean_state_evidence(mem0)
            if not _managed_descriptors_match(
                transport_descriptor,
                mem0_descriptor,
                state.binding,
                corpus_ids,
            ):
                raise TypeError
        except Exception:
            _transition(self, state, phase="terminal", clear=True)
            self._fail("consume_failed")
        _transition(
            self,
            state,
            phase="ready",
            case_snapshot=snapshot,
            infinity_clean_state_evidence=infinity,
            infinity_descriptor=infinity_descriptor,
            transport_evidence=transport,
            transport_descriptor=transport_descriptor,
            mem0_evidence=mem0,
            mem0_descriptor=mem0_descriptor,
        )

    def seal_execution_validation(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        benchmark: str,
        case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
        required_model: str,
        required_route: ProviderRouteAttestation,
        provider_calls: tuple[FullExecutionProviderCall, ...],
        session_verifier: RunScopedSessionHmacKey,
        session_evidence: tuple[SessionIdentityEvidence, ...],
    ) -> VerifiedFullExecutionValidation:
        state = self._require_composition(composition_binding, bindings)
        if state.phase != "ready":
            self._fail("not_ready")
        try:
            seal_inputs_valid = (
                type(case_manifest) is tuple
                and all(type(item) is FullExecutionCaseManifestEntry for item in case_manifest)
                and tuple((item.case_id, item.corpus_id) for item in case_manifest)
                == state.case_snapshot
                and benchmark == state.binding.profile.benchmark
            )
        except Exception:
            seal_inputs_valid = False
        if not seal_inputs_valid:
            self._fail("seal_inputs_invalid")
        state = _begin(self, state, expected="ready", phase="sealing")
        try:
            if not _ready_evidence_matches(state):
                raise TypeError
            transport = state.transport_evidence
            infinity_clean_state_evidence = state.infinity_clean_state_evidence
            mem0 = state.mem0_evidence
            if transport is None or infinity_clean_state_evidence is None or mem0 is None:
                raise TypeError
            session = issue_full_execution_validation_session_from_evidence(
                bindings=bindings,
                benchmark=benchmark,
                case_manifest=case_manifest,
                required_model=required_model,
                required_route=required_route,
                provider_calls=provider_calls,
                session_verifier=session_verifier,
                session_evidence=session_evidence,
                transport_evidence=transport,
                clean_state_evidence=(infinity_clean_state_evidence, mem0),
            )
            proof = seal_full_execution_validation(session)
            if type(proof) is not VerifiedFullExecutionValidation:
                raise TypeError
        except Exception:
            _transition(self, state, phase="terminal", clear=True)
            self._fail("validation_failed")
        _transition(self, state, phase="sealed", clear=True)
        return proof

    def _require_composition(
        self,
        composition_binding: object,
        bindings: FullComparisonRunBindings,
    ) -> _AdapterState:
        state = _state(self)
        try:
            trusted = validate_full_comparison_run_bindings(bindings)
            valid = (
                composition_binding is state.binding
                and trusted.run_id == state.binding.run_id
                and trusted.profile_id == state.binding.profile_id
                and trusted.binding_commitment_sha256 == state.binding.binding_commitment_sha256
                and trusted.backend_targets == state.binding.backend_targets
            )
        except Exception:
            valid = False
        if not valid:
            self._fail("bindings_invalid")
        return state

    def _fail(self, suffix: str) -> NoReturn:
        raise ManagedMem0V5ExecutionEvidenceAdapterError(
            f"managed_mem0_v5_execution_evidence_{suffix}"
        )

    def __repr__(self) -> str:
        return "ManagedMem0V5ExecutionEvidenceAdapter(<opaque>)"


def _validate_cases(
    cases: object,
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    if (
        type(cases) is not tuple
        or not cases
        or any(type(item) is not ManagedRunCase for item in cases)
        or len({item.case_id for item in cases}) != len(cases)
    ):
        raise ManagedMem0V5ExecutionEvidenceAdapterError(
            "managed_mem0_v5_execution_evidence_cases_invalid"
        )
    snapshot = tuple((item.case_id, item.corpus_id) for item in cases)
    return snapshot, tuple(dict.fromkeys(item.corpus_id for item in cases))


def _infinity_matches(
    evidence: object,
    snapshot: FullExecutionCleanStateEvidenceDescriptor | None,
    binding: ManagedRunnerCompositionBinding,
    corpus_ids: tuple[str, ...],
) -> bool:
    try:
        descriptor = inspect_full_execution_clean_state_evidence(evidence)
    except Exception:
        return False
    return (
        descriptor == snapshot
        and descriptor.variant == "infinity_di"
        and descriptor.backend_roles == ("infinity-context",)
        and descriptor.run_id_sha256 == _run_sha256(binding.run_id)
        and tuple(item[0] for item in descriptor.corpus_scopes)
        == tuple(canonical_sha256({"corpus_id": item}) for item in corpus_ids)
    )


def _managed_descriptors_match(
    transport: FullExecutionTransportEvidenceDescriptor,
    clean: FullExecutionCleanStateEvidenceDescriptor,
    binding: ManagedRunnerCompositionBinding,
    corpus_ids: tuple[str, ...],
) -> bool:
    corpus_digests = tuple(canonical_sha256({"corpus_id": item}) for item in corpus_ids)
    return (
        transport.variant == "managed_mem0_v5"
        and transport.benchmark == binding.profile.benchmark
        and transport.backend_roles == ("mem0",)
        and transport.run_id_sha256 == _run_sha256(binding.run_id)
        and tuple(item[0] for item in transport.per_corpus_operation_counts) == corpus_ids
        and transport.operation_count
        == sum(count for _, count in transport.per_corpus_operation_counts)
        and clean.variant == "managed_mem0_v5"
        and clean.backend_roles == ("mem0",)
        and clean.run_id_sha256 == transport.run_id_sha256
        and clean.admission_commitment_sha256 == transport.admission_commitment_sha256
        and clean.authority_commitment_sha256 == transport.authority_commitment_sha256
        and tuple(item[0] for item in clean.corpus_scopes) == corpus_digests
    )


def _ready_evidence_matches(state: _AdapterState) -> bool:
    try:
        return (
            state.infinity_clean_state_evidence is not None
            and inspect_full_execution_clean_state_evidence(state.infinity_clean_state_evidence)
            == state.infinity_descriptor
            and state.transport_evidence is not None
            and inspect_full_execution_transport_evidence(state.transport_evidence)
            == state.transport_descriptor
            and state.mem0_evidence is not None
            and inspect_full_execution_clean_state_evidence(state.mem0_evidence)
            == state.mem0_descriptor
        )
    except Exception:
        return False


def _begin(
    adapter: ManagedMem0V5ExecutionEvidenceAdapter,
    state: _AdapterState,
    *,
    expected: str,
    phase: str,
) -> _AdapterState:
    with _LOCK:
        current = _state_locked(adapter)
        if current is not state or current.phase != expected:
            adapter._fail("state_invalid")
        return _store_locked(adapter, replace(current, phase=phase, integrity_mac=b""))


def _transition(
    adapter: ManagedMem0V5ExecutionEvidenceAdapter,
    state: _AdapterState,
    *,
    phase: str,
    case_snapshot: tuple[tuple[str, str], ...] | None = None,
    infinity_clean_state_evidence: FullExecutionCleanStateEvidence | None = None,
    infinity_descriptor: FullExecutionCleanStateEvidenceDescriptor | None = None,
    transport_evidence: FullExecutionTransportEvidence | None = None,
    transport_descriptor: FullExecutionTransportEvidenceDescriptor | None = None,
    mem0_evidence: FullExecutionCleanStateEvidence | None = None,
    mem0_descriptor: FullExecutionCleanStateEvidenceDescriptor | None = None,
    clear: bool = False,
) -> _AdapterState:
    with _LOCK:
        current = _state_locked(adapter)
        if current.phase != state.phase:
            adapter._fail("state_invalid")
        return _store_locked(
            adapter,
            replace(
                current,
                phase=phase,
                case_snapshot=(current.case_snapshot if case_snapshot is None else case_snapshot),
                infinity_clean_state_evidence=(
                    None
                    if clear
                    else current.infinity_clean_state_evidence
                    if infinity_clean_state_evidence is None
                    else infinity_clean_state_evidence
                ),
                infinity_descriptor=(
                    None
                    if clear
                    else current.infinity_descriptor
                    if infinity_descriptor is None
                    else infinity_descriptor
                ),
                transport_evidence=(
                    None
                    if clear
                    else current.transport_evidence
                    if transport_evidence is None
                    else transport_evidence
                ),
                transport_descriptor=(
                    None
                    if clear
                    else current.transport_descriptor
                    if transport_descriptor is None
                    else transport_descriptor
                ),
                mem0_evidence=(
                    None
                    if clear
                    else current.mem0_evidence
                    if mem0_evidence is None
                    else mem0_evidence
                ),
                mem0_descriptor=(
                    None
                    if clear
                    else current.mem0_descriptor
                    if mem0_descriptor is None
                    else mem0_descriptor
                ),
                integrity_mac=b"",
            ),
        )


def _state(value: object) -> _AdapterState:
    if type(value) is not ManagedMem0V5ExecutionEvidenceAdapter:
        raise ManagedMem0V5ExecutionEvidenceAdapterError(
            "managed_mem0_v5_execution_evidence_composition_invalid"
        )
    with _LOCK:
        return _state_locked(value)


def _state_locked(adapter: ManagedMem0V5ExecutionEvidenceAdapter) -> _AdapterState:
    state = _STATES.get(adapter)
    try:
        valid = (
            state is not None
            and hmac.compare_digest(
                state.integrity_mac,
                _mac(adapter, replace(state, integrity_mac=b"")),
            )
            and type(state.lifecycle) is ManagedMem0V5LifecycleAdapter
            and state.lifecycle.composition_binding is state.binding
            and type(state.infinity_source) is ManagedInfinityCleanStateEvidenceSource
        )
    except Exception:
        valid = False
    if not valid or state is None:
        raise ManagedMem0V5ExecutionEvidenceAdapterError(
            "managed_mem0_v5_execution_evidence_composition_invalid"
        )
    return state


def _store(adapter: ManagedMem0V5ExecutionEvidenceAdapter, state: _AdapterState) -> None:
    with _LOCK:
        _store_locked(adapter, state)


def _store_locked(
    adapter: ManagedMem0V5ExecutionEvidenceAdapter,
    state: _AdapterState,
) -> _AdapterState:
    trusted = replace(state, integrity_mac=_mac(adapter, replace(state, integrity_mac=b"")))
    _STATES[adapter] = trusted
    return trusted


def _mac(adapter: ManagedMem0V5ExecutionEvidenceAdapter, state: _AdapterState) -> bytes:
    payload = {
        "adapter_identity": id(adapter),
        "binding_identity": id(state.binding),
        "lifecycle_identity": id(state.lifecycle),
        "infinity_source_identity": id(state.infinity_source),
        "infinity_source_implementation": state.infinity_source_implementation_sha256,
        "infinity_identity": None
        if state.infinity_clean_state_evidence is None
        else id(state.infinity_clean_state_evidence),
        "infinity_commitment": None
        if state.infinity_descriptor is None
        else state.infinity_descriptor.evidence_commitment_sha256,
        "phase": state.phase,
        "case_snapshot": state.case_snapshot,
        "transport_identity": None
        if state.transport_evidence is None
        else id(state.transport_evidence),
        "transport_commitment": None
        if state.transport_descriptor is None
        else state.transport_descriptor.evidence_commitment_sha256,
        "mem0_identity": None if state.mem0_evidence is None else id(state.mem0_evidence),
        "mem0_commitment": None
        if state.mem0_descriptor is None
        else state.mem0_descriptor.evidence_commitment_sha256,
    }
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


def _run_sha256(run_id: str) -> str:
    return hashlib.sha256(run_id.encode()).hexdigest()


_STATES = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedMem0V5ExecutionEvidenceAdapter",
    "ManagedMem0V5ExecutionEvidenceAdapterError",
)
