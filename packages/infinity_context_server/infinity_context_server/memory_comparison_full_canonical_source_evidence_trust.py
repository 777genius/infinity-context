"""Composition-root trust capability for canonical and source evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import final

TRUST_POLICY_SCHEMA_VERSION = "memory-comparison-canonical-source-trust.v1"
CANONICAL_POLICY_LANE = "canonical"
SOURCE_POLICY_LANE = "source"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 16_384
_TOKEN = object()
_LOCK = threading.RLock()


class CanonicalSourceEvidenceTrustError(ValueError):
    """Raised when evidence is detached from its composition-root policy."""


@final
class CanonicalSourceEvidenceTrustPolicy:
    """Opaque policy issued only by the trusted composition root."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise CanonicalSourceEvidenceTrustError(
                "trust policies must be composition-root issued"
            )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("CanonicalSourceEvidenceTrustPolicy is final")

    def __repr__(self) -> str:
        return "CanonicalSourceEvidenceTrustPolicy(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("CanonicalSourceEvidenceTrustPolicy is nonserializable")


@final
class _CanonicalSourceEvidenceTrustLease:
    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise CanonicalSourceEvidenceTrustError("trust leases must be policy issued")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("_CanonicalSourceEvidenceTrustLease is final")

    def __reduce__(self) -> object:
        raise TypeError("trust leases are nonserializable")


@dataclass(frozen=True, slots=True)
class _PolicySnapshot:
    policy_id: str
    canonical_backend_id: str
    infinity_source_backend_id: str
    mem0_source_backend_id: str
    canonical_adapter_id: str
    infinity_source_adapter_id: str
    mem0_source_adapter_id: str
    canonical_implementation_sha256: str
    infinity_source_implementation_sha256: str
    mem0_source_implementation_sha256: str
    runtime_attestation_commitment: str


@dataclass(slots=True)
class _PolicyState:
    snapshot: _PolicySnapshot
    port_bindings: tuple[object, ...]
    secret: bytes
    commitment: str
    lanes: dict[str, _CanonicalSourceEvidenceTrustLease]


@dataclass(slots=True)
class _LeaseState:
    policy: CanonicalSourceEvidenceTrustPolicy
    lane: str
    port_bindings: tuple[object, ...]
    policy_commitment: str
    phase: str


def _build_trust_policy_api() -> tuple[Callable[..., object], ...]:
    """Keep authority registries outside module reach."""

    policies: weakref.WeakKeyDictionary[CanonicalSourceEvidenceTrustPolicy, _PolicyState] = (
        weakref.WeakKeyDictionary()
    )
    leases: weakref.WeakKeyDictionary[_CanonicalSourceEvidenceTrustLease, _LeaseState] = (
        weakref.WeakKeyDictionary()
    )

    def verified_policy(policy: CanonicalSourceEvidenceTrustPolicy) -> _PolicyState:
        if type(policy) is not CanonicalSourceEvidenceTrustPolicy:
            raise CanonicalSourceEvidenceTrustError("trust policy type must be exact")
        state = policies.get(policy)
        if state is None:
            raise CanonicalSourceEvidenceTrustError("trust policy is not composition-root issued")
        current = _policy_commitment(state.secret, state.snapshot, state.port_bindings)
        if not hmac.compare_digest(state.commitment, current):
            raise CanonicalSourceEvidenceTrustError("trust policy integrity check failed")
        return state

    def verified_lease(
        policy: CanonicalSourceEvidenceTrustPolicy,
        lease: _CanonicalSourceEvidenceTrustLease,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
    ) -> _LeaseState:
        state = verified_policy(policy)
        if type(lease) is not _CanonicalSourceEvidenceTrustLease:
            raise CanonicalSourceEvidenceTrustError("trust policy lease type must be exact")
        lease_state = leases.get(lease)
        if (
            lease_state is None
            or lease_state.policy is not policy
            or lease_state.lane != lane
            or state.lanes.get(lane) is not lease
            or lease_state.policy_commitment != state.commitment
            or not _same_objects(lease_state.port_bindings, port_bindings)
        ):
            raise CanonicalSourceEvidenceTrustError("trust policy identity does not match")
        return lease_state

    def composition_issue(
        *,
        policy_id: str,
        canonical_backend_id: str,
        infinity_source_backend_id: str,
        mem0_source_backend_id: str,
        canonical_adapter_id: str,
        infinity_source_adapter_id: str,
        mem0_source_adapter_id: str,
        canonical_implementation_sha256: str,
        infinity_source_implementation_sha256: str,
        mem0_source_implementation_sha256: str,
        runtime_attestation_commitment: str,
        canonical_lifecycle_port: object,
        canonical_readback_port: object,
        infinity_retrieved_port: object,
        infinity_ingested_port: object,
        mem0_request_port: object,
        mem0_readback_port: object,
    ) -> CanonicalSourceEvidenceTrustPolicy:
        """Private composition seam; deliberately absent from __all__."""

        snapshot = _PolicySnapshot(
            _text(policy_id, "policy_id"),
            _text(canonical_backend_id, "canonical_backend_id"),
            _text(infinity_source_backend_id, "infinity_source_backend_id"),
            _text(mem0_source_backend_id, "mem0_source_backend_id"),
            _text(canonical_adapter_id, "canonical_adapter_id"),
            _text(infinity_source_adapter_id, "infinity_source_adapter_id"),
            _text(mem0_source_adapter_id, "mem0_source_adapter_id"),
            _digest(
                canonical_implementation_sha256,
                "canonical_implementation_sha256",
            ),
            _digest(
                infinity_source_implementation_sha256,
                "infinity_source_implementation_sha256",
            ),
            _digest(
                mem0_source_implementation_sha256,
                "mem0_source_implementation_sha256",
            ),
            _digest(runtime_attestation_commitment, "runtime_attestation_commitment"),
        )
        port_bindings = (
            canonical_lifecycle_port,
            canonical_readback_port,
            infinity_retrieved_port,
            infinity_ingested_port,
            mem0_request_port,
            mem0_readback_port,
        )
        if any(port is None for port in port_bindings):
            raise CanonicalSourceEvidenceTrustError("all policy ports must be concrete objects")
        secret = secrets.token_bytes(32)
        commitment = _policy_commitment(secret, snapshot, port_bindings)
        policy = CanonicalSourceEvidenceTrustPolicy(_token=_TOKEN)
        with _LOCK:
            policies[policy] = _PolicyState(
                snapshot,
                port_bindings,
                secret,
                commitment,
                {},
            )
        return policy

    def reserve(
        policy: CanonicalSourceEvidenceTrustPolicy,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
        backend_ids: tuple[str, ...],
    ) -> _CanonicalSourceEvidenceTrustLease:
        if type(lane) is not str or lane not in {
            CANONICAL_POLICY_LANE,
            SOURCE_POLICY_LANE,
        }:
            raise CanonicalSourceEvidenceTrustError("unsupported trust policy lane")
        with _LOCK:
            state = verified_policy(policy)
            if lane in state.lanes:
                raise CanonicalSourceEvidenceTrustError("trust policy lane was already reserved")
            _validate_lane_bindings(state, lane, port_bindings, backend_ids)
            lease = _CanonicalSourceEvidenceTrustLease(_token=_TOKEN)
            state.lanes[lane] = lease
            leases[lease] = _LeaseState(
                policy,
                lane,
                port_bindings,
                state.commitment,
                "issued",
            )
            return lease

    def begin(
        policy: CanonicalSourceEvidenceTrustPolicy,
        lease: _CanonicalSourceEvidenceTrustLease,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
    ) -> None:
        with _LOCK:
            state = verified_lease(
                policy,
                lease,
                lane=lane,
                port_bindings=port_bindings,
            )
            if state.phase != "issued":
                raise CanonicalSourceEvidenceTrustError("trust policy lease is not live")
            state.phase = "sealing"

    def seal(
        policy: CanonicalSourceEvidenceTrustPolicy,
        lease: _CanonicalSourceEvidenceTrustLease,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
    ) -> dict[str, object]:
        with _LOCK:
            state = verified_lease(
                policy,
                lease,
                lane=lane,
                port_bindings=port_bindings,
            )
            if state.phase != "sealing":
                raise CanonicalSourceEvidenceTrustError("trust policy lease is not sealing")
            state.phase = "sealed"
            return _public_snapshot(verified_policy(policy))

    def fail(
        policy: CanonicalSourceEvidenceTrustPolicy,
        lease: _CanonicalSourceEvidenceTrustLease,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
    ) -> None:
        with _LOCK:
            state = verified_lease(
                policy,
                lease,
                lane=lane,
                port_bindings=port_bindings,
            )
            if state.phase == "sealing":
                state.phase = "failed"

    def validate(
        policy: CanonicalSourceEvidenceTrustPolicy,
        lease: _CanonicalSourceEvidenceTrustLease,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
        phases: tuple[str, ...],
    ) -> dict[str, object]:
        with _LOCK:
            state = verified_lease(
                policy,
                lease,
                lane=lane,
                port_bindings=port_bindings,
            )
            if type(phases) is not tuple or state.phase not in phases:
                raise CanonicalSourceEvidenceTrustError("trust policy lease phase is invalid")
            return _public_snapshot(verified_policy(policy))

    def consume_component(
        policy: CanonicalSourceEvidenceTrustPolicy,
        lease: _CanonicalSourceEvidenceTrustLease,
        *,
        lane: str,
        port_bindings: tuple[object, ...],
    ) -> dict[str, object]:
        with _LOCK:
            state = verified_lease(
                policy,
                lease,
                lane=lane,
                port_bindings=port_bindings,
            )
            if state.phase != "sealed":
                raise CanonicalSourceEvidenceTrustError(
                    "trust policy component was already consumed or is not sealed"
                )
            state.phase = "component_consumed"
            return _public_snapshot(verified_policy(policy))

    return (
        composition_issue,
        reserve,
        begin,
        seal,
        fail,
        validate,
        consume_component,
    )


(
    _composition_issue_canonical_source_evidence_trust_policy,
    _reserve_canonical_source_evidence_trust,
    _begin_canonical_source_evidence_trust,
    _seal_canonical_source_evidence_trust,
    _fail_canonical_source_evidence_trust,
    _validate_canonical_source_evidence_trust,
    _consume_canonical_source_evidence_trust_component,
) = _build_trust_policy_api()


def _validate_lane_bindings(
    state: _PolicyState,
    lane: str,
    ports: tuple[object, ...],
    backend_ids: tuple[str, ...],
) -> None:
    snapshot = state.snapshot
    if lane == CANONICAL_POLICY_LANE:
        trusted_ports = state.port_bindings[:2]
        trusted_backend_ids = (snapshot.canonical_backend_id,)
    else:
        trusted_ports = state.port_bindings[2:]
        trusted_backend_ids = (
            snapshot.infinity_source_backend_id,
            snapshot.mem0_source_backend_id,
        )
    if (
        type(ports) is not tuple
        or not _same_objects(ports, trusted_ports)
        or type(backend_ids) is not tuple
        or any(type(item) is not str for item in backend_ids)
        or backend_ids != trusted_backend_ids
    ):
        raise CanonicalSourceEvidenceTrustError(
            "ports or backend identities differ from trust policy"
        )


def _same_objects(left: tuple[object, ...], right: tuple[object, ...]) -> bool:
    return len(left) == len(right) and all(
        left_item is right_item for left_item, right_item in zip(left, right, strict=True)
    )


def _public_snapshot(state: _PolicyState) -> dict[str, object]:
    snapshot = state.snapshot
    return {
        "schema_version": TRUST_POLICY_SCHEMA_VERSION,
        "policy_id": snapshot.policy_id,
        "policy_commitment": state.commitment,
        "backend_ids": {
            "canonical": snapshot.canonical_backend_id,
            "infinity_source": snapshot.infinity_source_backend_id,
            "mem0_source": snapshot.mem0_source_backend_id,
        },
        "adapter_ids": {
            "canonical": snapshot.canonical_adapter_id,
            "infinity_source": snapshot.infinity_source_adapter_id,
            "mem0_source": snapshot.mem0_source_adapter_id,
        },
        "implementation_sha256": {
            "canonical": snapshot.canonical_implementation_sha256,
            "infinity_source": snapshot.infinity_source_implementation_sha256,
            "mem0_source": snapshot.mem0_source_implementation_sha256,
        },
        "runtime_attestation_commitment": snapshot.runtime_attestation_commitment,
        "policy_bound": True,
        "externally_authentic": False,
        "component_only": True,
        "composite_policy_consume_required": True,
    }


def _policy_commitment(
    secret: bytes,
    snapshot: _PolicySnapshot,
    ports: tuple[object, ...],
) -> str:
    payload = {
        "schema_version": TRUST_POLICY_SCHEMA_VERSION,
        "snapshot": {field: getattr(snapshot, field) for field in snapshot.__dataclass_fields__},
        "port_object_ids": [id(port) for port in ports],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > _MAX_TEXT:
        raise CanonicalSourceEvidenceTrustError(f"{name} must be a bounded nonblank exact string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise CanonicalSourceEvidenceTrustError(f"{name} must be lowercase sha256")
    return value


__all__ = (
    "CANONICAL_POLICY_LANE",
    "SOURCE_POLICY_LANE",
    "TRUST_POLICY_SCHEMA_VERSION",
    "CanonicalSourceEvidenceTrustError",
    "CanonicalSourceEvidenceTrustPolicy",
)
