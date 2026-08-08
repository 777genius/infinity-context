"""Provider-free public preparation for one exact managed-v5 live run."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    preflight_managed_mem0_v5_clean_state_request,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5StatePaths,
    preflight_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_authority import (
    ManagedMem0V5ProductionAuthority,
    inspect_managed_mem0_v5_production_authority,
    issue_managed_mem0_v5_production_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    _inspect_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5TransportPort
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationManifest,
)

_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)
_OPERATION_KIND = "managed_mem0_v5_extraction"


@final
class ManagedV5PublicRunPreparation:
    """Opaque, process-local authority produced before any credential loading."""

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "ManagedV5PublicRunPreparation(<sealed-one-shot>)"

    def __copy__(self) -> object:
        raise TypeError("managed v5 public preparation is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed v5 public preparation is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed v5 public preparation is nonserializable")


@dataclass(frozen=True, slots=True)
class _PublicPreparationState:
    cases: tuple[ManagedRunCase, ...] = field(repr=False)
    request: Mem0OssAdmissionRequest = field(repr=False)
    composition_binding: ManagedRunnerCompositionBinding = field(repr=False)
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority = field(repr=False)
    manifest_authority: ManagedMem0V5ManifestAuthority = field(repr=False)
    operation_manifest: OperationManifest = field(repr=False)
    production_authority: ManagedMem0V5ProductionAuthority = field(repr=False)
    deadline: datetime
    integrity_mac: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _ActivatedManagedV5PublicRun:
    preparation_identity: int
    preparation_commitment: str
    cases: tuple[ManagedRunCase, ...]
    request: Mem0OssAdmissionRequest
    composition_binding: ManagedRunnerCompositionBinding
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority
    manifest_authority: ManagedMem0V5ManifestAuthority
    operation_manifest: OperationManifest
    production_authority: ManagedMem0V5ProductionAuthority
    plan: VerifiedManagedRunPlan
    integrity_mac: bytes = field(repr=False)


_STATES: weakref.WeakKeyDictionary[ManagedV5PublicRunPreparation, _PublicPreparationState] = (
    weakref.WeakKeyDictionary()
)


def prepare_managed_v5_public_run(
    *,
    cases: tuple[ManagedRunCase, ...],
    current_date: str,
    request: Mem0OssAdmissionRequest,
    composition_binding: ManagedRunnerCompositionBinding,
    origin: str,
    timeout_seconds: float,
    state_paths: ManagedMem0V5StatePaths,
    credential_paths: ManagedMem0V5CredentialPaths,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
    transport: Mem0V5TransportPort | None = None,
) -> ManagedV5PublicRunPreparation:
    """Complete exact public authority and local preflight before secret access.

    This function performs no network I/O, readiness probe, registry operation or
    credential-file read. In particular it never composes the Mem0 runtime lane.
    """

    _require_nominal_inputs(cases, request, composition_binding, receipt_authority)
    preflight = preflight_managed_mem0_v5(
        cases=cases,
        current_date=current_date,
        request=request,
        origin=origin,
        timeout_seconds=timeout_seconds,
        state_paths=state_paths,
        credential_paths=credential_paths,
        runtime_receipt_boundary=runtime_receipt_boundary,
        trusted_runtime_binding=trusted_runtime_binding,
        receipt_authority=receipt_authority,
        dispatch_guard=dispatch_guard,
        transport=transport,
    )
    preflight_managed_mem0_v5_clean_state_request(
        authority=preflight.authority,
        admission=preflight.admission,
    )
    operation_manifest = _operation_manifest(
        request=request,
        authority=preflight.authority,
        receipt_authority=receipt_authority,
    )
    production_authority = issue_managed_mem0_v5_production_authority(
        cases=cases,
        current_date=current_date,
        request=request,
        composition_binding=composition_binding,
        origin=origin,
        timeout_seconds=timeout_seconds,
        state_paths=state_paths,
        credential_paths=credential_paths,
        runtime_receipt_boundary=runtime_receipt_boundary,
        trusted_runtime_binding=trusted_runtime_binding,
        receipt_authority=receipt_authority,
        operation_manifest=operation_manifest,
        dispatch_guard=dispatch_guard,
        transport=transport,
    )
    preparation = ManagedV5PublicRunPreparation()
    state = _PublicPreparationState(
        cases,
        request,
        composition_binding,
        receipt_authority,
        preflight.authority,
        operation_manifest,
        production_authority,
        composition_binding.deadline,
        b"",
    )
    state = _with_mac(preparation, state)
    with _LOCK:
        _STATES[preparation] = state
    return preparation


def _activate_managed_v5_public_run(
    preparation: ManagedV5PublicRunPreparation,
    *,
    cases: tuple[ManagedRunCase, ...],
    request: Mem0OssAdmissionRequest,
    composition_binding: ManagedRunnerCompositionBinding,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    production_authority: ManagedMem0V5ProductionAuthority,
    plan: VerifiedManagedRunPlan,
    now: datetime,
) -> _ActivatedManagedV5PublicRun:
    """Atomically consume after readiness and bind the exact resulting plan."""

    with _LOCK:
        state = _state_locked(preparation)
        # Burn before validating caller-supplied activation material. An invalid or
        # ambiguous activation is terminal and cannot be retried with a new tuple.
        del _STATES[preparation]
        try:
            trusted_now = _aware(now)
            plan_state = _inspect_verified_managed_run_plan(plan)
            targets = tuple(
                (item.backend_role, item.target_identity_sha256)
                for item in composition_binding.backend_targets
            )
            plan_targets = tuple(
                (item.backend_role, item.target_identity_sha256)
                for item in plan_state.backend_targets
            )
            if (
                cases is not state.cases
                or request is not state.request
                or composition_binding is not state.composition_binding
                or receipt_authority is not state.receipt_authority
                or production_authority is not state.production_authority
                or trusted_now >= state.deadline
                or composition_binding.deadline != state.deadline
                or plan_state.run_id != request.run_id
                or plan_state.cases != cases
                or plan_targets != targets
            ):
                raise TypeError
            descriptor = inspect_managed_mem0_v5_production_authority(production_authority)
            if (
                descriptor.binding_commitment_sha256
                != composition_binding.binding_commitment_sha256
                or descriptor.ingestion_manifest_sha256
                != state.manifest_authority.ingestion_manifest_sha256
                or descriptor.operation_root_sha256 != state.operation_manifest.commitment_sha256
            ):
                raise TypeError
        except Exception:
            raise ManagedRunError("managed v5 public preparation activation invalid") from None
        activated = _ActivatedManagedV5PublicRun(
            id(preparation),
            state.integrity_mac.hex(),
            state.cases,
            state.request,
            state.composition_binding,
            state.receipt_authority,
            state.manifest_authority,
            state.operation_manifest,
            state.production_authority,
            plan,
            b"",
        )
        return replace(activated, integrity_mac=_activated_mac(activated))


def _authenticate_activated_managed_v5_public_run(
    value: object,
) -> _ActivatedManagedV5PublicRun:
    """Authenticate the exact post-readiness capability without consuming it."""

    if type(value) is not _ActivatedManagedV5PublicRun:
        raise ManagedRunError("managed v5 public preparation activation invalid")
    try:
        if not hmac.compare_digest(
            value.integrity_mac,
            _activated_mac(replace(value, integrity_mac=b"")),
        ):
            raise TypeError
        plan = _inspect_verified_managed_run_plan(value.plan)
        descriptor = inspect_managed_mem0_v5_production_authority(value.production_authority)
        if (
            plan.run_id != value.request.run_id
            or plan.cases != value.cases
            or value.composition_binding.run_id != value.request.run_id
            or descriptor.binding_commitment_sha256
            != value.composition_binding.binding_commitment_sha256
        ):
            raise TypeError
    except Exception:
        raise ManagedRunError("managed v5 public preparation activation invalid") from None
    return value


def _authenticate_managed_v5_public_run_preparation(
    value: object,
) -> _PublicPreparationState:
    """Authenticate the exact unconsumed public capability without consuming it."""

    with _LOCK:
        return _state_locked(value)


def _operation_manifest(
    *,
    request: Mem0OssAdmissionRequest,
    authority: ManagedMem0V5ManifestAuthority,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
) -> OperationManifest:
    operations = tuple(
        LogicalOperationIdentity(
            run_id=request.run_id,
            operation_key=item.operation_id_sha256,
            operation_kind=_OPERATION_KIND,
            ordinal=index,
            authority_commitment_sha256=authority.authority_commitment_sha256,
        )
        for index, item in enumerate(receipt_authority.operations)
    )
    return OperationManifest(operations)


def _require_nominal_inputs(
    cases: object,
    request: object,
    binding: object,
    receipt_authority: object,
) -> None:
    if (
        type(cases) is not tuple
        or not cases
        or any(type(item) is not ManagedRunCase for item in cases)
        or type(request) is not Mem0OssAdmissionRequest
        or type(binding) is not ManagedRunnerCompositionBinding
        or type(receipt_authority) is not Mem0V5ObservedExtractionReceiptAuthority
        or binding.run_id != request.run_id
        or binding.deadline.tzinfo is None
        or binding.deadline.utcoffset() is None
    ):
        raise ManagedRunError("managed v5 public preparation input invalid")


def _state_locked(preparation: object) -> _PublicPreparationState:
    if type(preparation) is not ManagedV5PublicRunPreparation:
        raise ManagedRunError("managed v5 public preparation unavailable")
    state = _STATES.get(preparation)
    if state is None or not hmac.compare_digest(
        state.integrity_mac, _state_mac(preparation, state)
    ):
        raise ManagedRunError("managed v5 public preparation unavailable")
    return state


def _with_mac(
    preparation: ManagedV5PublicRunPreparation,
    state: _PublicPreparationState,
) -> _PublicPreparationState:
    return _PublicPreparationState(
        state.cases,
        state.request,
        state.composition_binding,
        state.receipt_authority,
        state.manifest_authority,
        state.operation_manifest,
        state.production_authority,
        state.deadline,
        _state_mac(preparation, state),
    )


def _state_mac(
    preparation: ManagedV5PublicRunPreparation,
    state: _PublicPreparationState,
) -> bytes:
    descriptor = inspect_managed_mem0_v5_production_authority(state.production_authority)
    payload = json.dumps(
        {
            "preparation_identity": id(preparation),
            "cases_identity": id(state.cases),
            "case_identities": [id(item) for item in state.cases],
            "request_identity": id(state.request),
            "binding_identity": id(state.composition_binding),
            "receipt_authority_identity": id(state.receipt_authority),
            "production_authority_identity": id(state.production_authority),
            "manifest": state.manifest_authority.authority_commitment_sha256,
            "operations": state.operation_manifest.commitment_sha256,
            "production": descriptor.authority_commitment_sha256,
            "deadline": state.deadline.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_SECRET, payload, hashlib.sha256).digest()


def _activated_mac(value: _ActivatedManagedV5PublicRun) -> bytes:
    descriptor = inspect_managed_mem0_v5_production_authority(value.production_authority)
    payload = json.dumps(
        {
            "preparation_identity": value.preparation_identity,
            "preparation_commitment": value.preparation_commitment,
            "cases_identity": id(value.cases),
            "case_identities": [id(item) for item in value.cases],
            "request_identity": id(value.request),
            "binding_identity": id(value.composition_binding),
            "receipt_authority_identity": id(value.receipt_authority),
            "manifest_identity": id(value.manifest_authority),
            "operation_manifest_identity": id(value.operation_manifest),
            "production_authority_identity": id(value.production_authority),
            "plan_identity": id(value.plan),
            "run_id": value.request.run_id,
            "deadline": value.composition_binding.deadline.isoformat(),
            "production": descriptor.authority_commitment_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_SECRET, payload, hashlib.sha256).digest()


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError
    return value


__all__ = ("ManagedV5PublicRunPreparation", "prepare_managed_v5_public_run")
