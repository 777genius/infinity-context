"""Policy-bound terminal delete evidence for future full-comparison admission."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_delete_evidence_trust import (
    AdapterProvenance,
    DeleteVerificationTrustPolicy,
    TrustedDeleteVerificationCoordinator,
    coordinator_snapshot,
    create_trusted_delete_verification_coordinator,
    trust_policy_snapshot,
)
from infinity_context_server.memory_comparison_full_delete_evidence_witnesses import (
    DELETE_REQUEST_SCHEMA_VERSION,
    INFINITY_BACKEND_KIND,
    MEM0_BACKEND_KIND,
    DeleteEvidenceVerificationError,
    DeleteScopeRequest,
    DeleteVerificationPort,
    InfinityCleanupWitness,
    InfinityReadbackWitness,
    Mem0CleanupWitness,
    Mem0ReadbackWitness,
    cleanup_witness_snapshot,
    readback_witness_snapshot,
    validate_delete_id,
)

DELETE_EVIDENCE_SCHEMA_VERSION = "memory-comparison-full-delete-evidence.v1"
_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _Binding:
    run_id: str
    profile_id: str
    infinity_backend_id: str
    mem0_backend_id: str
    scope_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class _BackendEvidence:
    backend_kind: str
    backend_id: str
    adapter_id: str
    implementation_sha256: str
    first_cleanup: tuple[object, ...]
    first_readback: tuple[object, ...]
    second_cleanup: tuple[object, ...]
    second_readback: tuple[object, ...]


@dataclass(slots=True)
class _SessionState:
    binding: _Binding
    secret: bytes
    commitment: str
    generation: int
    status: str
    seal: SealedTerminalDeleteEvidence | None
    consumed_by: str | None


@dataclass(frozen=True, slots=True)
class _SealSnapshot:
    session: TerminalDeleteEvidenceSession
    policy: DeleteVerificationTrustPolicy
    coordinator: TrustedDeleteVerificationCoordinator
    binding: _Binding
    generation: int
    infinity: _BackendEvidence
    mem0: _BackendEvidence
    policy_commitment: str
    coordinator_commitment: str
    commitment: str


@final
class TerminalDeleteEvidenceSession:
    """Opaque one-shot lifecycle bound to exact primitive identities."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise DeleteEvidenceVerificationError("delete evidence sessions must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("TerminalDeleteEvidenceSession is sealed")

    def __repr__(self) -> str:
        return "TerminalDeleteEvidenceSession(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("TerminalDeleteEvidenceSession is nonserializable")


@final
class SealedTerminalDeleteEvidence:
    """Opaque evidence capability; public reports are never admission input."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise DeleteEvidenceVerificationError("delete evidence seals must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("SealedTerminalDeleteEvidence is sealed")

    def __repr__(self) -> str:
        return "SealedTerminalDeleteEvidence(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("SealedTerminalDeleteEvidence is nonserializable")


_SESSIONS: weakref.WeakKeyDictionary[TerminalDeleteEvidenceSession, _SessionState] = (
    weakref.WeakKeyDictionary()
)
_SEALS: weakref.WeakKeyDictionary[SealedTerminalDeleteEvidence, _SealSnapshot] = (
    weakref.WeakKeyDictionary()
)
_LOCK = threading.RLock()


def create_terminal_delete_evidence_session(
    *,
    run_id: str,
    profile_id: str,
    infinity_backend_id: str,
    mem0_backend_id: str,
    scope_id: str,
    source_id: str,
) -> TerminalDeleteEvidenceSession:
    """Issue one registered verification lifecycle from exact bindings."""

    binding = _binding(
        run_id=run_id,
        profile_id=profile_id,
        infinity_backend_id=infinity_backend_id,
        mem0_backend_id=mem0_backend_id,
        scope_id=scope_id,
        source_id=source_id,
    )
    secret = secrets.token_bytes(32)
    commitment = _commitment(secret, {"binding": _binding_payload(binding), "kind": "session"})
    session = TerminalDeleteEvidenceSession(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _SESSIONS[session] = _SessionState(binding, secret, commitment, 0, "open", None, None)
    return session


def seal_terminal_delete_evidence(
    session: TerminalDeleteEvidenceSession,
    *,
    policy: DeleteVerificationTrustPolicy,
    coordinator: TrustedDeleteVerificationCoordinator,
) -> SealedTerminalDeleteEvidence:
    """Collect two absence-confirming cleanup/readback rounds per backend."""

    state = _session_state(session)
    expected_policy = trust_policy_snapshot(policy)
    registered = coordinator_snapshot(coordinator, expected_policy=policy)
    if (
        expected_policy.infinity.backend_id != state.binding.infinity_backend_id
        or expected_policy.mem0.backend_id != state.binding.mem0_backend_id
    ):
        raise DeleteEvidenceVerificationError("delete trust policy backend binding mismatch")
    with _LOCK:
        if state.status != "open":
            raise DeleteEvidenceVerificationError("delete evidence session is not open")
        state.status = "verifying"
        state.generation += 1
        generation = state.generation
        binding = state.binding
    try:
        infinity = _collect_backend_evidence(
            expected_policy.infinity_port,
            binding=binding,
            provenance=expected_policy.infinity,
        )
        mem0 = _collect_backend_evidence(
            expected_policy.mem0_port,
            binding=binding,
            provenance=expected_policy.mem0,
        )
        trust_policy_snapshot(policy)
        coordinator_snapshot(coordinator, expected_policy=policy)
    except BaseException as exc:
        with _LOCK:
            if state.status == "verifying" and state.generation == generation:
                state.status = "open"
                state.generation += 1
        _raise_sanitized_verification_failure(exc)

    commitment = _commitment(
        state.secret,
        _seal_payload(
            binding,
            generation,
            infinity,
            mem0,
            expected_policy.commitment,
            registered.commitment,
        ),
    )
    seal = SealedTerminalDeleteEvidence(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        if state.status != "verifying" or state.generation != generation:
            raise DeleteEvidenceVerificationError("delete evidence session changed during sealing")
        state.status = "sealed"
        state.seal = seal
        _SEALS[seal] = _SealSnapshot(
            session,
            policy,
            coordinator,
            binding,
            generation,
            infinity,
            mem0,
            expected_policy.commitment,
            registered.commitment,
            commitment,
        )
    return seal


def terminal_delete_evidence_report(
    evidence: SealedTerminalDeleteEvidence,
    *,
    policy: DeleteVerificationTrustPolicy,
) -> dict[str, object]:
    """Revalidate exact policy-bound evidence and return a component report."""

    snapshot = _seal_snapshot(evidence, expected_policy=policy)
    policy_snapshot = trust_policy_snapshot(policy)
    return {
        "schema_version": DELETE_EVIDENCE_SCHEMA_VERSION,
        "evidence_role": "component_only",
        "externally_authentic": False,
        "composite_policy_consume_required": True,
        "verification_policy": {
            "commitment": snapshot.policy_commitment,
            "external_attestation_commitment": (policy_snapshot.external_attestation_commitment),
        },
        "coordinator_commitment": snapshot.coordinator_commitment,
        **_binding_payload(snapshot.binding),
        "infinity": _backend_report(snapshot.infinity),
        "mem0": _backend_report(snapshot.mem0),
        "commitment": snapshot.commitment,
    }


def consume_terminal_delete_evidence(
    evidence: SealedTerminalDeleteEvidence,
    session: TerminalDeleteEvidenceSession,
    *,
    policy: DeleteVerificationTrustPolicy,
    consumer_id: str,
    run_id: str,
    profile_id: str,
    infinity_backend_id: str,
    mem0_backend_id: str,
    scope_id: str,
    source_id: str,
) -> None:
    """Atomically consume exact sealed evidence once for a future composite."""

    validate_delete_id(consumer_id, field_name="delete evidence consumer_id")
    expected = _binding(
        run_id=run_id,
        profile_id=profile_id,
        infinity_backend_id=infinity_backend_id,
        mem0_backend_id=mem0_backend_id,
        scope_id=scope_id,
        source_id=source_id,
    )
    with _LOCK:
        snapshot = _seal_snapshot(evidence, expected_policy=policy)
        if snapshot.session is not session or snapshot.binding != expected:
            raise DeleteEvidenceVerificationError("delete evidence admission binding mismatch")
        state = _session_state(session)
        if state.status != "sealed" or state.seal is not evidence or state.consumed_by is not None:
            raise DeleteEvidenceVerificationError("delete evidence admission is stale or replayed")
        trust_policy_snapshot(policy)
        state.status = "consumed"
        state.consumed_by = consumer_id


def _collect_backend_evidence(
    port: DeleteVerificationPort,
    *,
    binding: _Binding,
    provenance: AdapterProvenance,
) -> _BackendEvidence:
    cleanups: list[tuple[object, ...]] = []
    readbacks: list[tuple[object, ...]] = []
    for attempt in (1, 2):
        cleanup_request = _delete_request(
            binding,
            backend_kind=provenance.backend_kind,
            backend_id=provenance.backend_id,
            attempt=attempt,
        )
        cleanup_before = _request_snapshot(cleanup_request)
        cleanup_digest = _request_digest(cleanup_before)
        cleanup = port.cleanup(cleanup_request)
        validation_request = _delete_request(
            binding,
            backend_kind=provenance.backend_kind,
            backend_id=provenance.backend_id,
            attempt=attempt,
        )
        cleanup_after = _request_snapshot(cleanup_request)
        if not hmac.compare_digest(_request_digest(cleanup_after), cleanup_digest):
            raise DeleteEvidenceVerificationError("delete cleanup request was mutated")
        cleanups.append(
            cleanup_witness_snapshot(
                cleanup,
                request=validation_request,
                require_idempotent=attempt == 2,
            )
        )
        readback_request = _delete_request(
            binding,
            backend_kind=provenance.backend_kind,
            backend_id=provenance.backend_id,
            attempt=attempt,
        )
        readback_before = _request_snapshot(readback_request)
        readback_digest = _request_digest(readback_before)
        readback = port.readback(readback_request)
        validation_request = _delete_request(
            binding,
            backend_kind=provenance.backend_kind,
            backend_id=provenance.backend_id,
            attempt=attempt,
        )
        readback_after = _request_snapshot(readback_request)
        if not hmac.compare_digest(_request_digest(readback_after), readback_digest):
            raise DeleteEvidenceVerificationError("delete readback request was mutated")
        readbacks.append(readback_witness_snapshot(readback, request=validation_request))
    return _BackendEvidence(
        provenance.backend_kind,
        provenance.backend_id,
        provenance.adapter_id,
        provenance.implementation_sha256,
        cleanups[0],
        readbacks[0],
        cleanups[1],
        readbacks[1],
    )


def _delete_request(
    binding: _Binding,
    *,
    backend_kind: str,
    backend_id: str,
    attempt: int,
) -> DeleteScopeRequest:
    return DeleteScopeRequest(
        binding.run_id,
        binding.profile_id,
        backend_kind,
        backend_id,
        binding.scope_id,
        binding.source_id,
        attempt,
    )


def _request_snapshot(request: object) -> tuple[str, str, str, str, str, str, int]:
    if type(request) is not DeleteScopeRequest:
        raise DeleteEvidenceVerificationError("delete request type changed after callback")
    values = (
        request.run_id,
        request.profile_id,
        request.backend_id,
        request.scope_id,
        request.source_id,
    )
    for name, value in zip(
        ("run_id", "profile_id", "backend_id", "scope_id", "source_id"),
        values,
        strict=True,
    ):
        validate_delete_id(value, field_name=f"delete request {name}")
    if type(request.backend_kind) is not str or request.backend_kind not in (
        INFINITY_BACKEND_KIND,
        MEM0_BACKEND_KIND,
    ):
        raise DeleteEvidenceVerificationError("delete request backend kind changed")
    if type(request.attempt) is not int or request.attempt not in (1, 2):
        raise DeleteEvidenceVerificationError("delete request attempt changed")
    return (
        request.run_id,
        request.profile_id,
        request.backend_kind,
        request.backend_id,
        request.scope_id,
        request.source_id,
        request.attempt,
    )


def _request_digest(snapshot: tuple[str, str, str, str, str, str, int]) -> bytes:
    return hashlib.sha256(json.dumps(snapshot, separators=(",", ":")).encode()).digest()


def _session_state(session: TerminalDeleteEvidenceSession) -> _SessionState:
    if type(session) is not TerminalDeleteEvidenceSession:
        raise DeleteEvidenceVerificationError("delete evidence session type is invalid")
    with _LOCK:
        state = _SESSIONS.get(session)
    if state is None:
        raise DeleteEvidenceVerificationError("delete evidence session is unregistered")
    expected = _commitment(
        state.secret,
        {"binding": _binding_payload(state.binding), "kind": "session"},
    )
    try:
        current = session._TerminalDeleteEvidenceSession__commitment
    except Exception:
        raise DeleteEvidenceVerificationError("delete evidence session integrity failed") from None
    if (
        type(current) is not str
        or not hmac.compare_digest(current, state.commitment)
        or not hmac.compare_digest(expected, state.commitment)
    ):
        raise DeleteEvidenceVerificationError("delete evidence session integrity failed")
    return state


def _seal_snapshot(
    evidence: SealedTerminalDeleteEvidence,
    *,
    expected_policy: DeleteVerificationTrustPolicy,
) -> _SealSnapshot:
    if type(evidence) is not SealedTerminalDeleteEvidence:
        raise DeleteEvidenceVerificationError("delete evidence admission type is invalid")
    with _LOCK:
        snapshot = _SEALS.get(evidence)
    if snapshot is None:
        raise DeleteEvidenceVerificationError("delete evidence seal is unregistered")
    state = _session_state(snapshot.session)
    policy = trust_policy_snapshot(expected_policy)
    coordinator = coordinator_snapshot(
        snapshot.coordinator,
        expected_policy=expected_policy,
    )
    expected = _commitment(
        state.secret,
        _seal_payload(
            snapshot.binding,
            snapshot.generation,
            snapshot.infinity,
            snapshot.mem0,
            snapshot.policy_commitment,
            snapshot.coordinator_commitment,
        ),
    )
    try:
        current = evidence._SealedTerminalDeleteEvidence__commitment
    except Exception:
        raise DeleteEvidenceVerificationError("delete evidence seal integrity failed") from None
    with _LOCK:
        valid_state = (
            state.status in ("sealed", "consumed")
            and snapshot.policy is expected_policy
            and state.generation == snapshot.generation
            and state.seal is evidence
            and state.binding == snapshot.binding
            and hmac.compare_digest(policy.commitment, snapshot.policy_commitment)
            and hmac.compare_digest(
                coordinator.policy_commitment,
                snapshot.policy_commitment,
            )
            and hmac.compare_digest(coordinator.commitment, snapshot.coordinator_commitment)
        )
    if (
        not valid_state
        or type(current) is not str
        or not hmac.compare_digest(current, snapshot.commitment)
        or not hmac.compare_digest(expected, snapshot.commitment)
    ):
        raise DeleteEvidenceVerificationError("delete evidence seal integrity failed")
    return snapshot


def _binding(
    *,
    run_id: str,
    profile_id: str,
    infinity_backend_id: str,
    mem0_backend_id: str,
    scope_id: str,
    source_id: str,
) -> _Binding:
    for name, value in (
        ("run_id", run_id),
        ("profile_id", profile_id),
        ("infinity_backend_id", infinity_backend_id),
        ("mem0_backend_id", mem0_backend_id),
        ("scope_id", scope_id),
        ("source_id", source_id),
    ):
        validate_delete_id(value, field_name=f"delete evidence {name}")
    if hmac.compare_digest(infinity_backend_id, mem0_backend_id):
        raise DeleteEvidenceVerificationError("delete evidence backend identities must differ")
    return _Binding(
        run_id,
        profile_id,
        infinity_backend_id,
        mem0_backend_id,
        scope_id,
        source_id,
    )


def _binding_payload(binding: _Binding) -> dict[str, object]:
    return {
        "run_id": binding.run_id,
        "profile_id": binding.profile_id,
        "infinity_backend_id": binding.infinity_backend_id,
        "mem0_backend_id": binding.mem0_backend_id,
        "scope_id": binding.scope_id,
        "source_id": binding.source_id,
    }


def _seal_payload(
    binding: _Binding,
    generation: int,
    infinity: _BackendEvidence,
    mem0: _BackendEvidence,
    policy_commitment: str,
    coordinator_commitment: str,
) -> dict[str, object]:
    return {
        "schema_version": DELETE_EVIDENCE_SCHEMA_VERSION,
        "binding": _binding_payload(binding),
        "externally_authentic": False,
        "composite_policy_consume_required": True,
        "coordinator_commitment": coordinator_commitment,
        "generation": generation,
        "policy_commitment": policy_commitment,
        "infinity": _backend_payload(infinity),
        "mem0": _backend_payload(mem0),
    }


def _backend_payload(evidence: _BackendEvidence) -> dict[str, object]:
    return {
        "backend_kind": evidence.backend_kind,
        "backend_id": evidence.backend_id,
        "adapter_id": evidence.adapter_id,
        "implementation_sha256": evidence.implementation_sha256,
        "first_cleanup": list(evidence.first_cleanup),
        "first_readback": list(evidence.first_readback),
        "second_cleanup": list(evidence.second_cleanup),
        "second_readback": list(evidence.second_readback),
    }


def _backend_report(evidence: _BackendEvidence) -> dict[str, object]:
    if evidence.backend_kind == INFINITY_BACKEND_KIND:
        cleanup_names = ("canonical_deleted_count", "derived_deleted_count")
        readback_names = ("canonical_remaining_count", "derived_remaining_count")
    else:
        cleanup_names = ("deleted_count",)
        readback_names = ("remaining_count",)
    return {
        "backend_id": evidence.backend_id,
        "adapter_provenance": {
            "adapter_id": evidence.adapter_id,
            "implementation_sha256": evidence.implementation_sha256,
            "policy_bound": True,
        },
        "first_cleanup": _cleanup_report(evidence.first_cleanup, cleanup_names),
        "first_readback": _readback_report(evidence.first_readback, readback_names),
        "second_cleanup": _cleanup_report(evidence.second_cleanup, cleanup_names),
        "second_readback": _readback_report(evidence.second_readback, readback_names),
        "idempotent_second_cleanup": True,
        "terminal_absence": True,
    }


def _cleanup_report(
    snapshot: tuple[object, ...],
    count_names: tuple[str, ...],
) -> dict[str, object]:
    counts = snapshot[7 : 7 + len(count_names)]
    return {
        "attempt": snapshot[5],
        "acknowledged": snapshot[6],
        **dict(zip(count_names, counts, strict=True)),
        "already_absent": snapshot[-1],
    }


def _readback_report(
    snapshot: tuple[object, ...],
    count_names: tuple[str, ...],
) -> dict[str, object]:
    counts = snapshot[6 : 6 + len(count_names)]
    return {
        "attempt": snapshot[5],
        **dict(zip(count_names, counts, strict=True)),
    }


def _commitment(secret: bytes, payload: dict[str, object]) -> str:
    rendered = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hmac.new(secret, rendered, hashlib.sha256).hexdigest()


def _raise_sanitized_verification_failure(exc: BaseException) -> None:
    if type(exc) is asyncio.CancelledError:
        raise asyncio.CancelledError() from None
    if type(exc) is KeyboardInterrupt:
        raise KeyboardInterrupt() from None
    if type(exc) is SystemExit:
        raise SystemExit() from None
    raise DeleteEvidenceVerificationError("terminal delete verification failed") from None


__all__ = (
    "DELETE_EVIDENCE_SCHEMA_VERSION",
    "DELETE_REQUEST_SCHEMA_VERSION",
    "DeleteEvidenceVerificationError",
    "DeleteScopeRequest",
    "DeleteVerificationPort",
    "InfinityCleanupWitness",
    "InfinityReadbackWitness",
    "Mem0CleanupWitness",
    "Mem0ReadbackWitness",
    "DeleteVerificationTrustPolicy",
    "SealedTerminalDeleteEvidence",
    "TerminalDeleteEvidenceSession",
    "TrustedDeleteVerificationCoordinator",
    "consume_terminal_delete_evidence",
    "create_terminal_delete_evidence_session",
    "create_trusted_delete_verification_coordinator",
    "seal_terminal_delete_evidence",
    "terminal_delete_evidence_report",
)
