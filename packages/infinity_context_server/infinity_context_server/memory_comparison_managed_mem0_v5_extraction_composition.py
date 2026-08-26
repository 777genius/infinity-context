"""Checkpoint-free HTTP runtime for managed Mem0 v5 extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_cleanup_binding import (
    ManagedMem0V5ServiceCleanupBinding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialCapabilities,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_dispatch_guard import (
    ManagedMem0V5SingleDispatchGuardPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_http_lane import (
    HmacSha256ManagedMem0V5EvidenceVerifier,
    ManagedMem0V5HttpLane,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5StorageWitnessVerifierPort,
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_verifiers import (
    ManagedMem0V5CleanupBridgeVerifier,
    ManagedMem0V5StorageBridgeVerifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5ReceiptAuthority,
    Mem0V5RuntimeReceiptVerifier,
    Mem0V5TransportPort,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
    Mem0V5ObservedExtractionReceiptVerifier,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import Mem0OssFullRunService

_ISSUER = object()


@final
@dataclass(frozen=True, slots=True, repr=False)
class ManagedMem0V5ExtractionRuntime:
    """Private owner for a composed lane and its verification service."""

    admission: Mem0OssFullRunAdmission
    service: Mem0OssFullRunService = field(repr=False)
    lane: ManagedMem0V5HttpLane = field(repr=False)
    receipt_authority: Mem0V5ReceiptAuthority | Mem0V5ObservedExtractionReceiptAuthority = field(
        repr=False
    )
    receipt_verifier: Mem0V5RuntimeReceiptVerifier | Mem0V5ObservedExtractionReceiptVerifier = (
        field(repr=False)
    )
    storage_verifier: ManagedMem0V5StorageWitnessVerifierPort = field(repr=False)


@final
@dataclass(frozen=True, slots=True, repr=False, init=False)
class ManagedMem0V5ExtractionCapabilities:
    """Focused extraction capabilities retained by their private owner."""

    _owner: object = field(repr=False)
    admission: Mem0OssFullRunAdmission
    http_lane: ManagedMem0V5HttpLane = field(repr=False)
    runtime_receipt_verifier: Mem0V5ObservedExtractionReceiptVerifier = field(repr=False)

    def __init__(
        self,
        owner: object,
        admission: Mem0OssFullRunAdmission,
        http_lane: ManagedMem0V5HttpLane,
        runtime_receipt_verifier: Mem0V5ObservedExtractionReceiptVerifier,
        *,
        _issuer: object,
    ) -> None:
        if (
            _issuer is not _ISSUER
            or owner is None
            or type(admission) is not Mem0OssFullRunAdmission
            or type(http_lane) is not ManagedMem0V5HttpLane
            or type(runtime_receipt_verifier) is not Mem0V5ObservedExtractionReceiptVerifier
        ):
            raise ManagedRunError("managed Mem0 v5 extraction capabilities are invalid")
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "admission", admission)
        object.__setattr__(self, "http_lane", http_lane)
        object.__setattr__(self, "runtime_receipt_verifier", runtime_receipt_verifier)

    def __repr__(self) -> str:
        return "ManagedMem0V5ExtractionCapabilities(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 v5 extraction capabilities are nonserializable")


def issue_managed_mem0_v5_extraction_capabilities(
    *,
    owner: object,
    admission: Mem0OssFullRunAdmission,
    lane: ManagedMem0V5HttpLane,
    receipt_verifier: Mem0V5ObservedExtractionReceiptVerifier,
) -> ManagedMem0V5ExtractionCapabilities:
    """Issue the narrow public capability while retaining its private owner."""

    return ManagedMem0V5ExtractionCapabilities(
        owner,
        admission,
        lane,
        receipt_verifier,
        _issuer=_ISSUER,
    )


def compose_managed_mem0_v5_extraction_runtime(
    *,
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
    projector: ManagedMem0V5ManifestProjector,
    request: Mem0OssAdmissionRequest,
    origin: str,
    timeout_seconds: float,
    runtime_receipt_boundary: object,
    trusted_runtime_binding: object,
    receipt_authority: Mem0V5ReceiptAuthority | Mem0V5ObservedExtractionReceiptAuthority,
    credentials: ManagedMem0V5CredentialCapabilities,
    dispatch_guard: ManagedMem0V5SingleDispatchGuardPort | None,
    transport: Mem0V5TransportPort | None,
    runtime_receipt_verifier_factory: object = Mem0V5RuntimeReceiptVerifier,
    observed_receipt_verifier_factory: object = Mem0V5ObservedExtractionReceiptVerifier,
) -> ManagedMem0V5ExtractionRuntime:
    """Compose the shared lane/verifier/service path without durable checkpoints."""

    witness_issuer, witness_verifier = create_managed_mem0_v5_storage_witness_authority()
    evidence_verifier = HmacSha256ManagedMem0V5EvidenceVerifier(
        key_capability=credentials.evidence_key,
        storage_witness_issuer=witness_issuer,
    )
    if request.credential_binding_sha256 != evidence_verifier.key_commitment_sha256:
        raise ManagedRunError("managed Mem0 v5 composition credential binding differs")
    receipt_secret = credentials.receipt_secret.consume()
    if type(receipt_authority) is Mem0V5ReceiptAuthority:
        receipt_verifier = runtime_receipt_verifier_factory(
            boundary=runtime_receipt_boundary,
            runtime_binding=trusted_runtime_binding,
            receipt_secret=receipt_secret,
            authority=receipt_authority,
        )
    else:
        factory = getattr(
            observed_receipt_verifier_factory,
            "_for_preflighted_composition",
            None,
        )
        if not callable(factory):
            raise ManagedRunError("managed Mem0 v5 receipt verifier is unavailable")
        receipt_verifier = factory(
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
    return ManagedMem0V5ExtractionRuntime(
        admission=admission,
        service=service,
        lane=lane,
        receipt_authority=receipt_authority,
        receipt_verifier=receipt_verifier,
        storage_verifier=witness_verifier,
    )


__all__ = (
    "ManagedMem0V5ExtractionCapabilities",
    "ManagedMem0V5ExtractionRuntime",
    "compose_managed_mem0_v5_extraction_runtime",
    "issue_managed_mem0_v5_extraction_capabilities",
)
