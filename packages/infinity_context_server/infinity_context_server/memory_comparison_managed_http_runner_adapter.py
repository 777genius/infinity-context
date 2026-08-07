"""Legacy HTTP compatibility adapter for neutral managed runner seams."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import final

from infinity_context_server.memory_comparison_clean_state import (
    public_clean_state_validation,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    VerifiedFullExecutionValidation,
    issue_full_execution_validation_session,
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
from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
    ManagedHttpRetrievalResult,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedComparisonHttpLifecycleAdapter,
    ManagedHttpExecutionEvidenceView,
    consume_managed_http_execution_evidence,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalAuthority,
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
    _validate_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
    _thaw_json,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
)


class ManagedHttpRunnerAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _AdapterState:
    binding: ManagedRunnerCompositionBinding
    http: ManagedComparisonHttpExecutionAdapter
    lifecycle: ManagedComparisonHttpLifecycleAdapter
    http_profile: object
    run_id: str
    profile_id: str
    deadline: object
    target_pairs: tuple[tuple[str, str], ...]
    retrieval_top_k: int
    answer_cutoff: int
    phase: str
    evidence: ManagedHttpExecutionEvidenceView | None
    evidence_snapshot: str | None
    integrity_mac: bytes


_ADAPTER_LOCK = threading.RLock()
_ADAPTER_SECRET = secrets.token_bytes(32)
_KEEP = object()
_ADAPTERS: weakref.WeakKeyDictionary[ManagedHttpRunnerAdapter, _AdapterState]


@final
class ManagedHttpRunnerAdapter:
    __slots__ = (
        "__weakref__",
        "_binding",
        "_evidence",
        "_evidence_snapshot",
        "_http",
        "_lifecycle",
        "_phase",
    )

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        http: ManagedComparisonHttpExecutionAdapter,
        lifecycle: ManagedComparisonHttpLifecycleAdapter,
    ) -> None:
        if (
            type(composition_binding) is not ManagedRunnerCompositionBinding
            or type(http) is not ManagedComparisonHttpExecutionAdapter
            or type(lifecycle) is not ManagedComparisonHttpLifecycleAdapter
            or not _legacy_composition_matches(composition_binding, http, lifecycle)
            or http.retrieval_top_k != composition_binding.retrieval_top_k
            or http.answer_cutoff != composition_binding.answer_cutoff
        ):
            raise ManagedHttpRunnerAdapterError("managed_http_runner_composition_invalid")
        self._binding = composition_binding
        self._http = http
        self._lifecycle = lifecycle
        self._evidence: ManagedHttpExecutionEvidenceView | None = None
        self._evidence_snapshot: str | None = None
        self._phase = "new"
        target_pairs = tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in composition_binding.backend_targets
        )
        state = _AdapterState(
            composition_binding,
            http,
            lifecycle,
            http._profile,
            composition_binding.run_id,
            composition_binding.profile_id,
            composition_binding.deadline,
            target_pairs,
            composition_binding.retrieval_top_k,
            composition_binding.answer_cutoff,
            "new",
            None,
            None,
            b"",
        )
        _store_adapter_state(self, state)

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _adapter_state(self).binding

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority:
        state = _adapter_state(self)
        return _issue_managed_retrieval_authority(
            state.binding,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )

    def retrieve(
        self,
        *,
        authority: ManagedRetrievalAuthority,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
    ) -> ManagedRetrievalResult:
        state = _adapter_state(self)
        if (
            type(case) is not ManagedRunCase
            or type(query) is not ManagedAnswerCase
            or case.case_id != query.case_id
        ):
            raise ManagedHttpRunnerAdapterError("managed_http_runner_retrieval_invalid")
        try:
            backend_role, target_identity = _validate_managed_retrieval_authority(
                authority,
                composition_binding=state.binding,
            )
        except Exception:
            raise ManagedHttpRunnerAdapterError("managed_http_runner_retrieval_invalid") from None
        try:
            result = state.http.retrieve(
                run_id=state.run_id,
                backend_role=backend_role,
                target_identity_sha256=target_identity,
                case=case,
                query=query,
            )
        except Exception:
            raise ManagedHttpRunnerAdapterError("managed_http_runner_retrieval_failed") from None
        if type(result) is not ManagedHttpRetrievalResult:
            raise ManagedHttpRunnerAdapterError("managed_http_runner_retrieval_result_invalid")
        return ManagedRetrievalResult(result.evidence, result.retrieval_identity, result.metadata)

    def consume_ready_evidence(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        bindings: FullComparisonRunBindings,
        cases: tuple[ManagedRunCase, ...],
    ) -> None:
        state = self._require_composition(composition_binding, bindings)
        if (
            state.phase != "new"
            or type(cases) is not tuple
            or not cases
            or any(type(item) is not ManagedRunCase for item in cases)
        ):
            raise ManagedHttpRunnerAdapterError("managed_http_runner_evidence_invalid")
        state = _transition_adapter(self, state, phase="consuming")
        try:
            view = consume_managed_http_execution_evidence(
                state.lifecycle.execution_evidence_capability(),
                run_id=bindings.run_id,
                binding_commitment_sha256=bindings.binding_commitment_sha256,
                backend_targets=bindings.backend_targets,
                cases=cases,
            )
            if type(view) is not ManagedHttpExecutionEvidenceView:
                raise TypeError
            snapshot = _evidence_snapshot(view)
        except Exception:
            _transition_adapter(self, state, phase="terminal", clear_evidence=True)
            raise ManagedHttpRunnerAdapterError(
                "managed_http_runner_evidence_consume_failed"
            ) from None
        _transition_adapter(
            self,
            state,
            phase="ready",
            evidence=view,
            evidence_snapshot=snapshot,
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
        view = state.evidence
        if state.phase != "ready" or type(view) is not ManagedHttpExecutionEvidenceView:
            raise ManagedHttpRunnerAdapterError("managed_http_runner_evidence_not_ready")
        state = _transition_adapter(self, state, phase="sealing")
        try:
            if state.evidence_snapshot != _evidence_snapshot(view):
                raise TypeError
            session = issue_full_execution_validation_session(
                bindings=bindings,
                benchmark=benchmark,
                case_manifest=case_manifest,
                required_model=required_model,
                required_route=required_route,
                provider_calls=provider_calls,
                session_verifier=session_verifier,
                session_evidence=session_evidence,
                transport_verifier=view.locomo_timestamp_verifier,
                transport_evidence=view.locomo_timestamp_evidence,
                clean_validation=view.validation,
                clean_scopes=view.scopes,
                clean_attestation_key=view.attestation_key,
            )
            proof = seal_full_execution_validation(session)
            if type(proof) is not VerifiedFullExecutionValidation:
                raise TypeError
        except Exception:
            _transition_adapter(
                self,
                state,
                phase="terminal",
                clear_evidence=True,
            )
            raise ManagedHttpRunnerAdapterError("managed_http_runner_validation_failed") from None
        _transition_adapter(
            self,
            state,
            phase="sealed",
            clear_evidence=True,
        )
        return proof

    def _require_composition(
        self,
        composition_binding: object,
        bindings: FullComparisonRunBindings,
    ) -> _AdapterState:
        state = _adapter_state(self)
        try:
            trusted = validate_full_comparison_run_bindings(bindings)
        except Exception:
            raise ManagedHttpRunnerAdapterError("managed_http_runner_bindings_invalid") from None
        if (
            composition_binding is not state.binding
            or trusted.run_id != state.binding.run_id
            or trusted.profile_id != state.binding.profile_id
            or trusted.binding_commitment_sha256
            != state.binding.binding_commitment_sha256
            or trusted.backend_targets != state.binding.backend_targets
        ):
            raise ManagedHttpRunnerAdapterError("managed_http_runner_bindings_invalid")
        return state


def _adapter_state(value: object) -> _AdapterState:
    if type(value) is not ManagedHttpRunnerAdapter:
        raise ManagedHttpRunnerAdapterError("managed_http_runner_composition_invalid")
    with _ADAPTER_LOCK:
        state = _ADAPTERS.get(value)
    if state is None or not hmac.compare_digest(
        state.integrity_mac, _adapter_mac(value, state)
    ):
        raise ManagedHttpRunnerAdapterError("managed_http_runner_composition_invalid")
    try:
        live_matches = (
            value._binding is state.binding
            and value._http is state.http
            and value._lifecycle is state.lifecycle
            and value._phase == state.phase
            and value._evidence is state.evidence
            and value._evidence_snapshot == state.evidence_snapshot
            and state.binding.run_id == state.run_id
            and state.binding.profile_id == state.profile_id
            and state.binding.deadline is state.deadline
            and tuple(
                (item.backend_role, item.target_identity_sha256)
                for item in state.binding.backend_targets
            )
            == state.target_pairs
            and state.binding.retrieval_top_k == state.retrieval_top_k
            and state.binding.answer_cutoff == state.answer_cutoff
            and state.http._profile is state.http_profile
            and state.http._run_id == state.run_id
            and state.http._deadline is state.deadline
            and state.http._targets == dict(state.target_pairs)
            and state.http.retrieval_top_k == state.retrieval_top_k
            and state.http.answer_cutoff == state.answer_cutoff
            and _legacy_composition_matches(state.binding, state.http, state.lifecycle)
        )
    except Exception:
        live_matches = False
    if not live_matches:
        raise ManagedHttpRunnerAdapterError("managed_http_runner_composition_invalid")
    return state


def _transition_adapter(
    adapter: ManagedHttpRunnerAdapter,
    state: _AdapterState,
    *,
    phase: str,
    evidence: object = _KEEP,
    evidence_snapshot: object = _KEEP,
    clear_evidence: bool = False,
) -> _AdapterState:
    next_evidence = None if clear_evidence else state.evidence
    next_snapshot = None if clear_evidence else state.evidence_snapshot
    if evidence is not _KEEP:
        next_evidence = evidence
    if evidence_snapshot is not _KEEP:
        next_snapshot = evidence_snapshot
    next_state = replace(
        state,
        phase=phase,
        evidence=next_evidence,
        evidence_snapshot=next_snapshot,
        integrity_mac=b"",
    )
    return _store_adapter_state(adapter, next_state)


def _store_adapter_state(
    adapter: ManagedHttpRunnerAdapter,
    state: _AdapterState,
) -> _AdapterState:
    trusted = replace(state, integrity_mac=_adapter_mac(adapter, state))
    adapter._binding = trusted.binding
    adapter._http = trusted.http
    adapter._lifecycle = trusted.lifecycle
    adapter._phase = trusted.phase
    adapter._evidence = trusted.evidence
    adapter._evidence_snapshot = trusted.evidence_snapshot
    with _ADAPTER_LOCK:
        _ADAPTERS[adapter] = trusted
    return trusted


def _adapter_mac(adapter: ManagedHttpRunnerAdapter, state: _AdapterState) -> bytes:
    material = {
        "adapter_identity": id(adapter),
        "binding_identity": id(state.binding),
        "http_identity": id(state.http),
        "lifecycle_identity": id(state.lifecycle),
        "http_profile_identity": id(state.http_profile),
        "run_id": state.run_id,
        "profile_id": state.profile_id,
        "deadline_identity": id(state.deadline),
        "target_pairs": state.target_pairs,
        "retrieval_top_k": state.retrieval_top_k,
        "answer_cutoff": state.answer_cutoff,
        "phase": state.phase,
        "evidence_identity": id(state.evidence) if state.evidence is not None else None,
        "evidence_snapshot": state.evidence_snapshot,
    }
    return hmac.new(
        _ADAPTER_SECRET,
        canonical_dispatch_json(material),
        hashlib.sha256,
    ).digest()


def _legacy_composition_matches(
    binding: ManagedRunnerCompositionBinding,
    http: ManagedComparisonHttpExecutionAdapter,
    lifecycle: ManagedComparisonHttpLifecycleAdapter,
) -> bool:
    try:
        target_pairs = tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in binding.backend_targets
        )
        return (
            http._run_id == binding.run_id
            and http._profile.profile_id == binding.profile_id
            and http._deadline is binding.deadline
            and http._targets == dict(target_pairs)
            and lifecycle._run_id == binding.run_id
            and lifecycle._binding == binding.binding_commitment_sha256
            and lifecycle._deadline is binding.deadline
            and lifecycle._target_pairs == target_pairs
            and lifecycle._execution is http
        )
    except (AttributeError, TypeError):
        return False


def _evidence_snapshot(view: ManagedHttpExecutionEvidenceView) -> str:
    material = {
        "validation": public_clean_state_validation(view.validation),
        "scopes": [
            [item.backend_role, item.corpus_identity_sha256, item.scope_identity_sha256]
            for item in view.scopes
        ],
        "attestation_key_sha256": hashlib.sha256(view.attestation_key).hexdigest(),
        "locomo_verifier_identity": (
            id(view.locomo_timestamp_verifier)
            if view.locomo_timestamp_verifier is not None
            else None
        ),
        "locomo_evidence_identities": [id(item) for item in view.locomo_timestamp_evidence],
        "provenance": _thaw_json(view.provenance),
    }
    return hashlib.sha256(canonical_dispatch_json(material)).hexdigest()


_ADAPTERS = weakref.WeakKeyDictionary()
