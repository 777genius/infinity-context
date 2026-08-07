"""Provider-neutral completeness proof for managed v5 transport observations."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import InitVar, dataclass
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5AuthenticatedRequestBindingV2Witness,
    ManagedMem0V5RequestBindingV2Receipt,
    authenticate_managed_mem0_v5_request_binding_v2_witness,
    claim_managed_mem0_v5_request_binding_v2_witnesses,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
    is_sha256,
)

_ROLE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_BENCHMARKS = frozenset(("locomo", "longmemeval"))
_CAPABILITY_TOKEN = object()
_VERIFIED_TOKEN = object()
_VERIFIED_KEY = secrets.token_bytes(32)
_SNAPSHOT_TOKEN = object()
_SNAPSHOT_KEY = secrets.token_bytes(32)


@final
@dataclass(frozen=True, slots=True, repr=False)
class VerifiedManagedTransportCoverage:
    """Gold-free proof that every admitted extraction crossed the transport."""

    benchmark: str
    run_id_sha256: str
    backend_role: str
    admission_commitment_sha256: str
    authority_commitment_sha256: str
    per_corpus_operation_counts: tuple[tuple[str, int], ...]
    operation_count: int
    request_binding_evidence_root_sha256: str
    evidence_commitment_sha256: str
    _authentication_sha256: str
    _token: InitVar[object]

    def __post_init__(self, _token: object) -> None:
        counts = self.per_corpus_operation_counts
        if (
            _token is not _VERIFIED_TOKEN
            or type(self.benchmark) is not str
            or self.benchmark not in _BENCHMARKS
            or not is_sha256(self.run_id_sha256)
            or not is_sha256(self.admission_commitment_sha256)
            or not is_sha256(self.authority_commitment_sha256)
            or type(self.backend_role) is not str
            or _ROLE.fullmatch(self.backend_role) is None
            or type(counts) is not tuple
            or not counts
            or any(
                type(item) is not tuple
                or len(item) != 2
                or not _text(item[0])
                or type(item[1]) is not int
                or item[1] < 1
                for item in counts
            )
            or len({item[0] for item in counts}) != len(counts)
            or type(self.operation_count) is not int
            or self.operation_count != sum(item[1] for item in counts)
            or not is_sha256(self.request_binding_evidence_root_sha256)
            or not is_sha256(self.evidence_commitment_sha256)
            or self.evidence_commitment_sha256 != canonical_sha256(self.commitment_payload())
            or not hmac.compare_digest(
                self._authentication_sha256,
                _verified_authentication(self.evidence_commitment_sha256),
            )
        ):
            raise ManagedRunError("managed transport coverage is invalid")

    @property
    def locomo_operation_count(self) -> int:
        """LongMemEval carries no LoCoMo-turn claim by construction."""

        return self.operation_count if self.benchmark == "locomo" else 0

    def commitment_payload(self) -> dict[str, object]:
        return {
            "benchmark": self.benchmark,
            "run_id_sha256": self.run_id_sha256,
            "backend_role": self.backend_role,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "authority_commitment_sha256": self.authority_commitment_sha256,
            "per_corpus_operation_counts": [
                {"corpus_id": corpus_id, "operation_count": count}
                for corpus_id, count in self.per_corpus_operation_counts
            ],
            "operation_count": self.operation_count,
            "locomo_operation_count": self.locomo_operation_count,
            "request_binding_evidence_root_sha256": (self.request_binding_evidence_root_sha256),
        }

    def public_payload(self) -> dict[str, object]:
        authenticate_managed_transport_coverage(self)
        return {
            **self.commitment_payload(),
            "evidence_commitment_sha256": self.evidence_commitment_sha256,
        }

    def __repr__(self) -> str:
        return "VerifiedManagedTransportCoverage(<opaque>)"


def authenticate_managed_transport_coverage(
    value: object,
) -> VerifiedManagedTransportCoverage:
    """Revalidate the process-local proof before trusting any public field."""

    if type(value) is not VerifiedManagedTransportCoverage:
        raise ManagedRunError("managed transport coverage is unauthenticated")
    value.__post_init__(_VERIFIED_TOKEN)
    return value


@final
@dataclass(frozen=True, slots=True, repr=False)
class _ManagedTransportObservationSnapshot:
    """Private authenticated primitive copy detached from the caller's witness."""

    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    corpus_id: str
    source_id: str
    source_sha256: str
    observation_date: str
    observation_date_commitment_sha256: str
    request_body_sha256: str
    request_binding_evidence_sha256: str
    _authentication_sha256: str
    _token: InitVar[object]

    def __post_init__(self, _token: object) -> None:
        receipt = ManagedMem0V5RequestBindingV2Receipt(**self.payload())
        if _token is not _SNAPSHOT_TOKEN or not hmac.compare_digest(
            self._authentication_sha256,
            _snapshot_authentication(receipt),
        ):
            raise ManagedRunError("managed transport observation snapshot is unauthenticated")

    def payload(self) -> dict[str, str]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "corpus_id": self.corpus_id,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "observation_date": self.observation_date,
            "observation_date_commitment_sha256": self.observation_date_commitment_sha256,
            "request_body_sha256": self.request_body_sha256,
            "request_binding_evidence_sha256": self.request_binding_evidence_sha256,
        }


class ManagedTransportCoverageCapabilityPort(Protocol):
    def consume_complete_transport_coverage(
        self,
        *,
        expected_admission_commitment_sha256: str,
        expected_operation_ids: tuple[str, ...],
    ) -> VerifiedManagedTransportCoverage: ...


@final
class ManagedTransportCoverageCapability:
    """One-use authority for producing an exact transport completeness proof."""

    __slots__ = (
        "_admission_commitment_sha256",
        "_authority_commitment_sha256",
        "_backend_role",
        "_benchmark",
        "_consumed",
        "_observations",
        "_run_id_sha256",
    )

    def __init__(
        self,
        *,
        benchmark: str,
        run_id_sha256: str,
        backend_role: str,
        authority: ManagedMem0V5ManifestAuthority,
        admission: Mem0OssFullRunAdmission,
        observations: tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...],
        _token: object,
    ) -> None:
        if _token is not _CAPABILITY_TOKEN:
            raise ManagedRunError("managed transport coverage capability is invalid")
        try:
            receipts = _validate_inputs(
                benchmark=benchmark,
                run_id_sha256=run_id_sha256,
                backend_role=backend_role,
                authority=authority,
                admission=admission,
                observations=observations,
            )
            claim_managed_mem0_v5_request_binding_v2_witnesses(observations)
        except ManagedRunError:
            raise
        except Exception:
            raise ManagedRunError("managed transport witness is unauthenticated") from None
        self._benchmark = benchmark
        self._run_id_sha256 = run_id_sha256
        self._backend_role = backend_role
        self._authority_commitment_sha256 = authority.authority_commitment_sha256
        self._admission_commitment_sha256 = admission.commitment_sha256
        self._observations = receipts
        self._consumed = False

    def consume_complete_transport_coverage(
        self,
        *,
        expected_admission_commitment_sha256: str,
        expected_operation_ids: tuple[str, ...],
    ) -> VerifiedManagedTransportCoverage:
        if self._consumed:
            raise ManagedRunError("managed transport coverage capability already consumed")
        self._consumed = True
        for observation in self._observations:
            observation.__post_init__(_SNAPSHOT_TOKEN)
        if (
            expected_admission_commitment_sha256 != self._admission_commitment_sha256
            or type(expected_operation_ids) is not tuple
            or any(not is_sha256(item) for item in expected_operation_ids)
            or len(set(expected_operation_ids)) != len(expected_operation_ids)
            or expected_operation_ids
            != tuple(item.operation_id_sha256 for item in self._observations)
        ):
            raise ManagedRunError("managed transport coverage expectation differs")
        counts = _corpus_counts(self._observations)
        evidence_root = canonical_sha256(
            {
                "request_binding_evidence_sha256": [
                    item.request_binding_evidence_sha256 for item in self._observations
                ]
            }
        )
        payload = {
            "benchmark": self._benchmark,
            "run_id_sha256": self._run_id_sha256,
            "backend_role": self._backend_role,
            "admission_commitment_sha256": self._admission_commitment_sha256,
            "authority_commitment_sha256": self._authority_commitment_sha256,
            "per_corpus_operation_counts": [
                {"corpus_id": corpus_id, "operation_count": count} for corpus_id, count in counts
            ],
            "operation_count": len(self._observations),
            "locomo_operation_count": (
                len(self._observations) if self._benchmark == "locomo" else 0
            ),
            "request_binding_evidence_root_sha256": evidence_root,
        }
        evidence_commitment = canonical_sha256(payload)
        return VerifiedManagedTransportCoverage(
            benchmark=self._benchmark,
            run_id_sha256=self._run_id_sha256,
            backend_role=self._backend_role,
            admission_commitment_sha256=self._admission_commitment_sha256,
            authority_commitment_sha256=self._authority_commitment_sha256,
            per_corpus_operation_counts=counts,
            operation_count=len(self._observations),
            request_binding_evidence_root_sha256=evidence_root,
            evidence_commitment_sha256=evidence_commitment,
            _authentication_sha256=_verified_authentication(evidence_commitment),
            _token=_VERIFIED_TOKEN,
        )

    def __repr__(self) -> str:
        return "ManagedTransportCoverageCapability(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("managed transport coverage capabilities are nonserializable")


def issue_managed_transport_coverage_capability(
    *,
    benchmark: str,
    run_id_sha256: str,
    backend_role: str,
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
    observations: tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...],
) -> ManagedTransportCoverageCapability:
    return ManagedTransportCoverageCapability(
        benchmark=benchmark,
        run_id_sha256=run_id_sha256,
        backend_role=backend_role,
        authority=authority,
        admission=admission,
        observations=observations,
        _token=_CAPABILITY_TOKEN,
    )


def _validate_inputs(
    *,
    benchmark: object,
    run_id_sha256: object,
    backend_role: object,
    authority: object,
    admission: object,
    observations: object,
) -> tuple[_ManagedTransportObservationSnapshot, ...]:
    if (
        type(benchmark) is not str
        or benchmark not in _BENCHMARKS
        or not is_sha256(run_id_sha256)
        or type(backend_role) is not str
        or _ROLE.fullmatch(backend_role) is None
        or type(authority) is not ManagedMem0V5ManifestAuthority
        or type(admission) is not Mem0OssFullRunAdmission
        or type(observations) is not tuple
        or any(
            type(item) is not ManagedMem0V5AuthenticatedRequestBindingV2Witness
            for item in observations
        )
    ):
        raise ManagedRunError("managed transport coverage input is invalid")
    authority.__post_init__()
    admission.__post_init__()
    if (
        run_id_sha256 != hashlib.sha256(admission.request.run_id.encode()).hexdigest()
        or admission.ingestion_manifest_sha256 != authority.ingestion_manifest_sha256
        or admission.ingestion_root_sha256 != authority.ingestion_root_sha256
        or admission.ingestion_unit_count != authority.operation_count
        or len(observations) != authority.operation_count
    ):
        raise ManagedRunError("managed transport coverage authority differs")
    receipts = tuple(
        authenticate_managed_mem0_v5_request_binding_v2_witness(item).receipt
        for item in observations
    )
    operation_ids: set[str] = set()
    for unit, observation in zip(authority.units, receipts, strict=True):
        if (
            observation.admission_commitment_sha256 != admission.commitment_sha256
            or observation.unit_identity_sha256 != unit.unit_identity_sha256
            or observation.unit_sha256 != unit.unit_sha256
            or observation.corpus_id != unit.corpus_id
            or observation.source_id != unit.source_id
            or observation.source_sha256 != unit.source_sha256
            or observation.observation_date != unit.observation_date
            or observation.operation_id_sha256 in operation_ids
        ):
            raise ManagedRunError("managed transport coverage observation differs")
        operation_ids.add(observation.operation_id_sha256)
    # LoCoMo transport coverage is exact authority coverage. LongMemEval has the
    # same generic extraction coverage but deliberately makes zero LoCoMo claims.
    snapshots = tuple(_snapshot_from_receipt(receipt) for receipt in receipts)
    if benchmark == "locomo" and sum(count for _, count in _corpus_counts(snapshots)) != len(
        snapshots
    ):
        raise ManagedRunError("managed LoCoMo transport coverage is incomplete")
    return snapshots


def _corpus_counts(
    observations: tuple[_ManagedTransportObservationSnapshot, ...],
) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    order: list[str] = []
    for observation in observations:
        observation.__post_init__(_SNAPSHOT_TOKEN)
        if observation.corpus_id not in counts:
            order.append(observation.corpus_id)
            counts[observation.corpus_id] = 0
        counts[observation.corpus_id] += 1
    return tuple((corpus_id, counts[corpus_id]) for corpus_id in order)


def _snapshot_from_receipt(
    receipt: ManagedMem0V5RequestBindingV2Receipt,
) -> _ManagedTransportObservationSnapshot:
    receipt.__post_init__()
    values = receipt.payload()
    values.pop("schema_version")
    return _ManagedTransportObservationSnapshot(
        **values,
        _authentication_sha256=_snapshot_authentication(receipt),
        _token=_SNAPSHOT_TOKEN,
    )


def _snapshot_authentication(receipt: ManagedMem0V5RequestBindingV2Receipt) -> str:
    return hmac.new(
        _SNAPSHOT_KEY,
        canonical_sha256(receipt.payload()).encode(),
        hashlib.sha256,
    ).hexdigest()


def _text(value: object) -> bool:
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= 512


def _verified_authentication(evidence_commitment_sha256: str) -> str:
    return hmac.new(
        _VERIFIED_KEY,
        evidence_commitment_sha256.encode(),
        hashlib.sha256,
    ).hexdigest()


__all__ = (
    "ManagedTransportCoverageCapability",
    "ManagedTransportCoverageCapabilityPort",
    "VerifiedManagedTransportCoverage",
    "authenticate_managed_transport_coverage",
    "issue_managed_transport_coverage_capability",
)
