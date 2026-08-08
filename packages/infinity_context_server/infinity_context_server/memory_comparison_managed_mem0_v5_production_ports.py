"""Narrow v5 cutover reset/ingest components over Infinity and PR45 lifecycles."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_profiles import INFINITY_COMPARISON_BACKEND
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    ManagedInfinityHttpLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5PairedRuntimeBundle,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_pending_receipts import (
    ManagedMem0V5PendingIngestReceipt,
    ManagedMem0V5PendingReceiptSet,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)

MANAGED_V5_CUTOVER_RESET_ADAPTER_ID = "managed-v5-cutover-reset-v1"
MANAGED_V5_CUTOVER_INGEST_ADAPTER_ID = "managed-v5-cutover-ingest-v1"


class ManagedV5CutoverProductionPortError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class _Coordinator:
    binding: ManagedRunnerCompositionBinding
    cases: tuple[ManagedRunCase, ...]
    infinity: ManagedInfinityHttpLifecycleAdapter
    mem0: ManagedMem0V5ProductionLifecycleAdapter
    bundle: ManagedMem0V5PairedRuntimeBundle
    pending: ManagedMem0V5PendingReceiptSet
    lock: threading.RLock
    phase: str = "new"
    next_ingest: int = 0

    @property
    def target_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (item.backend_role, item.target_identity_sha256)
            for item in self.binding.backend_targets
        )

    @property
    def expected(self) -> tuple[tuple[str, str, ManagedRunCase], ...]:
        return tuple(
            (role, target, case) for role, target in self.target_pairs for case in self.cases
        )


@final
class ManagedV5CutoverResetPort:
    __slots__ = ("_state",)

    def __init__(self, state: _Coordinator) -> None:
        self._state = state

    @property
    def adapter_id(self) -> str:
        return MANAGED_V5_CUTOVER_RESET_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return _implementation(self.adapter_id)

    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        state = self._state
        with state.lock:
            if (
                state.phase != "new"
                or run_id != state.binding.run_id
                or binding_commitment_sha256 != state.binding.binding_commitment_sha256
                or backend_targets != state.target_pairs
            ):
                state.phase = "cleanup_only"
                _fail("managed_v5_cutover_reset_invalid")
            state.phase = "resetting"
        try:
            state.infinity.reset(
                run_id=run_id,
                binding_commitment_sha256=binding_commitment_sha256,
                backend_targets=backend_targets,
            )
            state.mem0.admit_or_restore()
        except Exception:
            with state.lock:
                state.phase = "cleanup_only"
            _fail("managed_v5_cutover_reset_failed")
        with state.lock:
            if state.phase != "resetting":
                state.phase = "cleanup_only"
                _fail("managed_v5_cutover_reset_concurrent")
            state.phase = "ready"


@final
class ManagedV5CutoverIngestPort:
    __slots__ = ("_state",)

    def __init__(self, state: _Coordinator) -> None:
        self._state = state

    @property
    def adapter_id(self) -> str:
        return MANAGED_V5_CUTOVER_INGEST_ADAPTER_ID

    @property
    def composition_binding(self) -> ManagedRunnerCompositionBinding:
        """Expose only the exact immutable owner binding for composition checks."""

        return self._state.binding

    @property
    def implementation_sha256(self) -> str:
        return _implementation(self.adapter_id)

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> object:
        state = self._state
        with state.lock:
            ordinal = state.next_ingest
            expected = state.expected
            if state.phase != "ready" or ordinal >= len(expected):
                _fail("managed_v5_cutover_ingest_phase_invalid")
            role, target, case = expected[ordinal]
            if (
                run_id != state.binding.run_id
                or backend_role != role
                or target_identity_sha256 != target
                or type(record) is not dict
                or not _records_match(record, case.record)
            ):
                state.phase = "cleanup_only"
                _fail("managed_v5_cutover_ingest_binding_invalid")
            is_mem0 = role == "mem0"
            is_final = ordinal == len(expected) - 1
            try:
                pending = state.pending.reserve(corpus_id=case.corpus_id) if is_mem0 else None
            except Exception:
                state.phase = "cleanup_only"
                _fail("managed_v5_cutover_pending_receipts_invalid")
            state.phase = "dispatching" if is_mem0 and is_final else "ingesting"
        try:
            if role == INFINITY_COMPARISON_BACKEND:
                result = state.infinity.ingest(
                    run_id=run_id,
                    backend_role=backend_role,
                    target_identity_sha256=target_identity_sha256,
                    record=record,
                )
            elif role == "mem0":
                if pending is None:
                    raise TypeError
                result = pending
                if is_final:
                    state.mem0.dispatch_once()
                    coverage = state.bundle.issue_transport_coverage(
                        benchmark=state.binding.profile.benchmark,
                    )
                    state.mem0.consume_transport_coverage(coverage)
                    receipts = tuple(
                        state.mem0.issue_corpus_receipt(corpus_id=item.corpus_id)
                        for item in state.cases
                    )
                    handles = state.pending.reserved_handles()
                    if not handles or handles[-1] is not pending:
                        raise TypeError
                    state.pending.bind_exact_ordered(handles=handles, receipts=receipts)
            else:
                raise TypeError
        except Exception:
            with state.lock:
                state.phase = "cleanup_only"
            state.pending.terminalize()
            _fail(
                "managed_v5_cutover_dispatch_ambiguous"
                if is_mem0 and is_final
                else "managed_v5_cutover_ingest_failed"
            )
        with state.lock:
            expected_phase = "dispatching" if is_mem0 and is_final else "ingesting"
            if state.phase != expected_phase or state.next_ingest != ordinal:
                state.phase = "cleanup_only"
                _fail("managed_v5_cutover_ingest_concurrent")
            state.next_ingest += 1
            state.phase = "complete" if state.next_ingest == len(expected) else "ready"
        return result

    def consume_exact_mem0_receipts(
        self, handles: tuple[ManagedMem0V5PendingIngestReceipt, ...]
    ) -> tuple[object, ...]:
        return self._state.pending.consume_exact_ordered(handles)

    def terminalize_mem0(self, *, pass_two_request: object | None = None) -> object:
        state = self._state
        with state.lock:
            if state.phase not in {"cleanup_only", "complete"}:
                _fail("managed_v5_cutover_terminalize_invalid")
            state.phase = "terminalizing"
        try:
            result = state.mem0.terminalize(pass_two_request=pass_two_request)
        except Exception:
            with state.lock:
                state.phase = "cleanup_only"
            raise
        with state.lock:
            state.phase = "terminal"
        return result


@final
@dataclass(frozen=True, slots=True)
class ManagedV5CutoverLifecyclePorts:
    reset: ManagedV5CutoverResetPort
    ingest: ManagedV5CutoverIngestPort


def create_managed_v5_cutover_lifecycle_ports(
    *,
    composition_binding: ManagedRunnerCompositionBinding,
    cases: tuple[ManagedRunCase, ...],
    infinity_lifecycle: ManagedInfinityHttpLifecycleAdapter,
    mem0_lifecycle: ManagedMem0V5ProductionLifecycleAdapter,
    paired_runtime_bundle: ManagedMem0V5PairedRuntimeBundle,
) -> ManagedV5CutoverLifecyclePorts:
    corpora = _unique_corpora(cases)
    if (
        type(composition_binding) is not ManagedRunnerCompositionBinding
        or type(infinity_lifecycle) is not ManagedInfinityHttpLifecycleAdapter
        or infinity_lifecycle.composition_binding is not composition_binding
        or type(mem0_lifecycle) is not ManagedMem0V5ProductionLifecycleAdapter
        or mem0_lifecycle.composition_binding is not composition_binding
        or type(paired_runtime_bundle) is not ManagedMem0V5PairedRuntimeBundle
        or tuple(item.backend_role for item in composition_binding.backend_targets)
        != (INFINITY_COMPARISON_BACKEND, "mem0")
    ):
        _fail("managed_v5_cutover_composition_invalid")
    state = _Coordinator(
        composition_binding,
        corpora,
        infinity_lifecycle,
        mem0_lifecycle,
        paired_runtime_bundle,
        ManagedMem0V5PendingReceiptSet(
            corpus_ids=tuple(item.corpus_id for item in corpora),
            production_lifecycle=mem0_lifecycle,
        ),
        threading.RLock(),
    )
    return ManagedV5CutoverLifecyclePorts(
        ManagedV5CutoverResetPort(state),
        ManagedV5CutoverIngestPort(state),
    )


def _unique_corpora(cases: object) -> tuple[ManagedRunCase, ...]:
    if type(cases) is not tuple or not cases or any(type(x) is not ManagedRunCase for x in cases):
        _fail("managed_v5_cutover_cases_invalid")
    seen: dict[str, ManagedRunCase] = {}
    for case in cases:
        previous = seen.get(case.corpus_id)
        if previous is None:
            seen[case.corpus_id] = case
        elif not _records_match(previous.record, case.record):
            _fail("managed_v5_cutover_cases_invalid")
    return tuple(seen.values())


def _records_match(left: object, right: object) -> bool:
    try:
        return _canonical(left) == _canonical(right)
    except Exception:
        return False


def _canonical(value: object) -> bytes:
    return json.dumps(
        _plain_json(value), allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_plain_json(item) for item in value]
    return value


def _implementation(adapter_id: str) -> str:
    return hashlib.sha256(f"{adapter_id}\0exact-target-major\0no-redispatch".encode()).hexdigest()


def _fail(code: str) -> None:
    raise ManagedV5CutoverProductionPortError(code)


__all__ = (
    "ManagedV5CutoverIngestPort",
    "ManagedV5CutoverLifecyclePorts",
    "ManagedV5CutoverProductionPortError",
    "ManagedV5CutoverResetPort",
    "create_managed_v5_cutover_lifecycle_ports",
)
