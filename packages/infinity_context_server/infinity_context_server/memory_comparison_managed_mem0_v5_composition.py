"""Restart-safe composition root for the managed Mem0 OSS v5 lane."""

from __future__ import annotations

import hashlib
import importlib
import os
import stat
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import final
from urllib.parse import urlsplit

from infinity_context_server.memory_comparison_managed_mem0_v5_checkpoint import (
    AtomicJsonManagedMem0V5CheckpointStore,
    HmacSha256ManagedMem0V5CheckpointSigner,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_binding import (
    ManagedMem0V5ServiceCleanupBinding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialPaths,
    load_managed_mem0_v5_credentials,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    AtomicJournalManagedMem0V5SingleDispatchGuard,
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_head_sqlite import (
    SQLiteManagedMem0V5CheckpointHead,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5LaneCoordinator,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_progress import (
    ManagedMem0V5CheckpointProgress,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    ManagedTransportCoverageCapability,
    issue_managed_transport_coverage_capability,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_verifiers import (
    ManagedMem0V5CleanupBridgeVerifier,
    ManagedMem0V5StorageBridgeVerifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5ReceiptAuthority,
    Mem0V5RuntimeReceiptVerifier,
    Mem0V5TransportPort,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
    Mem0V5ObservedExtractionReceiptVerifier,
    require_mem0_v5_observed_extraction_receipt_boundary,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService

_COMPOSITION_RUNTIME_LOCK = threading.Lock()
_COMPOSITION_RUNTIMES: dict[
    int,
    tuple[
        weakref.ReferenceType[object],
        Mem0OssFullRunAdmission,
        ManagedMem0V5HttpLane,
    ],
] = {}


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0V5StatePaths:
    """Same-failure-domain checkpoint and local crash/CAS head paths.

    The local head detects process-crash and competing-writer faults. It is not an
    external freshness anchor and makes no rollback claim after host or volume loss.
    """

    checkpoint: Path
    local_checkpoint_head: Path

    def __post_init__(self) -> None:
        paths = (self.checkpoint, self.local_checkpoint_head)
        if (
            any(not isinstance(path, Path) or not path.is_absolute() for path in paths)
            or self.checkpoint == self.local_checkpoint_head
            or any(path.name in {"", ".", ".."} for path in paths)
        ):
            raise ManagedRunError("managed Mem0 v5 composition state paths are invalid")


@final
@dataclass(frozen=True, slots=True, repr=False, weakref_slot=True)
class ManagedMem0V5Composition:
    """Public run authority and coordinator, without secret-bearing helpers."""

    authority: ManagedMem0V5ManifestAuthority
    request: Mem0OssAdmissionRequest
    coordinator: ManagedMem0V5LaneCoordinator

    def __post_init__(self) -> None:
        if (
            type(self.authority) is not ManagedMem0V5ManifestAuthority
            or type(self.request) is not Mem0OssAdmissionRequest
            or type(self.coordinator) is not ManagedMem0V5LaneCoordinator
        ):
            raise ManagedRunError("managed Mem0 v5 composition result is invalid")

    def issue_transport_coverage(
        self,
        *,
        benchmark: str,
        backend_role: str = "mem0",
    ) -> ManagedTransportCoverageCapability:
        admission, lane = _composition_runtime(self)
        return issue_managed_transport_coverage_capability(
            benchmark=benchmark,
            run_id_sha256=hashlib.sha256(self.request.run_id.encode()).hexdigest(),
            backend_role=backend_role,
            authority=self.authority,
            admission=admission,
            observations=lane.transport_observations,
        )

    def __repr__(self) -> str:
        return "ManagedMem0V5Composition(<opaque>)"


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedMem0V5Preflight:
    """Secret-free authority derived by the exact production public preflight."""

    authority: ManagedMem0V5ManifestAuthority
    admission: Mem0OssFullRunAdmission

    def __post_init__(self) -> None:
        if (
            type(self.authority) is not ManagedMem0V5ManifestAuthority
            or type(self.admission) is not Mem0OssFullRunAdmission
            or self.admission.ingestion_manifest_sha256 != self.authority.ingestion_manifest_sha256
            or self.admission.ingestion_root_sha256 != self.authority.ingestion_root_sha256
            or self.admission.ingestion_unit_count != self.authority.operation_count
        ):
            raise ManagedRunError("managed Mem0 v5 preflight result is invalid")

    def __repr__(self) -> str:
        return "ManagedMem0V5Preflight(<opaque>)"


def preflight_managed_mem0_v5(
    *,
    cases: tuple[ManagedRunCase, ...],
    current_date: str,
    request: Mem0OssAdmissionRequest,
    origin: str,
    timeout_seconds: float,
    state_paths: ManagedMem0V5StatePaths,
    credential_paths: ManagedMem0V5CredentialPaths,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    receipt_authority: Mem0V5ReceiptAuthority | Mem0V5ObservedExtractionReceiptAuthority,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
    transport: Mem0V5TransportPort | None = None,
) -> ManagedMem0V5Preflight:
    """Validate all public production authority without secrets, writes, or network."""

    authority = ManagedMem0V5ManifestProjector().project(cases, current_date=current_date)
    _require_endpoint(origin=origin, timeout_seconds=timeout_seconds)
    _require_state_storage(state_paths)
    _require_trusted_runtime_inputs(
        runtime_receipt_boundary=runtime_receipt_boundary,
        trusted_runtime_binding=trusted_runtime_binding,
        transport=transport,
    )
    admission = _require_public_binding(
        authority=authority,
        request=request,
        state_paths=state_paths,
        credential_paths=credential_paths,
        trusted_runtime_binding=trusted_runtime_binding,
        receipt_authority=receipt_authority,
        dispatch_guard=dispatch_guard,
    )
    if type(receipt_authority) is Mem0V5ObservedExtractionReceiptAuthority:
        require_mem0_v5_observed_extraction_receipt_boundary(
            boundary=runtime_receipt_boundary,
            runtime_binding=trusted_runtime_binding,
            authority=receipt_authority,
        )
    return ManagedMem0V5Preflight(authority, admission)


def compose_managed_mem0_v5(
    *,
    cases: tuple[ManagedRunCase, ...],
    current_date: str,
    request: Mem0OssAdmissionRequest,
    origin: str,
    timeout_seconds: float,
    state_paths: ManagedMem0V5StatePaths,
    credential_paths: ManagedMem0V5CredentialPaths,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    receipt_authority: Mem0V5ReceiptAuthority | Mem0V5ObservedExtractionReceiptAuthority,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None = None,
    transport: Mem0V5TransportPort | None = None,
) -> ManagedMem0V5Composition:
    """Build a fresh process-local coordinator over shared authenticated state.

    The trusted runtime binding authenticates only runtime_source_sha256 and the route.
    The request's runtime_source_revision and runtime_base_sha256 remain caller-declared
    admission metadata; this composition root makes no provenance claim for either field.
    """

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
    authority = preflight.authority
    projector = ManagedMem0V5ManifestProjector()

    with load_managed_mem0_v5_credentials(credential_paths) as credentials:
        witness_issuer, witness_verifier = create_managed_mem0_v5_storage_witness_authority()
        evidence_verifier = HmacSha256ManagedMem0V5EvidenceVerifier(
            key_capability=credentials.evidence_key,
            storage_witness_issuer=witness_issuer,
        )
        if request.credential_binding_sha256 != evidence_verifier.key_commitment_sha256:
            raise ManagedRunError("managed Mem0 v5 composition credential binding differs")

        receipt_secret = credentials.receipt_secret.consume()
        if type(receipt_authority) is Mem0V5ReceiptAuthority:
            receipt_verifier = Mem0V5RuntimeReceiptVerifier(
                boundary=runtime_receipt_boundary,
                runtime_binding=trusted_runtime_binding,
                receipt_secret=receipt_secret,
                authority=receipt_authority,
            )
        else:
            receipt_verifier = Mem0V5ObservedExtractionReceiptVerifier(
                boundary=runtime_receipt_boundary,
                runtime_binding=trusted_runtime_binding,
                receipt_secret=receipt_secret,
                authority=receipt_authority,
            )
        if not callable(getattr(receipt_verifier, "mark_outcome_unknown", None)):
            raise ManagedRunError("managed Mem0 v5 receipt recovery marker is unavailable")
        service = Mem0OssFullRunService(
            manifest_port=projector,
            receipt_port=receipt_verifier,
            storage_port=ManagedMem0V5StorageBridgeVerifier(
                authority=authority,
                storage_witness_verifier=witness_verifier,
            ),
            cleanup_port=ManagedMem0V5CleanupBridgeVerifier(),
        )
        lane = ManagedMem0V5HttpLane(
            origin=origin,
            bearer_capability=credentials.bearer_token,
            timeout_seconds=timeout_seconds,
            evidence_verifier=evidence_verifier,
            dispatch_binding=evidence_verifier,
            cleanup_binding=ManagedMem0V5ServiceCleanupBinding(service=service),
            dispatch_guard=dispatch_guard,
            transport=transport,
        )
        signer = HmacSha256ManagedMem0V5CheckpointSigner(
            key=credentials.checkpoint_signing_key.consume()
        )
        progress = ManagedMem0V5CheckpointProgress(
            store=AtomicJsonManagedMem0V5CheckpointStore(
                path=state_paths.checkpoint,
                signer=signer,
            ),
            signer=signer,
            head=SQLiteManagedMem0V5CheckpointHead(
                state_paths.local_checkpoint_head,
                hmac_key=credentials.checkpoint_head_key.consume(),
            ),
        )
        coordinator = ManagedMem0V5LaneCoordinator(
            service=service,
            lane_port=lane,
            progress_port=progress,
        )

    composition = ManagedMem0V5Composition(authority, request, coordinator)
    _register_composition_runtime(
        composition,
        admission=preflight.admission,
        lane=lane,
    )
    return composition


def _register_composition_runtime(
    composition: ManagedMem0V5Composition,
    *,
    admission: Mem0OssFullRunAdmission,
    lane: ManagedMem0V5HttpLane,
) -> None:
    identity = id(composition)

    def remove(reference: weakref.ReferenceType[object]) -> None:
        with _COMPOSITION_RUNTIME_LOCK:
            current = _COMPOSITION_RUNTIMES.get(identity)
            if current is not None and current[0] is reference:
                _COMPOSITION_RUNTIMES.pop(identity, None)

    reference = weakref.ref(composition, remove)
    with _COMPOSITION_RUNTIME_LOCK:
        _COMPOSITION_RUNTIMES[identity] = (reference, admission, lane)


def _composition_runtime(
    composition: ManagedMem0V5Composition,
) -> tuple[Mem0OssFullRunAdmission, ManagedMem0V5HttpLane]:
    with _COMPOSITION_RUNTIME_LOCK:
        runtime = _COMPOSITION_RUNTIMES.get(id(composition))
        if runtime is None or runtime[0]() is not composition:
            raise ManagedRunError("managed Mem0 v5 composition runtime is unavailable")
        return runtime[1], runtime[2]


def _require_public_binding(
    *,
    authority: ManagedMem0V5ManifestAuthority,
    request: Mem0OssAdmissionRequest,
    state_paths: ManagedMem0V5StatePaths,
    credential_paths: ManagedMem0V5CredentialPaths,
    trusted_runtime_binding: object,
    receipt_authority: Mem0V5ReceiptAuthority | Mem0V5ObservedExtractionReceiptAuthority,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None,
) -> Mem0OssFullRunAdmission:
    if (
        type(state_paths) is not ManagedMem0V5StatePaths
        or type(credential_paths) is not ManagedMem0V5CredentialPaths
        or type(request) is not Mem0OssAdmissionRequest
        or type(receipt_authority)
        not in (Mem0V5ReceiptAuthority, Mem0V5ObservedExtractionReceiptAuthority)
        or (
            dispatch_guard is not None
            and (
                type(dispatch_guard) is not AtomicJournalManagedMem0V5SingleDispatchGuard
                or authority.operation_count != 1
            )
        )
    ):
        raise ManagedRunError("managed Mem0 v5 composition input is invalid")
    state_values = (state_paths.checkpoint, state_paths.local_checkpoint_head)
    guard_values = () if dispatch_guard is None else (dispatch_guard.path,)
    try:
        normalized_paths = tuple(
            path.resolve(strict=False)
            for path in (*state_values, *guard_values, *credential_paths.values())
        )
    except OSError:
        raise ManagedRunError("managed Mem0 v5 composition paths are not distinct") from None
    if len(set(normalized_paths)) != 7 + len(guard_values):
        raise ManagedRunError("managed Mem0 v5 composition paths are not distinct")
    try:
        binding_source = trusted_runtime_binding.runtime_source_sha256
        binding_route = trusted_runtime_binding.route_binding_sha256
    except Exception:
        raise ManagedRunError("managed Mem0 v5 composition runtime binding is invalid") from None
    if (
        request.expected_operation_count != authority.operation_count
        or request.route_sha256 != receipt_authority.route_binding_sha256
        or request.route_sha256 != binding_route
        or request.runtime_source_sha256 != receipt_authority.runtime_source_sha256
        or request.runtime_source_sha256 != binding_source
        or request.model != receipt_authority.model
        or request.reasoning_effort != receipt_authority.reasoning_effort
        or request.service_tier != receipt_authority.service_tier
    ):
        raise ManagedRunError("managed Mem0 v5 composition authority binding differs")
    admission = Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    expected_operations = tuple(
        (
            index,
            canonical_sha256(
                {
                    "admission_commitment_sha256": admission.commitment_sha256,
                    "unit_index": index,
                    "unit_identity_sha256": unit.unit_identity_sha256,
                }
            ),
        )
        for index, unit in enumerate(authority.units)
    )
    if type(receipt_authority) is Mem0V5ReceiptAuthority:
        actual_operations = tuple(
            (operation.sequence, operation.operation_id_sha256)
            for operation in receipt_authority.operations
        )
        if actual_operations != expected_operations:
            raise ManagedRunError("managed Mem0 v5 composition receipt operations differ")
    else:
        unit = authority.units[0] if authority.operation_count == 1 else None
        if (
            unit is None
            or receipt_authority.admission_commitment_sha256 != admission.commitment_sha256
            or receipt_authority.sequence != 0
            or receipt_authority.operation_id_sha256 != expected_operations[0][1]
            or receipt_authority.unit_identity_sha256 != unit.unit_identity_sha256
            or receipt_authority.unit_sha256 != unit.unit_sha256
            or receipt_authority.scope_sha256 != unit.scope_sha256
        ):
            raise ManagedRunError("managed Mem0 v5 composition observed receipt binding differs")
    return admission


def _require_endpoint(*, origin: str, timeout_seconds: float) -> None:
    if type(origin) is not str or not 1 <= len(origin) <= 2_048:
        raise ManagedRunError("managed Mem0 v5 composition endpoint is invalid")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        raise ManagedRunError("managed Mem0 v5 composition endpoint is invalid") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or type(timeout_seconds) not in (int, float)
        or isinstance(timeout_seconds, bool)
        or not 0.01 <= float(timeout_seconds) <= 120.0
    ):
        raise ManagedRunError("managed Mem0 v5 composition endpoint is invalid")


def _require_state_storage(state_paths: object) -> None:
    if type(state_paths) is not ManagedMem0V5StatePaths:
        raise ManagedRunError("managed Mem0 v5 composition input is invalid")
    parents = (state_paths.checkpoint.parent, state_paths.local_checkpoint_head.parent)
    try:
        metadata = tuple(os.lstat(parent) for parent in parents)
    except OSError:
        raise ManagedRunError("managed Mem0 v5 composition state storage is invalid") from None
    if (
        any(
            not stat.S_ISDIR(item.st_mode)
            or item.st_uid != os.geteuid()
            or stat.S_IMODE(item.st_mode) != 0o700
            for item in metadata
        )
        or metadata[0].st_dev != metadata[1].st_dev
    ):
        raise ManagedRunError("managed Mem0 v5 composition state storage is invalid")


def _require_trusted_runtime_inputs(
    *,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    transport: Mem0V5TransportPort | None,
) -> None:
    try:
        receipt_module = importlib.import_module("phase_c_canary.runtime_receipt_v2")
        binding_module = importlib.import_module("phase_c_canary.runtime_binding")
        if (
            type(runtime_receipt_boundary) is not receipt_module.RuntimeReceiptV2Boundary
            or type(trusted_runtime_binding) is not binding_module.TrustedRuntimeBinding
            or not callable(getattr(runtime_receipt_boundary.hmac_verifier, "verify", None))
            or (transport is not None and not callable(getattr(transport, "request", None)))
        ):
            raise TypeError
        binding_module.require_trusted_runtime_binding(trusted_runtime_binding)
    except Exception:
        raise ManagedRunError("managed Mem0 v5 composition runtime authority is invalid") from None


__all__ = (
    "ManagedMem0V5Composition",
    "ManagedMem0V5Preflight",
    "ManagedMem0V5StatePaths",
    "compose_managed_mem0_v5",
    "preflight_managed_mem0_v5",
)
