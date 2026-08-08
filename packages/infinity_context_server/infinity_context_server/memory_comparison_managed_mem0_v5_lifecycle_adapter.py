"""Authenticated one-shot lifecycle owner for a managed Mem0 v5 paired run."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from enum import Enum
from typing import NoReturn, final

from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_readback import (
    ManagedMem0V5CleanupReadbackWitness,
    validate_managed_mem0_v5_cleanup_readback_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_ingest_receipts import (
    ManagedMem0V5CorpusIngestReceipt,
    ManagedMem0V5CorpusIngestReceiptSet,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5CleanupReadbackCapabilityPort,
    ManagedMem0V5PairedRun,
    managed_mem0_v5_paired_run_fingerprint,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CorpusIngestEvidence,
    ManagedMem0V5ReadyCleanStateClaim,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    ManagedTransportCoverageCapability,
    ManagedTransportCoverageCapabilityPort,
    VerifiedManagedTransportCoverage,
    authenticate_managed_transport_coverage,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssRunSeal,
    Mem0OssTerminalCleanupEvidence,
)


class ManagedMem0V5LifecycleAdapterError(RuntimeError):
    pass


class _Phase(Enum):
    NEW = "new"
    ADMITTING = "admitting"
    ADMITTED = "admitted"
    RESTORING = "restoring"
    DISPATCHING = "dispatching"
    SEALED = "sealed"
    COVERING = "covering"
    COVERED = "covered"
    PROJECTING = "projecting"
    RECEIPTS = "receipts"
    CONSUMING = "consuming"
    CLEANING = "cleaning"
    CLEANUP_RETRY = "cleanup_retry"
    ABORTING = "aborting"
    ABORT_RETRY = "abort_retry"
    TERMINAL = "terminal"
    PASS_TWO = "pass_two"
    PASS_TWO_COMPLETE = "pass_two_complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class _LifecycleState:
    binding: ManagedRunnerCompositionBinding
    paired_run: ManagedMem0V5PairedRun
    authority: ManagedMem0V5ManifestAuthority
    request: Mem0OssAdmissionRequest
    cleanup_readback: ManagedMem0V5CleanupReadbackCapabilityPort
    receipt_set: ManagedMem0V5CorpusIngestReceiptSet
    corpus_ids: tuple[str, ...]
    mem0_target_identity_sha256: str
    phase: _Phase
    coverage: VerifiedManagedTransportCoverage | None
    receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    receipts_consumed: bool
    execution_evidence_consumed: bool
    terminal: Mem0OssTerminalCleanupEvidence | None
    integrity_mac: bytes


@dataclass(frozen=True, slots=True)
class _ManagedMem0V5ExecutionEvidenceHandoff:
    coverage: VerifiedManagedTransportCoverage
    ready_clean_state_claim: ManagedMem0V5ReadyCleanStateClaim
    corpus_ids: tuple[str, ...]


_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)
_STATES: weakref.WeakKeyDictionary[ManagedMem0V5LifecycleAdapter, _LifecycleState]


@final
class ManagedMem0V5LifecycleAdapter:
    """Own NEW -> ADMITTED -> SEALED -> TERMINAL plus bounded recovery."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        paired_run: ManagedMem0V5PairedRun,
        authority: ManagedMem0V5ManifestAuthority,
        request: Mem0OssAdmissionRequest,
        cleanup_readback_capability: ManagedMem0V5CleanupReadbackCapabilityPort,
    ) -> None:
        corpus_ids, target = _validate_composition(
            composition_binding,
            paired_run,
            authority,
            request,
            cleanup_readback_capability,
        )
        state = _LifecycleState(
            composition_binding,
            paired_run,
            authority,
            request,
            cleanup_readback_capability,
            ManagedMem0V5CorpusIngestReceiptSet(
                composition_binding=composition_binding,
                corpus_ids=corpus_ids,
                authority_commitment_sha256=authority.authority_commitment_sha256,
            ),
            corpus_ids,
            target,
            _Phase.NEW,
            None,
            (),
            False,
            False,
            None,
            b"",
        )
        _store(self, state)

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        return _state(self).binding

    @property
    def terminal_evidence(self) -> Mem0OssTerminalCleanupEvidence:
        state = _state(self)
        if state.phase not in {_Phase.TERMINAL, _Phase.PASS_TWO, _Phase.PASS_TWO_COMPLETE}:
            self._fail("terminal_invalid")
        if state.terminal is None:
            self._fail("terminal_invalid")
        state.terminal.__post_init__()
        return state.terminal

    def admit(self) -> ManagedMem0V5AuthenticatedCleanStateWitness:
        state = _begin(self, {_Phase.NEW}, _Phase.ADMITTING, "admit_invalid")
        try:
            witness = state.paired_run.admit()
        except Exception:
            _finish_abort_outcome(self)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_admit_failed"
            ) from None
        if type(witness) is not ManagedMem0V5AuthenticatedCleanStateWitness:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_admit_result_invalid"
            )
        _transition(self, phase=_Phase.ADMITTED)
        return witness

    def restore(self) -> Mem0OssRunSeal | Mem0OssTerminalCleanupEvidence:
        """Resume only an unattempted lifecycle instance from durable paired state."""

        state = _begin(self, {_Phase.NEW}, _Phase.RESTORING, "restore_invalid")
        try:
            restored = state.paired_run.restore()
        except Exception:
            _finish_abort_outcome(self)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_restore_failed"
            ) from None
        if type(restored) is Mem0OssRunSeal:
            _transition(self, phase=_Phase.SEALED)
        elif type(restored) is Mem0OssTerminalCleanupEvidence:
            restored.__post_init__()
            _transition(self, phase=_Phase.TERMINAL, terminal=restored)
        else:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_restore_result_invalid"
            )
        return restored

    def dispatch_once(self) -> Mem0OssRunSeal:
        state = _begin(self, {_Phase.ADMITTED}, _Phase.DISPATCHING, "dispatch_invalid")
        try:
            seal = state.paired_run.dispatch()
        except Exception:
            _finish_abort_outcome(self)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_dispatch_failed"
            ) from None
        if type(seal) is not Mem0OssRunSeal:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_dispatch_result_invalid"
            )
        _transition(self, phase=_Phase.SEALED)
        return seal

    def retry_abort(self) -> Mem0OssTerminalCleanupEvidence:
        state = _begin(self, {_Phase.ABORT_RETRY}, _Phase.ABORTING, "abort_retry_invalid")
        try:
            terminal = state.paired_run.retry_abort()
        except Exception:
            _transition(self, phase=_Phase.ABORT_RETRY)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_abort_retry_failed"
            ) from None
        if type(terminal) is not Mem0OssTerminalCleanupEvidence:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_abort_retry_result_invalid"
            )
        _transition(self, phase=_Phase.TERMINAL, terminal=terminal)
        return terminal

    def abort(self) -> Mem0OssTerminalCleanupEvidence:
        """Abort from every stable started phase without re-admission or redispatch."""

        state = _begin(
            self,
            {_Phase.ADMITTED, _Phase.SEALED, _Phase.COVERED, _Phase.RECEIPTS},
            _Phase.ABORTING,
            "abort_invalid",
        )
        try:
            terminal = state.paired_run.abort()
        except Exception:
            _transition(self, phase=_Phase.ABORT_RETRY)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_abort_failed"
            ) from None
        if type(terminal) is not Mem0OssTerminalCleanupEvidence:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_abort_result_invalid"
            )
        _transition(self, phase=_Phase.TERMINAL, terminal=terminal)
        return terminal

    def terminalize(
        self, *, pass_two_request: object | None = None
    ) -> Mem0OssTerminalCleanupEvidence | ManagedMem0V5CleanupReadbackWitness:
        """Reach terminal state; completed receipt flows also require fresh pass two."""

        state = _state(self)
        if state.phase is _Phase.ABORT_RETRY:
            return self.retry_abort()
        if state.phase in {_Phase.ADMITTED, _Phase.SEALED, _Phase.COVERED}:
            return self.abort()
        if state.phase is _Phase.RECEIPTS:
            if not state.receipts_consumed or len(state.receipts) != len(state.corpus_ids):
                return self.abort()
            if pass_two_request is None:
                raise ManagedMem0V5LifecycleAdapterError(
                    "managed_mem0_v5_lifecycle_cleanup_pass_two_request_missing"
                )
            self.cleanup_pass1()
            return self.cleanup_pass2(request=pass_two_request)
        if state.phase is _Phase.CLEANUP_RETRY:
            if pass_two_request is None:
                self._fail("cleanup_pass_two_request_missing")
            self.cleanup_pass1()
            return self.cleanup_pass2(request=pass_two_request)
        if state.phase is _Phase.TERMINAL:
            if state.terminal is None:
                self._fail("terminal_invalid")
            if state.terminal.terminal_state == "deleted":
                if pass_two_request is None:
                    self._fail("cleanup_pass_two_request_missing")
                return self.cleanup_pass2(request=pass_two_request)
            return state.terminal
        self._fail("terminalize_invalid")

    def issue_ready_clean_state_claim(self) -> ManagedMem0V5ReadyCleanStateClaim:
        """Expose low-level opaque claim material, never its verifier."""

        with _LOCK:
            state = _state_locked(self)
            return _consume_ready_clean_state_claim_locked(self, state)

    def _consume_ready_execution_material_for_adapter(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        cases: tuple[ManagedRunCase, ...],
    ) -> _ManagedMem0V5ExecutionEvidenceHandoff:
        """Atomically consume exact run material for the high-level evidence adapter."""

        with _LOCK:
            state = _state_locked(self)
            if (
                composition_binding is not state.binding
                or not _cases_match_authority(cases, state)
                or not _execution_material_is_ready(state)
            ):
                self._fail("execution_evidence_invalid")
            claim = _consume_ready_clean_state_claim_locked(self, state)
            coverage = state.coverage
            if coverage is None:  # guarded by the shared consume helper
                self._fail("execution_evidence_invalid")
            return _ManagedMem0V5ExecutionEvidenceHandoff(
                coverage,
                claim,
                state.corpus_ids,
            )

    def _validate_execution_cases_for_adapter(
        self,
        *,
        composition_binding: ManagedRunnerCompositionBinding,
        cases: tuple[ManagedRunCase, ...],
    ) -> tuple[str, ...]:
        """Read-only preflight repeated by the atomic handoff before consumption."""

        with _LOCK:
            state = _state_locked(self)
            if composition_binding is not state.binding or not _cases_match_authority(cases, state):
                self._fail("execution_evidence_cases_invalid")
            return state.corpus_ids

    def consume_transport_coverage(
        self, capability: ManagedTransportCoverageCapabilityPort
    ) -> VerifiedManagedTransportCoverage:
        state = _state(self)
        expected_benchmark = state.binding.profile.benchmark
        if (
            type(capability) is ManagedTransportCoverageCapability
            and capability._benchmark != expected_benchmark
        ):
            self._fail("coverage_benchmark_invalid")
        state = _begin(self, {_Phase.SEALED}, _Phase.COVERING, "coverage_invalid")
        try:
            coverage = state.paired_run.consume_transport_coverage(capability)
        except Exception:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_coverage_failed"
            ) from None
        if not _coverage_matches(coverage, state, expected_benchmark=expected_benchmark):
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError("managed_mem0_v5_lifecycle_coverage_invalid")
        _transition(self, phase=_Phase.COVERED, coverage=coverage)
        return coverage

    def issue_corpus_receipt(self, *, corpus_id: str) -> ManagedMem0V5CorpusIngestReceipt:
        state = _state(self)
        ordinal = len(state.receipts)
        if (
            state.phase not in {_Phase.COVERED, _Phase.RECEIPTS}
            or state.receipts_consumed
            or ordinal >= len(state.corpus_ids)
            or corpus_id != state.corpus_ids[ordinal]
            or state.coverage is None
            or state.coverage.benchmark != state.binding.profile.benchmark
        ):
            self._fail("receipt_invalid")
        state = _begin(
            self,
            {state.phase},
            _Phase.PROJECTING,
            "receipt_invalid",
        )
        try:
            evidence = state.paired_run.corpus_ingest_evidence(corpus_id=corpus_id)
            receipt = state.receipt_set.issue(evidence)
        except Exception:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_receipt_failed"
            ) from None
        _transition(
            self,
            phase=_Phase.RECEIPTS,
            receipts=(*state.receipts, receipt),
        )
        return receipt

    def consume_corpus_receipts(
        self, receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...]
    ) -> tuple[ManagedMem0V5CorpusIngestEvidence, ...]:
        state = _state(self)
        if (
            state.phase is not _Phase.RECEIPTS
            or state.receipts_consumed
            or len(state.receipts) != len(state.corpus_ids)
        ):
            self._fail("receipt_consume_invalid")
        state = _begin(self, {_Phase.RECEIPTS}, _Phase.CONSUMING, "receipt_consume_invalid")
        try:
            evidence = state.receipt_set.consume_exact_ordered(receipts)
        except Exception:
            _transition(self, phase=_Phase.RECEIPTS)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_receipt_consume_invalid"
            ) from None
        _transition(self, phase=_Phase.RECEIPTS, receipts_consumed=True)
        return evidence

    def cleanup_pass1(self) -> Mem0OssTerminalCleanupEvidence:
        state = _state(self)
        if state.phase is _Phase.RECEIPTS:
            if not state.receipts_consumed or len(state.receipts) != len(state.corpus_ids):
                self._fail("cleanup_invalid")
        elif state.phase is not _Phase.CLEANUP_RETRY:
            self._fail("cleanup_invalid")
        try:
            state.receipt_set.validate_consumed(state.receipts)
        except Exception:
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_receipt_snapshot_invalid"
            ) from None
        state = _begin(
            self,
            {state.phase},
            _Phase.CLEANING,
            "cleanup_invalid",
        )
        try:
            terminal = state.paired_run.cleanup()
        except Exception:
            _transition(self, phase=_Phase.CLEANUP_RETRY)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_cleanup_failed"
            ) from None
        if type(terminal) is not Mem0OssTerminalCleanupEvidence:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_cleanup_result_invalid"
            )
        _transition(self, phase=_Phase.TERMINAL, terminal=terminal)
        return terminal

    def cleanup_pass2(self, *, request: object) -> ManagedMem0V5CleanupReadbackWitness:
        current = _state(self)
        if current.phase is not _Phase.TERMINAL or current.terminal is None:
            self._fail("cleanup_pass_two_invalid")
        try:
            validate_managed_mem0_v5_cleanup_readback_authority(
                request=request,
                terminal=current.terminal,
            )
        except Exception:
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_cleanup_pass_two_invalid"
            ) from None
        state = _begin(self, {_Phase.TERMINAL}, _Phase.PASS_TWO, "cleanup_pass_two_invalid")
        if state.terminal is None:
            _transition(self, phase=_Phase.FAILED)
            self._fail("cleanup_pass_two_invalid")
        try:
            witness = state.paired_run.cleanup_readback(
                pass_index=2,
                capability=state.cleanup_readback,
                request=request,
            )
        except Exception:
            _transition(self, phase=_Phase.TERMINAL)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_cleanup_pass_two_failed"
            ) from None
        if type(witness) is not ManagedMem0V5CleanupReadbackWitness:
            _transition(self, phase=_Phase.FAILED)
            raise ManagedMem0V5LifecycleAdapterError(
                "managed_mem0_v5_lifecycle_cleanup_pass_two_result_invalid"
            )
        _transition(self, phase=_Phase.PASS_TWO_COMPLETE)
        return witness

    def _fail(self, suffix: str) -> NoReturn:
        raise ManagedMem0V5LifecycleAdapterError(f"managed_mem0_v5_lifecycle_{suffix}")

    def __repr__(self) -> str:
        return "ManagedMem0V5LifecycleAdapter(<opaque>)"


def _validate_composition(
    binding: object,
    paired_run: object,
    authority: object,
    request: object,
    cleanup_readback: object,
) -> tuple[tuple[str, ...], str]:
    if (
        type(binding) is not ManagedRunnerCompositionBinding
        or type(paired_run) is not ManagedMem0V5PairedRun
        or type(authority) is not ManagedMem0V5ManifestAuthority
        or type(request) is not Mem0OssAdmissionRequest
        or paired_run._authority is not authority
        or paired_run._request is not request
        or request.run_id != binding.run_id
        or request.expected_operation_count != authority.operation_count
        or not callable(getattr(cleanup_readback, "readback", None))
    ):
        raise ManagedMem0V5LifecycleAdapterError("managed_mem0_v5_lifecycle_composition_invalid")
    authority.__post_init__()
    corpus_ids = tuple(dict.fromkeys(item.corpus_id for item in authority.units))
    targets = tuple(
        item.target_identity_sha256
        for item in binding.backend_targets
        if item.backend_role == "mem0"
    )
    if not corpus_ids or len(targets) != 1:
        raise ManagedMem0V5LifecycleAdapterError("managed_mem0_v5_lifecycle_composition_invalid")
    return corpus_ids, targets[0]


def _coverage_matches(
    coverage: object,
    state: _LifecycleState,
    *,
    expected_benchmark: str,
) -> bool:
    try:
        authenticated = authenticate_managed_transport_coverage(coverage)
    except Exception:
        return False
    admission = Mem0OssFullRunAdmission(
        request=state.request,
        ingestion_manifest_sha256=state.authority.ingestion_manifest_sha256,
        ingestion_root_sha256=state.authority.ingestion_root_sha256,
        ingestion_unit_count=state.authority.operation_count,
    )
    return (
        authenticated is coverage
        and authenticated.benchmark == expected_benchmark
        and authenticated.backend_role == "mem0"
        and authenticated.run_id_sha256 == hashlib.sha256(state.binding.run_id.encode()).hexdigest()
        and authenticated.authority_commitment_sha256 == state.authority.authority_commitment_sha256
        and authenticated.admission_commitment_sha256 == admission.commitment_sha256
    )


def _cases_match_authority(cases: object, state: _LifecycleState) -> bool:
    try:
        if (
            type(cases) is not tuple
            or not cases
            or any(type(item) is not ManagedRunCase for item in cases)
            or len({item.case_id for item in cases}) != len(cases)
            or tuple(dict.fromkeys(item.corpus_id for item in cases)) != state.corpus_ids
        ):
            return False
        projected = ManagedMem0V5ManifestProjector().project(
            cases,
            current_date=state.authority.current_date,
        )
        return projected == state.authority
    except Exception:
        return False


def _consume_ready_clean_state_claim_locked(
    adapter: ManagedMem0V5LifecycleAdapter,
    state: _LifecycleState,
) -> ManagedMem0V5ReadyCleanStateClaim:
    if state.execution_evidence_consumed:
        adapter._fail("execution_evidence_invalid")
    _store_locked(
        adapter,
        replace(
            state,
            execution_evidence_consumed=True,
            integrity_mac=b"",
        ),
    )
    try:
        claim = state.paired_run.issue_ready_clean_state_claim()
    except Exception:
        raise ManagedMem0V5LifecycleAdapterError(
            "managed_mem0_v5_lifecycle_execution_evidence_failed"
        ) from None
    if type(claim) is not ManagedMem0V5ReadyCleanStateClaim:
        raise ManagedMem0V5LifecycleAdapterError(
            "managed_mem0_v5_lifecycle_execution_evidence_result_invalid"
        )
    return claim


def _execution_material_is_ready(state: _LifecycleState) -> bool:
    try:
        valid = (
            state.phase is _Phase.RECEIPTS
            and not state.execution_evidence_consumed
            and state.receipts_consumed
            and len(state.receipts) == len(state.corpus_ids)
            and state.coverage is not None
            and _coverage_matches(
                state.coverage,
                state,
                expected_benchmark=state.binding.profile.benchmark,
            )
        )
        if valid:
            state.receipt_set.validate_consumed(state.receipts)
        return valid
    except Exception:
        return False


def _finish_abort_outcome(adapter: ManagedMem0V5LifecycleAdapter) -> None:
    state = _state(adapter)
    try:
        terminal = state.paired_run.completed_terminal_evidence
    except Exception:
        if state.paired_run.abort_retry_required:
            _transition(adapter, phase=_Phase.ABORT_RETRY)
        else:
            _transition(adapter, phase=_Phase.FAILED)
    else:
        _transition(adapter, phase=_Phase.TERMINAL, terminal=terminal)


def _begin(
    adapter: ManagedMem0V5LifecycleAdapter,
    allowed: set[_Phase],
    phase: _Phase,
    error_suffix: str,
) -> _LifecycleState:
    with _LOCK:
        state = _state_locked(adapter)
        if state.phase not in allowed:
            adapter._fail(error_suffix)
        next_state = replace(state, phase=phase, integrity_mac=b"")
        _store_locked(adapter, next_state)
        return _STATES[adapter]


def _transition(
    adapter: ManagedMem0V5LifecycleAdapter,
    *,
    phase: _Phase,
    coverage: VerifiedManagedTransportCoverage | None | object = ...,
    receipts: tuple[ManagedMem0V5CorpusIngestReceipt, ...] | object = ...,
    receipts_consumed: bool | object = ...,
    execution_evidence_consumed: bool | object = ...,
    terminal: Mem0OssTerminalCleanupEvidence | None | object = ...,
) -> _LifecycleState:
    with _LOCK:
        current = _state_locked(adapter)
        next_state = replace(
            current,
            phase=phase,
            coverage=current.coverage if coverage is ... else coverage,
            receipts=current.receipts if receipts is ... else receipts,
            receipts_consumed=(
                current.receipts_consumed if receipts_consumed is ... else receipts_consumed
            ),
            execution_evidence_consumed=(
                current.execution_evidence_consumed
                if execution_evidence_consumed is ...
                else execution_evidence_consumed
            ),
            terminal=current.terminal if terminal is ... else terminal,
            integrity_mac=b"",
        )
        _store_locked(adapter, next_state)
        return _STATES[adapter]


def _state(value: object) -> _LifecycleState:
    if type(value) is not ManagedMem0V5LifecycleAdapter:
        raise ManagedMem0V5LifecycleAdapterError("managed_mem0_v5_lifecycle_composition_invalid")
    with _LOCK:
        return _state_locked(value)


def _state_locked(adapter: ManagedMem0V5LifecycleAdapter) -> _LifecycleState:
    state = _STATES.get(adapter)
    try:
        valid_mac = state is not None and hmac.compare_digest(
            state.integrity_mac,
            _state_mac(adapter, replace(state, integrity_mac=b"")),
        )
    except Exception:
        valid_mac = False
    if not valid_mac or state is None:
        raise ManagedMem0V5LifecycleAdapterError("managed_mem0_v5_lifecycle_composition_invalid")
    _validate_composition(
        state.binding,
        state.paired_run,
        state.authority,
        state.request,
        state.cleanup_readback,
    )
    _validate_dynamic(state)
    return state


def _validate_dynamic(state: _LifecycleState) -> None:
    if (
        type(state.phase) is not _Phase  # noqa: E721 - exact lifecycle state required
        or type(state.receipts) is not tuple  # noqa: E721 - exact lifecycle state required
        or len(state.receipts) > len(state.corpus_ids)
        or any(type(item) is not ManagedMem0V5CorpusIngestReceipt for item in state.receipts)
        or type(state.receipts_consumed) is not bool  # noqa: E721 - exact state flag required
        or type(state.execution_evidence_consumed) is not bool  # noqa: E721
        or (state.receipts_consumed and len(state.receipts) != len(state.corpus_ids))
        or (
            state.coverage is not None
            and not _coverage_matches(
                state.coverage,
                state,
                expected_benchmark=state.binding.profile.benchmark,
            )
        )
        or (
            state.terminal is not None
            and type(state.terminal) is not Mem0OssTerminalCleanupEvidence
        )
    ):
        raise ManagedMem0V5LifecycleAdapterError("managed_mem0_v5_lifecycle_composition_invalid")


def _store(adapter: ManagedMem0V5LifecycleAdapter, state: _LifecycleState) -> None:
    with _LOCK:
        _store_locked(adapter, state)


def _store_locked(adapter: ManagedMem0V5LifecycleAdapter, state: _LifecycleState) -> None:
    unsigned = replace(state, integrity_mac=b"")
    _validate_dynamic(unsigned)
    _STATES[adapter] = replace(
        unsigned,
        integrity_mac=_state_mac(adapter, unsigned),
    )


def _state_mac(adapter: ManagedMem0V5LifecycleAdapter, state: _LifecycleState) -> bytes:
    payload = {
        "adapter_identity": id(adapter),
        "binding_identity": id(state.binding),
        "paired_run_identity": id(state.paired_run),
        "paired_run_fingerprint_sha256": managed_mem0_v5_paired_run_fingerprint(state.paired_run),
        "authority_identity": id(state.authority),
        "request_identity": id(state.request),
        "cleanup_readback_identity": id(state.cleanup_readback),
        "receipt_set_identity": id(state.receipt_set),
        "corpus_ids": state.corpus_ids,
        "mem0_target_identity_sha256": state.mem0_target_identity_sha256,
        "phase": state.phase.value,
        "coverage_identity": None if state.coverage is None else id(state.coverage),
        "coverage_commitment": (
            None if state.coverage is None else state.coverage.evidence_commitment_sha256
        ),
        "receipt_identities": tuple(id(item) for item in state.receipts),
        "receipts_consumed": state.receipts_consumed,
        "execution_evidence_consumed": state.execution_evidence_consumed,
        "terminal_identity": None if state.terminal is None else id(state.terminal),
        "terminal_commitment": (
            None if state.terminal is None else state.terminal.commitment_sha256
        ),
    }
    return hmac.new(
        _SECRET,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).digest()


_STATES = weakref.WeakKeyDictionary()


__all__ = (
    "ManagedMem0V5LifecycleAdapter",
    "ManagedMem0V5LifecycleAdapterError",
)
