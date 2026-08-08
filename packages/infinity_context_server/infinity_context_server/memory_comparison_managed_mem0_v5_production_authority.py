"""Secret-free one-shot authority for the managed Mem0 v5 production lane."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, replace
from typing import NoReturn, final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5Composition,
    ManagedMem0V5Preflight,
    ManagedMem0V5StatePaths,
    preflight_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import Mem0V5TransportPort
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OperationManifest,
    RetryDisposition,
)

_OPERATION_KIND = "managed_mem0_v5_extraction"
_LOCK = threading.RLock()
_SECRET = secrets.token_bytes(32)


class ManagedMem0V5ProductionAuthorityError(RuntimeError):
    """Fixed-code authority failure without caller or credential material."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5ProductionAuthorityDescriptor:
    """Secret-free commitments for one exact production execution."""

    run_id_sha256: str
    binding_commitment_sha256: str
    target_identity_sha256: str
    origin_sha256: str
    ingestion_manifest_sha256: str
    admission_commitment_sha256: str
    phase_c_runtime_source_sha256: str
    route_sha256: str
    credential_binding_sha256: str
    operation_root_sha256: str
    operation_count: int
    deadline: str
    authority_commitment_sha256: str


@dataclass(frozen=True, slots=True)
class _AuthorityState:
    descriptor: ManagedMem0V5ProductionAuthorityDescriptor
    preflight: ManagedMem0V5Preflight
    binding: ManagedRunnerCompositionBinding
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority
    operation_manifest: OperationManifest
    origin: str
    consumed: bool
    integrity_mac: bytes


_STATES: weakref.WeakKeyDictionary[ManagedMem0V5ProductionAuthority, _AuthorityState]


@final
class ManagedMem0V5ProductionAuthority:
    """Opaque, process-local and atomically single-consume authority."""

    __slots__ = ("__weakref__",)

    def __repr__(self) -> str:
        return "ManagedMem0V5ProductionAuthority(<redacted>)"

    def __copy__(self) -> object:
        raise TypeError("managed Mem0 v5 production authority is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed Mem0 v5 production authority is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 production authority is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed Mem0 v5 production authority is nonserializable")


def issue_managed_mem0_v5_production_authority(
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
    operation_manifest: OperationManifest,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
    transport: Mem0V5TransportPort | None = None,
) -> ManagedMem0V5ProductionAuthority:
    """Bind public preflight output to one exact production operation inventory."""

    try:
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
    except Exception:
        _fail("preflight_invalid")
    normalized_origin = _validated_origin(origin)
    _validate_inputs(
        preflight=preflight,
        binding=composition_binding,
        receipt_authority=receipt_authority,
        operation_manifest=operation_manifest,
    )
    request = preflight.admission.request
    target = next(
        item.target_identity_sha256
        for item in composition_binding.backend_targets
        if item.backend_role == "mem0"
    )
    public = {
        "run_id_sha256": hashlib.sha256(request.run_id.encode()).hexdigest(),
        "binding_commitment_sha256": composition_binding.binding_commitment_sha256,
        "target_identity_sha256": target,
        "origin_sha256": hashlib.sha256(normalized_origin.encode()).hexdigest(),
        "ingestion_manifest_sha256": preflight.authority.ingestion_manifest_sha256,
        "admission_commitment_sha256": preflight.admission.commitment_sha256,
        "phase_c_runtime_source_sha256": receipt_authority.runtime_source_sha256,
        "route_sha256": request.route_sha256,
        "credential_binding_sha256": request.credential_binding_sha256,
        "operation_root_sha256": operation_manifest.commitment_sha256,
        "operation_count": len(operation_manifest.operations),
        "deadline": composition_binding.deadline.isoformat(),
    }
    descriptor = ManagedMem0V5ProductionAuthorityDescriptor(
        **public,
        authority_commitment_sha256=canonical_sha256(public),
    )
    authority = ManagedMem0V5ProductionAuthority()
    state = _AuthorityState(
        descriptor,
        preflight,
        composition_binding,
        receipt_authority,
        operation_manifest,
        normalized_origin,
        False,
        b"",
    )
    _store(authority, state)
    return authority


def inspect_managed_mem0_v5_production_authority(
    authority: ManagedMem0V5ProductionAuthority,
) -> ManagedMem0V5ProductionAuthorityDescriptor:
    """Return only the immutable, secret-free production descriptor."""

    return _state(authority).descriptor


def _consume_managed_mem0_v5_production_authority(
    authority: ManagedMem0V5ProductionAuthority,
    *,
    composition: ManagedMem0V5Composition,
    composition_binding: ManagedRunnerCompositionBinding,
    origin: str,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    operation_manifest: OperationManifest,
) -> ManagedMem0V5ProductionAuthorityDescriptor:
    """Atomically consume only for the exact object-bound public preflight tuple."""

    with _LOCK:
        state = _authenticate_exact_tuple_locked(
            authority,
            composition=composition,
            composition_binding=composition_binding,
            origin=origin,
            receipt_authority=receipt_authority,
            operation_manifest=operation_manifest,
        )
        _store_locked(authority, replace(state, consumed=True, integrity_mac=b""))
        return state.descriptor


def _authenticate_managed_mem0_v5_production_authority(
    authority: ManagedMem0V5ProductionAuthority,
    *,
    composition: ManagedMem0V5Composition,
    composition_binding: ManagedRunnerCompositionBinding,
    origin: str,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    operation_manifest: OperationManifest,
) -> ManagedMem0V5ProductionAuthorityDescriptor:
    """Authenticate the exact tuple without spending its one-shot authority."""

    with _LOCK:
        return _authenticate_exact_tuple_locked(
            authority,
            composition=composition,
            composition_binding=composition_binding,
            origin=origin,
            receipt_authority=receipt_authority,
            operation_manifest=operation_manifest,
        ).descriptor


def _authenticate_exact_tuple_locked(
    authority: ManagedMem0V5ProductionAuthority,
    *,
    composition: ManagedMem0V5Composition,
    composition_binding: ManagedRunnerCompositionBinding,
    origin: str,
    receipt_authority: Mem0V5ObservedExtractionReceiptAuthority,
    operation_manifest: OperationManifest,
) -> _AuthorityState:
    try:
        normalized_origin = _validated_origin(origin)
    except Exception:
        _fail("consume_invalid")
    state = _state_locked(authority)
    try:
        composed_origin = composition.runtime_origin
        composed_receipt_authority = composition.runtime_receipt_authority
    except Exception:
        _fail("consume_invalid")
    if (
        state.consumed
        or type(composition) is not ManagedMem0V5Composition
        or composition.authority != state.preflight.authority
        or composition.request != state.preflight.admission.request
        or composition_binding is not state.binding
        or receipt_authority is not state.receipt_authority
        or operation_manifest is not state.operation_manifest
        or normalized_origin != state.origin
        or _validated_origin(composed_origin) != state.origin
        or composed_receipt_authority is not state.receipt_authority
    ):
        _fail("consume_invalid")
    return state


def _validate_inputs(
    *,
    preflight: object,
    binding: object,
    receipt_authority: object,
    operation_manifest: object,
) -> None:
    try:
        if (
            type(preflight) is not ManagedMem0V5Preflight
            or type(binding) is not ManagedRunnerCompositionBinding
            or type(receipt_authority) is not Mem0V5ObservedExtractionReceiptAuthority
            or type(operation_manifest) is not OperationManifest
        ):
            raise TypeError
        preflight.__post_init__()
        receipt_authority.__post_init__()
        operation_manifest.__post_init__()
        request = preflight.admission.request
        operations = operation_manifest.operations
        observed = receipt_authority.operations
        targets = tuple(item for item in binding.backend_targets if item.backend_role == "mem0")
        valid = (
            binding.run_id == request.run_id
            and binding.deadline.tzinfo is not None
            and binding.deadline.utcoffset() is not None
            and len(targets) == 1
            and operation_manifest.run_id == request.run_id
            and len(operations) == preflight.authority.operation_count
            and len(operations) == request.expected_operation_count
            and len(operations) == len(observed)
            and receipt_authority.admission_commitment_sha256
            == preflight.admission.commitment_sha256
            and receipt_authority.runtime_source_sha256 == request.runtime_source_sha256
            and receipt_authority.route_binding_sha256 == request.route_sha256
            and receipt_authority.model == request.model
            and receipt_authority.reasoning_effort == request.reasoning_effort
            and receipt_authority.service_tier == request.service_tier
        )
        if not valid:
            raise TypeError
        for index, (operation, observed_operation) in enumerate(
            zip(operations, observed, strict=True)
        ):
            if (
                operation.ordinal != index
                or operation.operation_kind != _OPERATION_KIND
                or operation.operation_key != observed_operation.operation_id_sha256
                or operation.authority_commitment_sha256
                != preflight.authority.authority_commitment_sha256
                or operation.retry_disposition is not RetryDisposition.QUARANTINE_UNKNOWN
            ):
                raise TypeError
    except Exception:
        _fail("input_invalid")


def _validated_origin(value: object) -> str:
    try:
        parsed = urlsplit(value) if type(value) is str else None
        port = parsed.port if parsed is not None else None
    except ValueError:
        parsed = None
        port = None
    if (
        parsed is None
        or parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("origin_invalid")
    return f"http://{parsed.netloc.lower()}"


def _state(authority: object) -> _AuthorityState:
    with _LOCK:
        return _state_locked(authority)


def _state_locked(authority: object) -> _AuthorityState:
    if type(authority) is not ManagedMem0V5ProductionAuthority:
        _fail("invalid")
    state = _STATES.get(authority)
    if state is None or not hmac.compare_digest(state.integrity_mac, _state_mac(authority, state)):
        _fail("invalid")
    return state


def _store(authority: ManagedMem0V5ProductionAuthority, state: _AuthorityState) -> None:
    with _LOCK:
        _store_locked(authority, state)


def _store_locked(authority: ManagedMem0V5ProductionAuthority, state: _AuthorityState) -> None:
    _STATES[authority] = replace(state, integrity_mac=_state_mac(authority, state))


def _state_mac(authority: ManagedMem0V5ProductionAuthority, state: _AuthorityState) -> bytes:
    material = json.dumps(
        {
            "authority_identity": id(authority),
            "descriptor": tuple(
                getattr(state.descriptor, name) for name in state.descriptor.__dataclass_fields__
            ),
            "preflight_identity": id(state.preflight),
            "binding_identity": id(state.binding),
            "receipt_authority_identity": id(state.receipt_authority),
            "operation_manifest_identity": id(state.operation_manifest),
            "origin": state.origin,
            "consumed": state.consumed,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(_SECRET, material, hashlib.sha256).digest()


def _fail(suffix: str) -> NoReturn:
    raise ManagedMem0V5ProductionAuthorityError(
        f"managed_mem0_v5_production_authority_{suffix}"
    ) from None


_STATES = weakref.WeakKeyDictionary()

__all__ = (
    "ManagedMem0V5ProductionAuthority",
    "ManagedMem0V5ProductionAuthorityDescriptor",
    "ManagedMem0V5ProductionAuthorityError",
    "inspect_managed_mem0_v5_production_authority",
    "issue_managed_mem0_v5_production_authority",
)
