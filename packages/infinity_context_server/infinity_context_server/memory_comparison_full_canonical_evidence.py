"""Sealed evidence from Infinity's canonical lifecycle and direct readback."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import secrets
import threading
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, final

from infinity_context_server import (
    memory_comparison_full_canonical_source_evidence_trust as _trust,
)

CANONICAL_EVIDENCE_SCHEMA_VERSION = "memory-comparison-full-canonical-evidence.v1"
INFINITY_CANONICAL_BACKEND_ID = "infinity-context"
_MAX_TEXT = 16_384
_TOKEN = object()
_LOCK = threading.RLock()


class CanonicalEvidenceError(ValueError):
    """Raised when canonical evidence cannot establish a valid binding."""


@final
class CanonicalEvidenceRequest:
    __slots__ = (
        "run_id",
        "profile_id",
        "backend_id",
        "scope_id",
        "case_id",
        "source_ref",
        "minimum_generation",
        "minimum_watermark",
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
        minimum_generation: int,
        minimum_watermark: int,
        _token: object,
    ) -> None:
        if _token is not _TOKEN:
            raise CanonicalEvidenceError("canonical requests must be issued")
        self.run_id = run_id
        self.profile_id = profile_id
        self.backend_id = backend_id
        self.scope_id = scope_id
        self.case_id = case_id
        self.source_ref = source_ref
        self.minimum_generation = minimum_generation
        self.minimum_watermark = minimum_watermark

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalEvidenceRequest is final")

    def __repr__(self) -> str:
        return "CanonicalEvidenceRequest(<bound>)"

    def __reduce__(self) -> object:
        raise TypeError("CanonicalEvidenceRequest is nonserializable")


@final
@dataclass(frozen=True, slots=True)
class CanonicalLifecycleReceipt:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    canonical_record_id: str
    status: str
    generation: int
    watermark: int
    derived_only: bool

    def __post_init__(self) -> None:
        _validate_receipt_fields(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalLifecycleReceipt is final")


@final
@dataclass(frozen=True, slots=True)
class CanonicalReadbackReceipt:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    canonical_record_id: str
    status: str
    generation: int
    watermark: int
    found: bool
    derived_only: bool

    def __post_init__(self) -> None:
        _validate_receipt_fields(self)
        if type(self.found) is not bool:
            raise CanonicalEvidenceError("found must be an exact bool")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalReadbackReceipt is final")


class CanonicalLifecycleEvidencePort(Protocol):
    def observe_lifecycle(
        self,
        request: CanonicalEvidenceRequest,
    ) -> CanonicalLifecycleReceipt: ...


class CanonicalReadbackEvidencePort(Protocol):
    def read_canonical(
        self,
        request: CanonicalEvidenceRequest,
        *,
        canonical_record_id: str,
    ) -> CanonicalReadbackReceipt: ...


@final
class CanonicalEvidenceSession:
    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise CanonicalEvidenceError("canonical sessions must be issued")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalEvidenceSession is final")

    def __repr__(self) -> str:
        return "CanonicalEvidenceSession(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("CanonicalEvidenceSession is nonserializable")


@final
class VerifiedCanonicalEvidence:
    """Opaque component proof; external admission needs composite policy consume."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise CanonicalEvidenceError("canonical evidence must be sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("VerifiedCanonicalEvidence is final")

    def __repr__(self) -> str:
        return "VerifiedCanonicalEvidence(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("VerifiedCanonicalEvidence is nonserializable")


@dataclass(frozen=True, slots=True)
class _Binding:
    run_id: str
    profile_id: str
    backend_id: str
    scope_id: str
    case_id: str
    source_ref: str
    minimum_generation: int
    minimum_watermark: int


@dataclass(slots=True)
class _SessionState:
    binding: _Binding
    request: CanonicalEvidenceRequest
    lifecycle_port: CanonicalLifecycleEvidencePort
    readback_port: CanonicalReadbackEvidencePort
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


_SESSIONS: weakref.WeakKeyDictionary[CanonicalEvidenceSession, _SessionState] = (
    weakref.WeakKeyDictionary()
)
_PROOFS: weakref.WeakKeyDictionary[VerifiedCanonicalEvidence, _ProofState] = (
    weakref.WeakKeyDictionary()
)


def issue_canonical_evidence_session(
    *,
    run_id: str,
    profile_id: str,
    backend_id: str,
    scope_id: str,
    case_id: str,
    source_ref: str,
    minimum_generation: int,
    minimum_watermark: int,
    lifecycle_port: CanonicalLifecycleEvidencePort,
    readback_port: CanonicalReadbackEvidencePort,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> CanonicalEvidenceSession:
    binding = _Binding(
        _text(run_id, "run_id"),
        _text(profile_id, "profile_id"),
        _text(backend_id, "backend_id"),
        _text(scope_id, "scope_id"),
        _text(case_id, "case_id"),
        _text(source_ref, "source_ref"),
        _positive_int(minimum_generation, "minimum_generation"),
        _positive_int(minimum_watermark, "minimum_watermark"),
    )
    if binding.backend_id != INFINITY_CANONICAL_BACKEND_ID:
        raise CanonicalEvidenceError("canonical evidence requires the Infinity backend")
    port_bindings = (lifecycle_port, readback_port)
    trust_lease = _reserve_policy(
        trust_policy,
        port_bindings=port_bindings,
        backend_id=binding.backend_id,
    )
    request = CanonicalEvidenceRequest(
        run_id=binding.run_id,
        profile_id=binding.profile_id,
        backend_id=binding.backend_id,
        scope_id=binding.scope_id,
        case_id=binding.case_id,
        source_ref=binding.source_ref,
        minimum_generation=binding.minimum_generation,
        minimum_watermark=binding.minimum_watermark,
        _token=_TOKEN,
    )
    session = CanonicalEvidenceSession(_token=_TOKEN)
    with _LOCK:
        _SESSIONS[session] = _SessionState(
            binding,
            request,
            lifecycle_port,
            readback_port,
            trust_policy,
            trust_lease,
            port_bindings,
            secrets.token_bytes(32),
            "issued",
        )
    return session


def seal_canonical_evidence(
    session: CanonicalEvidenceSession,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> VerifiedCanonicalEvidence:
    if type(session) is not CanonicalEvidenceSession:
        raise CanonicalEvidenceError("canonical session type must be exact")
    with _LOCK:
        state = _SESSIONS.get(session)
        if state is None or state.phase != "issued" or state.trust_policy is not trust_policy:
            raise CanonicalEvidenceError("canonical session or trust policy is not live")
        state.phase = "observing"
    try:
        _begin_policy(state)
        _validate_request(state.request, state.binding)
        lifecycle = _lifecycle_snapshot(
            state.lifecycle_port.observe_lifecycle(state.request),
            state.binding,
        )
        _validate_request(state.request, state.binding)
        readback = _readback_snapshot(
            state.readback_port.read_canonical(
                state.request,
                canonical_record_id=lifecycle["canonical_record_id"],
            ),
            state.binding,
            lifecycle,
        )
        _validate_request(state.request, state.binding)
        policy_snapshot = _seal_policy(state)
        report = _report(state.binding, lifecycle, readback, policy_snapshot)
        frozen_report = _deep_freeze_report(report)
        commitment = _commitment(state.secret, _thaw(frozen_report))
    except BaseException:
        _fail_policy(state)
        with _LOCK:
            state.phase = "failed"
        raise
    proof = VerifiedCanonicalEvidence(_token=_TOKEN)
    with _LOCK:
        if state.phase != "observing":
            raise CanonicalEvidenceError("canonical session changed during observation")
        state.phase = "sealed"
        _PROOFS[proof] = _ProofState(
            state.binding,
            state.trust_policy,
            state.trust_lease,
            state.port_bindings,
            frozen_report,
            commitment,
            state.secret,
            False,
        )
    return proof


def consume_canonical_evidence(
    proof: VerifiedCanonicalEvidence,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
    run_id: str,
    profile_id: str,
    backend_id: str,
    scope_id: str,
    case_id: str,
    source_ref: str,
) -> dict[str, object]:
    state = _verified_proof(proof, trust_policy=trust_policy)
    supplied = (
        _text(run_id, "run_id"),
        _text(profile_id, "profile_id"),
        _text(backend_id, "backend_id"),
        _text(scope_id, "scope_id"),
        _text(case_id, "case_id"),
        _text(source_ref, "source_ref"),
    )
    bound = (
        state.binding.run_id,
        state.binding.profile_id,
        state.binding.backend_id,
        state.binding.scope_id,
        state.binding.case_id,
        state.binding.source_ref,
    )
    if supplied != bound:
        raise CanonicalEvidenceError("canonical evidence identity does not match")
    with _LOCK:
        current = _verified_proof(proof, trust_policy=trust_policy)
        if current.consumed:
            raise CanonicalEvidenceError("canonical component was already consumed")
        _consume_policy(current)
        current.consumed = True
    return _thaw(current.report)


def public_canonical_evidence_report(
    proof: VerifiedCanonicalEvidence,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> dict[str, object]:
    """Return component telemetry; JSON is never external admission."""

    return _thaw(_verified_proof(proof, trust_policy=trust_policy).report)


def _verified_proof(
    proof: VerifiedCanonicalEvidence,
    *,
    trust_policy: _trust.CanonicalSourceEvidenceTrustPolicy,
) -> _ProofState:
    if type(proof) is not VerifiedCanonicalEvidence:
        raise CanonicalEvidenceError("canonical evidence type must be exact")
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
        raise CanonicalEvidenceError("canonical evidence integrity check failed")
    _validate_policy(state)
    return state


def _reserve_policy(
    policy: _trust.CanonicalSourceEvidenceTrustPolicy,
    *,
    port_bindings: tuple[object, ...],
    backend_id: str,
) -> object:
    try:
        return _trust._reserve_canonical_source_evidence_trust(
            policy,
            lane=_trust.CANONICAL_POLICY_LANE,
            port_bindings=port_bindings,
            backend_ids=(backend_id,),
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise CanonicalEvidenceError("canonical trust policy verification failed") from None


def _begin_policy(state: _SessionState) -> None:
    try:
        _trust._begin_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.CANONICAL_POLICY_LANE,
            port_bindings=state.port_bindings,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise CanonicalEvidenceError("canonical trust policy verification failed") from None


def _seal_policy(state: _SessionState) -> dict[str, object]:
    try:
        return _trust._seal_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.CANONICAL_POLICY_LANE,
            port_bindings=state.port_bindings,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise CanonicalEvidenceError("canonical trust policy verification failed") from None


def _fail_policy(state: _SessionState) -> None:
    with contextlib.suppress(_trust.CanonicalSourceEvidenceTrustError):
        _trust._fail_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.CANONICAL_POLICY_LANE,
            port_bindings=state.port_bindings,
        )


def _validate_policy(state: _ProofState) -> None:
    try:
        snapshot = _trust._validate_canonical_source_evidence_trust(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.CANONICAL_POLICY_LANE,
            port_bindings=state.port_bindings,
            phases=("sealed", "component_consumed"),
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise CanonicalEvidenceError("canonical trust policy verification failed") from None
    if snapshot != _sealed_policy_snapshot(state.report):
        raise CanonicalEvidenceError("canonical trust policy snapshot changed")


def _consume_policy(state: _ProofState) -> None:
    try:
        snapshot = _trust._consume_canonical_source_evidence_trust_component(
            state.trust_policy,
            state.trust_lease,
            lane=_trust.CANONICAL_POLICY_LANE,
            port_bindings=state.port_bindings,
        )
    except _trust.CanonicalSourceEvidenceTrustError:
        raise CanonicalEvidenceError("canonical trust policy verification failed") from None
    if snapshot != _sealed_policy_snapshot(state.report):
        raise CanonicalEvidenceError("canonical trust policy snapshot changed")


def _lifecycle_snapshot(
    receipt: CanonicalLifecycleReceipt,
    binding: _Binding,
) -> dict[str, object]:
    if type(receipt) is not CanonicalLifecycleReceipt:
        raise CanonicalEvidenceError("lifecycle receipt type must be exact")
    receipt.__post_init__()
    _validate_identity(receipt, binding)
    _validate_active(receipt, binding)
    return {
        "canonical_record_id": _text(receipt.canonical_record_id, "canonical_record_id"),
        "generation": receipt.generation,
        "status": receipt.status,
        "watermark": receipt.watermark,
    }


def _readback_snapshot(
    receipt: CanonicalReadbackReceipt,
    binding: _Binding,
    lifecycle: dict[str, object],
) -> dict[str, object]:
    if type(receipt) is not CanonicalReadbackReceipt:
        raise CanonicalEvidenceError("readback receipt type must be exact")
    receipt.__post_init__()
    _validate_identity(receipt, binding)
    _validate_active(receipt, binding)
    if receipt.found is not True:
        raise CanonicalEvidenceError("canonical readback did not find the record")
    if receipt.canonical_record_id != lifecycle["canonical_record_id"]:
        raise CanonicalEvidenceError("readback record does not match lifecycle")
    if receipt.generation < lifecycle["generation"] or receipt.watermark < lifecycle["watermark"]:
        raise CanonicalEvidenceError("canonical readback is stale relative to lifecycle")
    return {
        "canonical_record_id": receipt.canonical_record_id,
        "found": True,
        "generation": receipt.generation,
        "status": receipt.status,
        "watermark": receipt.watermark,
    }


def _validate_identity(receipt: object, binding: _Binding) -> None:
    values = tuple(
        getattr(receipt, name, None)
        for name in ("run_id", "profile_id", "backend_id", "scope_id", "case_id", "source_ref")
    )
    if any(type(value) is not str for value in values) or values != (
        binding.run_id,
        binding.profile_id,
        binding.backend_id,
        binding.scope_id,
        binding.case_id,
        binding.source_ref,
    ):
        raise CanonicalEvidenceError("canonical receipt identity does not match")


def _validate_active(receipt: object, binding: _Binding) -> None:
    if receipt.status != "active":
        raise CanonicalEvidenceError("canonical record is deleted, superseded, or inactive")
    if receipt.derived_only is not False:
        raise CanonicalEvidenceError("derived-only evidence cannot prove canonical storage")
    generation = receipt.generation
    watermark = receipt.watermark
    if type(generation) is not int or generation < binding.minimum_generation:
        raise CanonicalEvidenceError("canonical generation is stale")
    if type(watermark) is not int or watermark < binding.minimum_watermark:
        raise CanonicalEvidenceError("canonical watermark is stale")


def _validate_request(request: CanonicalEvidenceRequest, binding: _Binding) -> None:
    values = (
        request.run_id,
        request.profile_id,
        request.backend_id,
        request.scope_id,
        request.case_id,
        request.source_ref,
        request.minimum_generation,
        request.minimum_watermark,
    )
    if (
        type(request) is not CanonicalEvidenceRequest
        or any(type(value) is not str for value in values[:6])
        or type(values[6]) is not int
        or type(values[7]) is not int
        or values
        != (
            binding.run_id,
            binding.profile_id,
            binding.backend_id,
            binding.scope_id,
            binding.case_id,
            binding.source_ref,
            binding.minimum_generation,
            binding.minimum_watermark,
        )
    ):
        raise CanonicalEvidenceError("canonical request integrity check failed")


def _validate_receipt_fields(receipt: object) -> None:
    for name in (
        "run_id",
        "profile_id",
        "backend_id",
        "scope_id",
        "case_id",
        "source_ref",
        "canonical_record_id",
        "status",
    ):
        _text(getattr(receipt, name), name)
    if type(receipt.generation) is not int:
        raise CanonicalEvidenceError("generation must be an exact integer")
    if type(receipt.watermark) is not int:
        raise CanonicalEvidenceError("watermark must be an exact integer")
    if type(receipt.derived_only) is not bool:
        raise CanonicalEvidenceError("derived_only must be an exact bool")


def _report(
    binding: _Binding,
    lifecycle: dict[str, object],
    readback: dict[str, object],
    policy_snapshot: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": CANONICAL_EVIDENCE_SCHEMA_VERSION,
        "run_id": binding.run_id,
        "profile_id": binding.profile_id,
        "backend_id": binding.backend_id,
        "scope_id": binding.scope_id,
        "case_id": binding.case_id,
        "source_ref": binding.source_ref,
        "lifecycle": dict(lifecycle),
        "readback": dict(readback),
        "trust_policy": policy_snapshot,
        "component_only": True,
        "externally_authentic": False,
        "composite_policy_consume_required": True,
        "admission_from_public_json": False,
    }


def _commitment(secret: bytes, report: dict[str, object]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _deep_freeze_report(value: object, *, depth: int = 0) -> MappingProxyType:
    frozen = _deep_freeze_value(value, depth=depth)
    if type(frozen) is not MappingProxyType:
        raise CanonicalEvidenceError("canonical report root must be an exact mapping")
    return frozen


def _deep_freeze_value(value: object, *, depth: int) -> object:
    if depth > 16:
        raise CanonicalEvidenceError("canonical report nesting is too deep")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise CanonicalEvidenceError("canonical report float must be finite")
        return value
    if type(value) is dict:
        if len(value) > 1_000:
            raise CanonicalEvidenceError("canonical report mapping is too large")
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or key != key.strip():
                raise CanonicalEvidenceError("canonical report keys must be exact strings")
            frozen[key] = _deep_freeze_value(item, depth=depth + 1)
        return MappingProxyType(frozen)
    if type(value) in {list, tuple}:
        if len(value) > 1_000:
            raise CanonicalEvidenceError("canonical report sequence is too large")
        return tuple(_deep_freeze_value(item, depth=depth + 1) for item in value)
    raise CanonicalEvidenceError("canonical report contains a non-JSON exact type")


def _thaw(value: object) -> dict[str, object]:
    thawed = _thaw_value(value, depth=0)
    if type(thawed) is not dict:
        raise CanonicalEvidenceError("canonical report root must be an exact mapping")
    return thawed


def _thaw_value(value: object, *, depth: int) -> object:
    if depth > 16:
        raise CanonicalEvidenceError("canonical report nesting is too deep")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise CanonicalEvidenceError("canonical report float must be finite")
        return value
    if type(value) in {dict, MappingProxyType}:
        if len(value) > 1_000:
            raise CanonicalEvidenceError("canonical report mapping is too large")
        thawed: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or key != key.strip():
                raise CanonicalEvidenceError("canonical report keys must be exact strings")
            thawed[key] = _thaw_value(item, depth=depth + 1)
        return thawed
    if type(value) in {list, tuple}:
        if len(value) > 1_000:
            raise CanonicalEvidenceError("canonical report sequence is too large")
        return [_thaw_value(item, depth=depth + 1) for item in value]
    raise CanonicalEvidenceError("canonical report contains a non-JSON exact type")


def _sealed_policy_snapshot(report: MappingProxyType[str, object]) -> dict[str, object]:
    snapshot = report.get("trust_policy")
    thawed = _thaw_value(snapshot, depth=0)
    if type(thawed) is not dict:
        raise CanonicalEvidenceError("canonical trust policy snapshot type changed")
    return thawed


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > _MAX_TEXT:
        raise CanonicalEvidenceError(f"{name} must be a bounded nonblank exact string")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise CanonicalEvidenceError(f"{name} must be a positive exact integer")
    return value


__all__ = (
    "CANONICAL_EVIDENCE_SCHEMA_VERSION",
    "INFINITY_CANONICAL_BACKEND_ID",
    "CanonicalEvidenceError",
    "CanonicalEvidenceRequest",
    "CanonicalEvidenceSession",
    "CanonicalLifecycleEvidencePort",
    "CanonicalLifecycleReceipt",
    "CanonicalReadbackEvidencePort",
    "CanonicalReadbackReceipt",
    "VerifiedCanonicalEvidence",
    "consume_canonical_evidence",
    "public_canonical_evidence_report",
    "seal_canonical_evidence",
)
