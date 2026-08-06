"""Trusted sealed authority for provider-neutral paired benchmark ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, final

from infinity_context_server.memory_comparison_ingestion_contracts import (
    IngestionMessage,
    IngestionUnit,
    IngestionUnitManifest,
    IngestionUnitMetadata,
)
from infinity_context_server.resumable_operation_journal import (
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationRunIdentity,
    RetryDisposition,
)
from infinity_context_server.resumable_operation_journal.domain import sha256_commitment


class PairedIngestionAuthorityError(RuntimeError):
    """A trusted paired-ingestion authority cannot be proven."""


class PairedIngestionLane(StrEnum):
    INFINITY = "infinity"
    MEM0 = "mem0"


@final
@dataclass(frozen=True, slots=True)
class VerifiedIngestionManifest:
    manifest_sha256: str
    corpus_projection_sha256: str
    unit_root_sha256: str
    unit_count: int
    verifier_key_id: str
    verification_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            any(
                not _is_sha256(value)
                for value in (
                    self.manifest_sha256,
                    self.corpus_projection_sha256,
                    self.unit_root_sha256,
                    self.verification_commitment_sha256,
                )
            )
            or type(self.unit_count) is not int
            or self.unit_count <= 0
            or not _safe_id(self.verifier_key_id)
        ):
            raise PairedIngestionAuthorityError("manifest verification result is invalid")


@final
@dataclass(frozen=True, slots=True)
class PublicIngestionManifestProjection:
    """Authenticated public-only projection; it cannot expose source audits or QA."""

    manifest_sha256: str
    corpus_projection_sha256: str
    unit_root_sha256: str
    units: tuple[IngestionUnit, ...]

    def __post_init__(self) -> None:
        if (
            not _is_sha256(self.manifest_sha256)
            or not _is_sha256(self.corpus_projection_sha256)
            or type(self.units) is not tuple
            or not self.units
            or any(type(unit) is not IngestionUnit for unit in self.units)
        ):
            raise PairedIngestionAuthorityError("public manifest projection is invalid")
        for ordinal, unit in enumerate(self.units):
            unit.validate()
            if unit.ordinal != ordinal:
                raise PairedIngestionAuthorityError("public manifest ordinal is invalid")
        if self.unit_root_sha256 != ingestion_unit_root_sha256(self.units):
            raise PairedIngestionAuthorityError("public manifest unit root is invalid")


class IngestionManifestVerificationPort(Protocol):
    """Trusted capability configured outside the benchmark coordinator."""

    def verify(self, manifest: IngestionUnitManifest) -> VerifiedIngestionManifest: ...

    def reverify(
        self, projection: PublicIngestionManifestProjection
    ) -> VerifiedIngestionManifest: ...


@final
@dataclass(frozen=True, slots=True)
class PairedAdmissionRequest:
    run_id: str
    manifest_sha256: str
    corpus_projection_sha256: str
    unit_root_sha256: str
    expected_unit_count: int
    runtime_route_sha256: str

    def __post_init__(self) -> None:
        if (
            not _safe_id(self.run_id)
            or any(
                not _is_sha256(value)
                for value in (
                    self.manifest_sha256,
                    self.corpus_projection_sha256,
                    self.unit_root_sha256,
                    self.runtime_route_sha256,
                )
            )
            or type(self.expected_unit_count) is not int
            or self.expected_unit_count <= 0
        ):
            raise PairedIngestionAuthorityError("paired admission request is invalid")

    @property
    def commitment_sha256(self) -> str:
        return sha256_commitment(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "corpus_projection_sha256": self.corpus_projection_sha256,
            "expected_unit_count": self.expected_unit_count,
            "manifest_sha256": self.manifest_sha256,
            "run_id": self.run_id,
            "runtime_route_sha256": self.runtime_route_sha256,
            "unit_root_sha256": self.unit_root_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class VerifiedPairedAdmission:
    request: PairedAdmissionRequest
    admission_commitment_sha256: str
    verifier_key_id: str
    verification_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.request) is not PairedAdmissionRequest
            or self.admission_commitment_sha256 != self.request.commitment_sha256
            or not _safe_id(self.verifier_key_id)
            or not _is_sha256(self.verification_commitment_sha256)
        ):
            raise PairedIngestionAuthorityError("paired admission verification is invalid")


class PairedAdmissionVerificationPort(Protocol):
    """Trusted admission/readiness verifier for an exact manifest and route."""

    def verify(self, request: PairedAdmissionRequest) -> VerifiedPairedAdmission: ...


@final
@dataclass(frozen=True, slots=True)
class PairedLaneBinding:
    lane: PairedIngestionLane
    run_identity: OperationRunIdentity
    operation_manifest: OperationManifest
    ingestion_manifest_sha256: str
    manifest_verifier_key_id: str
    manifest_verification_commitment_sha256: str
    admission_commitment_sha256: str
    admission_verifier_key_id: str
    admission_verification_commitment_sha256: str
    runtime_route_sha256: str
    scope_commitment_sha256: str
    binding_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.lane) is not PairedIngestionLane
            or type(self.run_identity) is not OperationRunIdentity
            or type(self.operation_manifest) is not OperationManifest
            or self.run_identity.run_id != self.operation_manifest.run_id
            or self.run_identity.manifest_commitment_sha256
            != self.operation_manifest.commitment_sha256
            or any(
                not _is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.ingestion_manifest_sha256,
                    self.manifest_verification_commitment_sha256,
                    self.runtime_route_sha256,
                    self.scope_commitment_sha256,
                    self.admission_verification_commitment_sha256,
                )
            )
            or not _safe_id(self.manifest_verifier_key_id)
            or not _safe_id(self.admission_verifier_key_id)
            or self.binding_sha256 != _lane_binding_sha256(self)
        ):
            raise PairedIngestionAuthorityError("paired lane binding is invalid")


@final
@dataclass(frozen=True, slots=True)
class PairedIngestionAuthority:
    run_id: str
    public_manifest: PublicIngestionManifestProjection = field(repr=False)
    manifest_verification: VerifiedIngestionManifest
    admission: VerifiedPairedAdmission
    lanes: tuple[PairedLaneBinding, PairedLaneBinding]
    authority_sha256: str

    @property
    def ingestion_manifest_sha256(self) -> str:
        return self.manifest_verification.manifest_sha256

    @property
    def corpus_projection_sha256(self) -> str:
        return self.manifest_verification.corpus_projection_sha256

    @property
    def units(self) -> tuple[IngestionUnit, ...]:
        return self.public_manifest.units

    def __post_init__(self) -> None:
        self._validate_structure()

    def validate_execution(
        self,
        *,
        manifest_verifier: IngestionManifestVerificationPort,
        admission_verifier: PairedAdmissionVerificationPort,
    ) -> None:
        """Re-verify mutable-process state immediately before every execution."""

        self._validate_structure()
        try:
            self.public_manifest.__post_init__()
            for unit in self.public_manifest.units:
                unit.validate()
            manifest_proof = _reverify_manifest(self.public_manifest, manifest_verifier)
            request = _admission_request(
                self.public_manifest,
                run_id=self.run_id,
                runtime_route_sha256=self.admission.request.runtime_route_sha256,
            )
            admission = _verify_admission(request, admission_verifier)
        except Exception:
            raise PairedIngestionAuthorityError(
                "paired execution authority verification failed"
            ) from None
        if manifest_proof != self.manifest_verification or admission != self.admission:
            raise PairedIngestionAuthorityError("paired execution authority diverged")
        rebuilt = _build_lanes(
            self.public_manifest,
            request=request,
            signer_key_id=self.lanes[0].run_identity.signer_key_id,
            manifest_proof=manifest_proof,
            admission=admission,
        )
        if rebuilt != self.lanes or self.authority_sha256 != _authority_sha256(
            run_id=self.run_id,
            manifest=manifest_proof,
            admission=admission,
            lanes=rebuilt,
        ):
            raise PairedIngestionAuthorityError("paired execution lane authority diverged")

    def execution_units(
        self,
        *,
        manifest_verifier: IngestionManifestVerificationPort,
        admission_verifier: PairedAdmissionVerificationPort,
    ) -> tuple[IngestionUnit, ...]:
        """Return a protected execution snapshot after immediate reverification."""

        self.validate_execution(
            manifest_verifier=manifest_verifier,
            admission_verifier=admission_verifier,
        )
        units = _clone_units(self.public_manifest.units)
        if ingestion_unit_root_sha256(units) != self.manifest_verification.unit_root_sha256:
            raise PairedIngestionAuthorityError("paired execution unit snapshot diverged")
        return units

    def lane(self, lane: PairedIngestionLane) -> PairedLaneBinding:
        for binding in self.lanes:
            if binding.lane is lane:
                return binding
        raise PairedIngestionAuthorityError("paired lane is not admitted")

    def _validate_structure(self) -> None:
        if (
            not _safe_id(self.run_id)
            or type(self.public_manifest) is not PublicIngestionManifestProjection
            or type(self.manifest_verification) is not VerifiedIngestionManifest
            or type(self.admission) is not VerifiedPairedAdmission
            or type(self.lanes) is not tuple
            or len(self.lanes) != 2
            or tuple(binding.lane for binding in self.lanes)
            != (PairedIngestionLane.INFINITY, PairedIngestionLane.MEM0)
            or any(type(binding) is not PairedLaneBinding for binding in self.lanes)
            or self.admission.request.run_id != self.run_id
        ):
            raise PairedIngestionAuthorityError("paired ingestion authority is invalid")


@final
class PairedLaneManifestPolicy:
    def __init__(self, binding: PairedLaneBinding) -> None:
        if type(binding) is not PairedLaneBinding:
            raise PairedIngestionAuthorityError("paired manifest policy binding is invalid")
        binding.__post_init__()
        self._binding = binding

    def validate(self, *, identity: OperationRunIdentity, manifest: OperationManifest) -> None:
        if identity != self._binding.run_identity or manifest != self._binding.operation_manifest:
            raise OperationJournalError("paired_ingestion_manifest_policy_divergent")


def build_paired_ingestion_authority(
    manifest: IngestionUnitManifest,
    *,
    run_id: str,
    runtime_route_sha256: str,
    signer_key_id: str,
    manifest_verifier: IngestionManifestVerificationPort,
    admission_verifier: PairedAdmissionVerificationPort,
) -> PairedIngestionAuthority:
    if type(manifest) is not IngestionUnitManifest or not _safe_id(run_id):
        raise PairedIngestionAuthorityError("paired authority input is invalid")
    try:
        manifest.validate()
        for unit in manifest.units:
            unit.validate()
        proof = _verify_manifest(manifest, manifest_verifier)
        public_manifest = PublicIngestionManifestProjection(
            manifest_sha256=manifest.manifest_sha256,
            corpus_projection_sha256=manifest.corpus_projection_sha256,
            unit_root_sha256=ingestion_unit_root_sha256(manifest.units),
            units=_clone_units(manifest.units),
        )
        request = _admission_request(
            public_manifest, run_id=run_id, runtime_route_sha256=runtime_route_sha256
        )
        admission = _verify_admission(request, admission_verifier)
        lanes = _build_lanes(
            public_manifest,
            request=request,
            signer_key_id=signer_key_id,
            manifest_proof=proof,
            admission=admission,
        )
        return PairedIngestionAuthority(
            run_id=run_id,
            public_manifest=public_manifest,
            manifest_verification=proof,
            admission=admission,
            lanes=lanes,
            authority_sha256=_authority_sha256(
                run_id=run_id, manifest=proof, admission=admission, lanes=lanes
            ),
        )
    except Exception:
        raise PairedIngestionAuthorityError("paired authority verification failed") from None


def ingestion_unit_root_sha256(units: tuple[IngestionUnit, ...]) -> str:
    return sha256_commitment(
        {
            "units": [
                {
                    "corpus_id": unit.corpus_id,
                    "metadata_sha256": unit.metadata_sha256,
                    "ordinal": unit.ordinal,
                    "payload_sha256": unit.payload_sha256,
                    "unit_input_sha256": unit.unit_input_sha256,
                    "unit_sha256": unit.unit_sha256,
                }
                for unit in units
            ]
        }
    )


def _clone_units(units: tuple[IngestionUnit, ...]) -> tuple[IngestionUnit, ...]:
    return tuple(
        IngestionUnit(
            ordinal=unit.ordinal,
            corpus_id=unit.corpus_id,
            messages=tuple(
                IngestionMessage(role=message.role, content=message.content)
                for message in unit.messages
            ),
            metadata=IngestionUnitMetadata(
                source_id=unit.metadata.source_id,
                timestamp=unit.metadata.timestamp,
            ),
            payload_sha256=unit.payload_sha256,
            metadata_sha256=unit.metadata_sha256,
            unit_input_sha256=unit.unit_input_sha256,
            unit_sha256=unit.unit_sha256,
        )
        for unit in units
    )


def _verify_manifest(
    manifest: IngestionUnitManifest, verifier: IngestionManifestVerificationPort
) -> VerifiedIngestionManifest:
    result = verifier.verify(manifest)
    expected = (
        manifest.manifest_sha256,
        manifest.corpus_projection_sha256,
        ingestion_unit_root_sha256(manifest.units),
        len(manifest.units),
    )
    if (
        type(result) is not VerifiedIngestionManifest
        or (
            result.manifest_sha256,
            result.corpus_projection_sha256,
            result.unit_root_sha256,
            result.unit_count,
        )
        != expected
    ):
        raise PairedIngestionAuthorityError("trusted manifest verification diverged")
    return result


def _reverify_manifest(
    projection: PublicIngestionManifestProjection,
    verifier: IngestionManifestVerificationPort,
) -> VerifiedIngestionManifest:
    result = verifier.reverify(projection)
    expected = (
        projection.manifest_sha256,
        projection.corpus_projection_sha256,
        projection.unit_root_sha256,
        len(projection.units),
    )
    if (
        type(result) is not VerifiedIngestionManifest
        or (
            result.manifest_sha256,
            result.corpus_projection_sha256,
            result.unit_root_sha256,
            result.unit_count,
        )
        != expected
    ):
        raise PairedIngestionAuthorityError("trusted manifest reverification diverged")
    return result


def _admission_request(
    manifest: PublicIngestionManifestProjection,
    *,
    run_id: str,
    runtime_route_sha256: str,
) -> PairedAdmissionRequest:
    return PairedAdmissionRequest(
        run_id=run_id,
        manifest_sha256=manifest.manifest_sha256,
        corpus_projection_sha256=manifest.corpus_projection_sha256,
        unit_root_sha256=manifest.unit_root_sha256,
        expected_unit_count=len(manifest.units),
        runtime_route_sha256=runtime_route_sha256,
    )


def _verify_admission(
    request: PairedAdmissionRequest, verifier: PairedAdmissionVerificationPort
) -> VerifiedPairedAdmission:
    result = verifier.verify(request)
    if type(result) is not VerifiedPairedAdmission or result.request != request:
        raise PairedIngestionAuthorityError("trusted admission verification diverged")
    return result


def _build_lanes(
    manifest: PublicIngestionManifestProjection,
    *,
    request: PairedAdmissionRequest,
    signer_key_id: str,
    manifest_proof: VerifiedIngestionManifest,
    admission: VerifiedPairedAdmission,
) -> tuple[PairedLaneBinding, PairedLaneBinding]:
    values = tuple(
        _build_lane(
            lane,
            manifest=manifest,
            request=request,
            signer_key_id=signer_key_id,
            manifest_proof=manifest_proof,
            admission=admission,
        )
        for lane in (PairedIngestionLane.INFINITY, PairedIngestionLane.MEM0)
    )
    return values  # type: ignore[return-value]


def _build_lane(
    lane: PairedIngestionLane,
    *,
    manifest: PublicIngestionManifestProjection,
    request: PairedAdmissionRequest,
    signer_key_id: str,
    manifest_proof: VerifiedIngestionManifest,
    admission: VerifiedPairedAdmission,
) -> PairedLaneBinding:
    retry = (
        RetryDisposition.IDEMPOTENT_REPLAY
        if lane is PairedIngestionLane.INFINITY
        else RetryDisposition.QUARANTINE_UNKNOWN
    )
    scope_sha = sha256_commitment(
        {
            "corpora": sorted({unit.corpus_id for unit in manifest.units}),
            "lane": lane.value,
            "manifest_sha256": manifest.manifest_sha256,
        }
    )
    operations = tuple(
        LogicalOperationIdentity(
            run_id=request.run_id,
            operation_key=unit.metadata.source_id,
            operation_kind=f"paired_ingestion_{lane.value}",
            ordinal=unit.ordinal,
            authority_commitment_sha256=sha256_commitment(
                {
                    "admission_commitment_sha256": request.commitment_sha256,
                    "admission_verification_sha256": admission.verification_commitment_sha256,
                    "admission_verifier_key_id": admission.verifier_key_id,
                    "corpus_id": unit.corpus_id,
                    "lane": lane.value,
                    "manifest_sha256": manifest.manifest_sha256,
                    "manifest_verification_sha256": manifest_proof.verification_commitment_sha256,
                    "manifest_verifier_key_id": manifest_proof.verifier_key_id,
                    "metadata_sha256": unit.metadata_sha256,
                    "ordinal": unit.ordinal,
                    "payload_sha256": unit.payload_sha256,
                    "runtime_route_sha256": request.runtime_route_sha256,
                    "source_id": unit.metadata.source_id,
                    "unit_input_sha256": unit.unit_input_sha256,
                    "unit_sha256": unit.unit_sha256,
                }
            ),
            retry_disposition=retry,
        )
        for unit in manifest.units
    )
    operation_manifest = OperationManifest(operations)
    policy_sha = sha256_commitment(
        {
            "admission_commitment_sha256": request.commitment_sha256,
            "admission_verification_sha256": admission.verification_commitment_sha256,
            "admission_verifier_key_id": admission.verifier_key_id,
            "lane": lane.value,
            "manifest_sha256": manifest.manifest_sha256,
            "manifest_verification_sha256": manifest_proof.verification_commitment_sha256,
            "manifest_verifier_key_id": manifest_proof.verifier_key_id,
            "runtime_route_sha256": request.runtime_route_sha256,
            "scope_commitment_sha256": scope_sha,
        }
    )
    identity = OperationRunIdentity(
        run_id=request.run_id,
        operation_namespace=f"paired_ingestion.{lane.value}",
        manifest_commitment_sha256=operation_manifest.commitment_sha256,
        policy_commitment_sha256=policy_sha,
        signer_key_id=signer_key_id,
        expected_operation_count=len(operations),
    )
    binding_sha = sha256_commitment(
        {
            "admission_commitment_sha256": request.commitment_sha256,
            "admission_verification_sha256": admission.verification_commitment_sha256,
            "admission_verifier_key_id": admission.verifier_key_id,
            "journal_manifest_sha256": operation_manifest.commitment_sha256,
            "journal_policy_sha256": identity.policy_commitment_sha256,
            "ingestion_manifest_sha256": manifest.manifest_sha256,
            "lane": lane.value,
            "manifest_verification_sha256": manifest_proof.verification_commitment_sha256,
            "manifest_verifier_key_id": manifest_proof.verifier_key_id,
            "runtime_route_sha256": request.runtime_route_sha256,
            "scope_commitment_sha256": scope_sha,
        }
    )
    return PairedLaneBinding(
        lane=lane,
        run_identity=identity,
        operation_manifest=operation_manifest,
        ingestion_manifest_sha256=manifest.manifest_sha256,
        manifest_verifier_key_id=manifest_proof.verifier_key_id,
        manifest_verification_commitment_sha256=manifest_proof.verification_commitment_sha256,
        admission_commitment_sha256=request.commitment_sha256,
        admission_verifier_key_id=admission.verifier_key_id,
        admission_verification_commitment_sha256=admission.verification_commitment_sha256,
        runtime_route_sha256=request.runtime_route_sha256,
        scope_commitment_sha256=scope_sha,
        binding_sha256=binding_sha,
    )


def _lane_binding_sha256(binding: PairedLaneBinding) -> str:
    return sha256_commitment(
        {
            "admission_commitment_sha256": binding.admission_commitment_sha256,
            "admission_verification_sha256": binding.admission_verification_commitment_sha256,
            "admission_verifier_key_id": binding.admission_verifier_key_id,
            "journal_manifest_sha256": binding.operation_manifest.commitment_sha256,
            "journal_policy_sha256": binding.run_identity.policy_commitment_sha256,
            "ingestion_manifest_sha256": binding.ingestion_manifest_sha256,
            "lane": binding.lane.value,
            "manifest_verification_sha256": binding.manifest_verification_commitment_sha256,
            "manifest_verifier_key_id": binding.manifest_verifier_key_id,
            "runtime_route_sha256": binding.runtime_route_sha256,
            "scope_commitment_sha256": binding.scope_commitment_sha256,
        }
    )


def _authority_sha256(
    *,
    run_id: str,
    manifest: VerifiedIngestionManifest,
    admission: VerifiedPairedAdmission,
    lanes: tuple[PairedLaneBinding, PairedLaneBinding],
) -> str:
    return sha256_commitment(
        {
            "admission_commitment_sha256": admission.admission_commitment_sha256,
            "admission_verification_sha256": admission.verification_commitment_sha256,
            "admission_verifier_key_id": admission.verifier_key_id,
            "lane_binding_sha256s": [item.binding_sha256 for item in lanes],
            "manifest_verification_sha256": manifest.verification_commitment_sha256,
            "manifest_verifier_key_id": manifest.verifier_key_id,
            "run_id": run_id,
        }
    )


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_id(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 160
        and all(character.isalnum() or character in "._:-" for character in value)
    )


__all__ = (
    "IngestionManifestVerificationPort",
    "PairedAdmissionRequest",
    "PairedAdmissionVerificationPort",
    "PairedIngestionAuthority",
    "PairedIngestionAuthorityError",
    "PairedIngestionLane",
    "PairedLaneBinding",
    "PairedLaneManifestPolicy",
    "PublicIngestionManifestProjection",
    "VerifiedIngestionManifest",
    "VerifiedPairedAdmission",
    "build_paired_ingestion_authority",
    "ingestion_unit_root_sha256",
)
