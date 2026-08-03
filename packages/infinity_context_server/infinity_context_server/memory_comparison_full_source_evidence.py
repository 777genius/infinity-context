"""Sealed source-lineage evidence for Infinity and truthful Mem0 observations."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, final

from infinity_context_server import (
    memory_comparison_full_canonical_source_evidence_trust as _trust,
)

SOURCE_EVIDENCE_SCHEMA_VERSION = "memory-comparison-full-source-evidence.v1"
INFINITY_SOURCE_BACKEND_ID = "infinity-context"
MEM0_SOURCE_BACKEND_ID = "mem0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 16_384
_TOKEN = object()
_LOCK = threading.RLock()


class SourceEvidenceError(ValueError):
    """Raised when source observations do not establish exact lineage."""


@final
class SourceEvidenceRequest:
    __slots__ = (
        "run_id",
        "profile_id",
        "backend_id",
        "scope_id",
        "case_id",
        "source_ref",
        "source_revision",
        "source_sha256",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        run_id: str,
        profile_id: str,
        backend_id: str,
        scope_id: str,
        case_id: str,
        source_ref: str,
        source_revision: int,
        source_sha256: str,
        _token: object,
    ) -> None:
        if _token is not _TOKEN:
            raise SourceEvidenceError("source requests must be issued")
        self.run_id = run_id
        self.profile_id = profile_id
        self.backend_id = backend_id
        self.scope_id = scope_id
        self.case_id = case_id
        self.source_ref = source_ref
        self.source_revision = source_revision
        self.source_sha256 = source_sha256

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("SourceEvidenceRequest is final")

    def __repr__(self) -> str:
        return "SourceEvidenceRequest(<bound>)"

    def __reduce__(self) -> object:
        raise TypeError("SourceEvidenceRequest is nonserializable")


@final
@dataclass(frozen=True, slots=True)
class InfinityRetrievedSourceReceipt:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str
    retrieved_item_id: str
    ingestion_id: str
    derived_only: bool

    def __post_init__(self) -> None:
        _validate_common_receipt(self)
        _text(self.retrieved_item_id, "retrieved_item_id")
        _text(self.ingestion_id, "ingestion_id")
        if type(self.derived_only) is not bool:
            raise SourceEvidenceError("derived_only must be an exact bool")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("InfinityRetrievedSourceReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class InfinityIngestedSourceReceipt:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str
    ingestion_id: str
    present: bool
    deleted: bool

    def __post_init__(self) -> None:
        _validate_common_receipt(self)
        _text(self.ingestion_id, "ingestion_id")
        if type(self.present) is not bool or type(self.deleted) is not bool:
            raise SourceEvidenceError("source state flags must be exact bools")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("InfinityIngestedSourceReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class Mem0SourceRequestReceipt:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str
    request_id: str
    accepted: bool

    def __post_init__(self) -> None:
        _validate_common_receipt(self)
        _text(self.request_id, "request_id")
        if type(self.accepted) is not bool:
            raise SourceEvidenceError("accepted must be an exact bool")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Mem0SourceRequestReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class Mem0SourceReadbackReceipt:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str
    request_id: str
    memory_item_id: str
    found: bool

    def __post_init__(self) -> None:
        _validate_common_receipt(self)
        _text(self.request_id, "request_id")
        _text(self.memory_item_id, "memory_item_id")
        if type(self.found) is not bool:
            raise SourceEvidenceError("found must be an exact bool")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("Mem0SourceReadbackReceipt is final")


class InfinityRetrievedSourcePort(Protocol):
    def retrieve_source(
        self,
        request: SourceEvidenceRequest,
    ) -> InfinityRetrievedSourceReceipt: ...


class InfinityIngestedSourcePort(Protocol):
    def read_ingested_source(
        self,
        request: SourceEvidenceRequest,
        *,
        ingestion_id: str,
    ) -> InfinityIngestedSourceReceipt: ...


class Mem0SourceRequestPort(Protocol):
    def observe_source_request(
        self,
        request: SourceEvidenceRequest,
    ) -> Mem0SourceRequestReceipt: ...


class Mem0SourceReadbackPort(Protocol):
    def read_source_result(
        self,
        request: SourceEvidenceRequest,
        *,
        request_id: str,
    ) -> Mem0SourceReadbackReceipt: ...


@final
class SourceEvidenceSession:
    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise SourceEvidenceError("source sessions must be issued")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("SourceEvidenceSession is final")

    def __repr__(self) -> str:
        return "SourceEvidenceSession(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("SourceEvidenceSession is nonserializable")


@final
class VerifiedSourceEvidence:
    """Opaque component proof; external admission needs composite policy consume."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise SourceEvidenceError("source evidence must be sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("VerifiedSourceEvidence is final")

    def __repr__(self) -> str:
        return "VerifiedSourceEvidence(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("VerifiedSourceEvidence is nonserializable")


@dataclass(frozen=True, slots=True)
class _Binding:
    run_id: str
    profile_id: str
    scope_id: str
    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str
    infinity_backend_id: str
    mem0_backend_id: str


@dataclass(slots=True)
class _SessionState:
    binding: _Binding
    infinity_request: SourceEvidenceRequest
    mem0_request: SourceEvidenceRequest
    retrieved_port: InfinityRetrievedSourcePort
    ingested_port: InfinityIngestedSourcePort
    mem0_request_port: Mem0SourceRequestPort
    mem0_readback_port: Mem0SourceReadbackPort
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy
    trust_lease: object
    port_bindings: tuple[object, ...]
    secret: bytes
    phase: str


@dataclass(slots=True)
class _ProofState:
    binding: _Binding
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy
    trust_lease: object
    port_bindings: tuple[object, ...]
    report: MappingProxyType[str, object]
    commitment: str
    secret: bytes
    consumed: bool


_SESSIONS: weakref.WeakKeyDictionary[SourceEvidenceSession, _SessionState] = (
    weakref.WeakKeyDictionary()
)
_PROOFS: weakref.WeakKeyDictionary[VerifiedSourceEvidence, _ProofState] = (
    weakref.WeakKeyDictionary()
)


def issue_source_evidence_session(
    *,
    run_id: str,
    profile_id: str,
    scope_id: str,
    case_id: str,
    source_ref: str,
    source_revision: int,
    source_sha256: str,
    infinity_backend_id: str,
    mem0_backend_id: str,
    retrieved_port: InfinityRetrievedSourcePort,
    ingested_port: InfinityIngestedSourcePort,
    mem0_request_port: Mem0SourceRequestPort,
    mem0_readback_port: Mem0SourceReadbackPort,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> SourceEvidenceSession:
    binding = _Binding(
        _text(run_id, "run_id"),
        _text(profile_id, "profile_id"),
        _text(scope_id, "scope_id"),
        _text(case_id, "case_id"),
        _text(source_ref, "source_ref"),
        _positive_int(source_revision, "source_revision"),
        _digest(source_sha256),
        _text(infinity_backend_id, "infinity_backend_id"),
        _text(mem0_backend_id, "mem0_backend_id"),
    )
    if (
        binding.infinity_backend_id != INFINITY_SOURCE_BACKEND_ID
        or binding.mem0_backend_id != MEM0_SOURCE_BACKEND_ID
    ):
        raise SourceEvidenceError("source evidence backend identity is invalid")
    port_bindings = (
        retrieved_port,
        ingested_port,
        mem0_request_port,
        mem0_readback_port,
    )
    trust_lease = _reserve_policy(
        trust_policy,
        port_bindings=port_bindings,
        backend_ids=(binding.infinity_backend_id, binding.mem0_backend_id),
    )
    infinity_request = _request(binding, binding.infinity_backend_id)
    mem0_request = _request(binding, binding.mem0_backend_id)
    session = SourceEvidenceSession(_token=_TOKEN)
    with _LOCK:
        _SESSIONS[session] = _SessionState(
            binding,
            infinity_request,
            mem0_request,
            retrieved_port,
            ingested_port,
            mem0_request_port,
            mem0_readback_port,
            trust_policy,
            trust_lease,
            port_bindings,
            secrets.token_bytes(32),
            "issued",
        )
    return session


def seal_source_evidence(
    session: SourceEvidenceSession,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> VerifiedSourceEvidence:
    if type(session) is not SourceEvidenceSession:
        raise SourceEvidenceError("source session type must be exact")
    with _LOCK:
        state = _SESSIONS.get(session)
        if state is None or state.phase != "issued" or state.trust_policy is not trust_policy:
            raise SourceEvidenceError("source session or trust policy is not live")
        state.phase = "observing"
    try:
        _begin_policy(state)
        _validate_request(state.infinity_request, state.binding, INFINITY_SOURCE_BACKEND_ID)
        retrieved = _retrieved_snapshot(
            state.retrieved_port.retrieve_source(state.infinity_request),
            state.binding,
        )
        _validate_request(state.infinity_request, state.binding, INFINITY_SOURCE_BACKEND_ID)
        ingested = _ingested_snapshot(
            state.ingested_port.read_ingested_source(
                state.infinity_request,
                ingestion_id=retrieved["ingestion_id"],
            ),
            state.binding,
            retrieved,
        )
        _validate_request(state.infinity_request, state.binding, INFINITY_SOURCE_BACKEND_ID)
        _validate_request(state.mem0_request, state.binding, MEM0_SOURCE_BACKEND_ID)
        request_receipt = _mem0_request_snapshot(
            state.mem0_request_port.observe_source_request(state.mem0_request),
            state.binding,
        )
        _validate_request(state.mem0_request, state.binding, MEM0_SOURCE_BACKEND_ID)
        readback = _mem0_readback_snapshot(
            state.mem0_readback_port.read_source_result(
                state.mem0_request,
                request_id=request_receipt["request_id"],
            ),
            state.binding,
            request_receipt,
        )
        _validate_request(state.mem0_request, state.binding, MEM0_SOURCE_BACKEND_ID)
        policy_snapshot = _seal_policy(state)
        report = _report(
            state.binding,
            retrieved,
            ingested,
            request_receipt,
            readback,
            policy_snapshot,
        )
        commitment = _commitment(state.secret, report)
    except BaseException:
        _fail_policy(state)
        with _LOCK:
            state.phase = "failed"
        raise
    proof = VerifiedSourceEvidence(_token=_TOKEN)
    with _LOCK:
        if state.phase != "observing":
            raise SourceEvidenceError("source session changed during observation")
        state.phase = "sealed"
        _PROOFS[proof] = _ProofState(
            state.binding,
            state.trust_policy,
            state.trust_lease,
            state.port_bindings,
            MappingProxyType(report),
            commitment,
            state.secret,
            False,
        )
    return proof


def consume_source_evidence(
    proof: VerifiedSourceEvidence,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
    run_id: str,
    profile_id: str,
    scope_id: str,
    case_id: str,
    source_ref: str,
    source_revision: int,
    source_sha256: str,
    infinity_backend_id: str,
    mem0_backend_id: str,
) -> dict[str, object]:
    state = _verified_proof(proof, trust_policy=trust_policy)
    supplied = (
        _text(run_id, "run_id"),
        _text(profile_id, "profile_id"),
        _text(scope_id, "scope_id"),
        _text(case_id, "case_id"),
        _text(source_ref, "source_ref"),
        _positive_int(source_revision, "source_revision"),
        _digest(source_sha256),
        _text(infinity_backend_id, "infinity_backend_id"),
        _text(mem0_backend_id, "mem0_backend_id"),
    )
    bound = (
        state.binding.run_id,
        state.binding.profile_id,
        state.binding.scope_id,
        state.binding.case_id,
        state.binding.source_ref,
        state.binding.source_revision,
        state.binding.source_sha256,
        state.binding.infinity_backend_id,
        state.binding.mem0_backend_id,
    )
    if supplied != bound:
        raise SourceEvidenceError("source evidence identity does not match")
    with _LOCK:
        current = _verified_proof(proof, trust_policy=trust_policy)
        if current.consumed:
            raise SourceEvidenceError("source component was already consumed")
        _consume_policy(current)
        current.consumed = True
    return _thaw(current.report)


def public_source_evidence_report(
    proof: VerifiedSourceEvidence,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> dict[str, object]:
    """Return component telemetry; JSON is never external admission."""

    return _thaw(_verified_proof(proof, trust_policy=trust_policy).report)


def _reserve_policy(
    policy: _trust.CanonicalSourceEvidenceTrustPolicy,
    *,
    port_bindings: tuple[object, ...],
    backend_ids: tuple[str, ...],
) -> object:
    try:
        return _trust._reserve_canonical_source_evidence_trust(
            policy,
            lane=_trust.SOURCE_POLICY_LANE,
            port_bindings=port_bindings,
            backend_ids=backend_ids,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise SourceEvidenceError("source trust policy verification failed") from None


def _begin_policy(state: _SessionState) -> None:
    try:
        _trust._begin_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.SOURCE_POLICY_LANE,
            port_bindings=state.port_bindings,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise SourceEvidenceError("source trust policy verification failed") from None


def _seal_policy(state: _SessionState) -> dict[str, object]:
    try:
        return _trust._seal_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.SOURCE_POLICY_LANE,
            port_bindings=state.port_bindings,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise SourceEvidenceError("source trust policy verification failed") from None


def _fail_policy(state: _SessionState) -> None:
    with contextlib.suppress(_trust.CanonicalSourceEvidenceTrustError):
        _trust._fail_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.SOURCE_POLICY_LANE,
            port_bindings=state.port_bindings,
        )


def _validate_policy(state: _ProofState) -> None:
    try:
        snapshot = _trust._validate_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.SOURCE_POLICY_LANE,
            port_bindings=state.port_bindings,
            phases=("sealed", "component_consumed"),
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise SourceEvidenceError("source trust policy verification failed") from None
    if snapshot != state.report.get("trust_policy"):
        raise SourceEvidenceError("source trust policy snapshot changed")


def _consume_policy(state: _ProofState) -> None:
    try:
        snapshot = _trust._consume_canonical_source_evidence_trust_component(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.SOURCE_POLICY_LANE,
            port_bindings=state.port_bindings,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise SourceEvidenceError("source trust policy verification failed") from None
    if snapshot != state.report.get("trust_policy"):
        raise SourceEvidenceError("source trust policy snapshot changed")


def _request(binding: _Binding, backend_id: str) -> SourceEvidenceRequest:
    return SourceEvidenceRequest(
        run_id=binding.run_id,
        profile_id=binding.profile_id,
        backend_id=backend_id,
        scope_id=binding.scope_id,
        case_id=binding.case_id,
        source_ref=binding.source_ref,
        source_revision=binding.source_revision,
        source_sha256=binding.source_sha256,
        _token=_TOKEN,
    )


def _verified_proof(
    proof: VerifiedSourceEvidence,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> _ProofState:
    if type(proof) is not VerifiedSourceEvidence:
        raise SourceEvidenceError("source evidence type must be exact")
    with _LOCK:
        state = _PROOFS.get(proof)
    if (
        state is None
        or state.trust_policy is not trust_policy
        or not hmac.compare_digest(
            state.commitment,
            _commitment(state.secret, _thaw(state.report)),
        )
    ):
        raise SourceEvidenceError("source evidence integrity check failed")
    _validate_policy(state)
    return state


def _retrieved_snapshot(
    receipt: InfinityRetrievedSourceReceipt,
    binding: _Binding,
) -> dict[str, object]:
    if type(receipt) is not InfinityRetrievedSourceReceipt:
        raise SourceEvidenceError("retrieved-source receipt type must be exact")
    receipt.__post_init__()
    _validate_receipt_binding(receipt, binding, INFINITY_SOURCE_BACKEND_ID)
    if receipt.derived_only is not False:
        raise SourceEvidenceError("derived-only retrieval cannot prove source lineage")
    return {
        "retrieved_item_id": receipt.retrieved_item_id,
        "ingestion_id": receipt.ingestion_id,
        "source_ref": receipt.source_ref,
        "source_revision": receipt.source_revision,
        "source_sha256": receipt.source_sha256,
    }


def _ingested_snapshot(
    receipt: InfinityIngestedSourceReceipt,
    binding: _Binding,
    retrieved: dict[str, object],
) -> dict[str, object]:
    if type(receipt) is not InfinityIngestedSourceReceipt:
        raise SourceEvidenceError("ingested-source receipt type must be exact")
    receipt.__post_init__()
    _validate_receipt_binding(receipt, binding, INFINITY_SOURCE_BACKEND_ID)
    if receipt.present is not True or receipt.deleted is not False:
        raise SourceEvidenceError("ingested source is missing or deleted")
    if receipt.ingestion_id != retrieved["ingestion_id"]:
        raise SourceEvidenceError("retrieved item does not bind to the ingested source")
    return {
        "ingestion_id": receipt.ingestion_id,
        "present": True,
        "deleted": False,
        "source_ref": receipt.source_ref,
        "source_revision": receipt.source_revision,
        "source_sha256": receipt.source_sha256,
    }


def _mem0_request_snapshot(
    receipt: Mem0SourceRequestReceipt,
    binding: _Binding,
) -> dict[str, object]:
    if type(receipt) is not Mem0SourceRequestReceipt:
        raise SourceEvidenceError("Mem0 request receipt type must be exact")
    receipt.__post_init__()
    _validate_receipt_binding(receipt, binding, MEM0_SOURCE_BACKEND_ID)
    if receipt.accepted is not True:
        raise SourceEvidenceError("Mem0 source request was not accepted")
    return {"request_id": receipt.request_id, "accepted": True}


def _mem0_readback_snapshot(
    receipt: Mem0SourceReadbackReceipt,
    binding: _Binding,
    request_receipt: dict[str, object],
) -> dict[str, object]:
    if type(receipt) is not Mem0SourceReadbackReceipt:
        raise SourceEvidenceError("Mem0 readback receipt type must be exact")
    receipt.__post_init__()
    _validate_receipt_binding(receipt, binding, MEM0_SOURCE_BACKEND_ID)
    if receipt.found is not True:
        raise SourceEvidenceError("Mem0 source readback did not find an item")
    if receipt.request_id != request_receipt["request_id"]:
        raise SourceEvidenceError("Mem0 readback does not bind to its request")
    return {
        "request_id": receipt.request_id,
        "memory_item_id": receipt.memory_item_id,
        "found": True,
        "source_ref": receipt.source_ref,
        "source_revision": receipt.source_revision,
        "source_sha256": receipt.source_sha256,
    }


def _validate_receipt_binding(receipt: object, binding: _Binding, backend_id: str) -> None:
    values = tuple(
        getattr(receipt, name, None)
        for name in (
            "run_id",
            "profile_id",
            "backend_id",
            "scope_id",
            "case_id",
            "source_ref",
            "source_revision",
            "source_sha256",
        )
    )
    if any(type(value) is not str for value in values[:6] + values[7:]):
        raise SourceEvidenceError("source receipt identity has invalid types")
    if type(values[6]) is not int or values != (
        binding.run_id,
        binding.profile_id,
        backend_id,
        binding.scope_id,
        binding.case_id,
        binding.source_ref,
        binding.source_revision,
        binding.source_sha256,
    ):
        raise SourceEvidenceError("source receipt identity does not match")


def _validate_request(
    request: SourceEvidenceRequest,
    binding: _Binding,
    backend_id: str,
) -> None:
    values = (
        request.run_id,
        request.profile_id,
        request.backend_id,
        request.scope_id,
        request.case_id,
        request.source_ref,
        request.source_revision,
        request.source_sha256,
    )
    if (
        type(request) is not SourceEvidenceRequest
        or any(type(value) is not str for value in values[:6] + values[7:])
        or type(values[6]) is not int
        or values
        != (
            binding.run_id,
            binding.profile_id,
            backend_id,
            binding.scope_id,
            binding.case_id,
            binding.source_ref,
            binding.source_revision,
            binding.source_sha256,
        )
    ):
        raise SourceEvidenceError("source request integrity check failed")


def _validate_common_receipt(receipt: object) -> None:
    for name in (
        "run_id",
        "profile_id",
        "backend_id",
        "scope_id",
        "case_id",
        "source_ref",
    ):
        _text(getattr(receipt, name), name)
    _positive_int(receipt.source_revision, "source_revision")
    _digest(receipt.source_sha256)


def _report(
    binding: _Binding,
    retrieved: dict[str, object],
    ingested: dict[str, object],
    request_receipt: dict[str, object],
    readback: dict[str, object],
    policy_snapshot: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": SOURCE_EVIDENCE_SCHEMA_VERSION,
        "run_id": binding.run_id,
        "profile_id": binding.profile_id,
        "scope_id": binding.scope_id,
        "case_id": binding.case_id,
        "source_ref": binding.source_ref,
        "source_revision": binding.source_revision,
        "source_sha256": binding.source_sha256,
        "infinity_backend_id": binding.infinity_backend_id,
        "mem0_backend_id": binding.mem0_backend_id,
        "infinity_source_binding": {
            "retrieved": retrieved,
            "ingested": ingested,
        },
        "mem0_source_witness": {
            "request": request_receipt,
            "readback": readback,
        },
        "trust_policy": policy_snapshot,
        "component_only": True,
        "externally_authentic": False,
        "composite_policy_consume_required": True,
        "admission_from_public_json": False,
    }


def _commitment(secret: bytes, report: dict[str, object]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _thaw(value: MappingProxyType[str, object] | dict[str, object]) -> dict[str, object]:
    def copy(item: object) -> object:
        if type(item) in {dict, MappingProxyType}:
            return {key: copy(child) for key, child in item.items()}
        return item

    return {key: copy(item) for key, item in value.items()}


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > _MAX_TEXT:
        raise SourceEvidenceError(f"{name} must be a bounded nonblank exact string")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise SourceEvidenceError(f"{name} must be a positive exact integer")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise SourceEvidenceError("source_sha256 must be lowercase sha256")
    return value


__all__ = (
    "INFINITY_SOURCE_BACKEND_ID",
    "MEM0_SOURCE_BACKEND_ID",
    "SOURCE_EVIDENCE_SCHEMA_VERSION",
    "InfinityIngestedSourcePort",
    "InfinityIngestedSourceReceipt",
    "InfinityRetrievedSourcePort",
    "InfinityRetrievedSourceReceipt",
    "Mem0SourceReadbackPort",
    "Mem0SourceReadbackReceipt",
    "Mem0SourceRequestPort",
    "Mem0SourceRequestReceipt",
    "SourceEvidenceError",
    "SourceEvidenceRequest",
    "SourceEvidenceSession",
    "VerifiedSourceEvidence",
    "consume_source_evidence",
    "public_source_evidence_report",
    "seal_source_evidence",
)
