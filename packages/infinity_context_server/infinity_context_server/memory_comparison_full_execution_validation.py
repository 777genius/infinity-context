"""Opaque complete-run validation for full memory comparison components."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_clean_state import VerifiedCleanStateValidation
from infinity_context_server.memory_comparison_full_execution_evidence_slots import (
    FULL_EXECUTION_VALIDATION_EVIDENCE_SCHEMA_VERSION,
    validate_full_execution_evidence_slots,
)
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    FULL_EXECUTION_EVIDENCE_REPLAY,
    FullExecutionCleanStateEvidence,
    FullExecutionTransportEvidence,
    _inspect_full_execution_clean_state_evidence_for_validation,
    _inspect_full_execution_transport_evidence_for_validation,
    inspect_full_execution_clean_state_evidence,
    inspect_full_execution_transport_evidence,
    issue_legacy_full_execution_clean_state_evidence,
    issue_legacy_full_execution_transport_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FULL_EXECUTION_VALIDATION_SCHEMA_VERSION,
    FullExecutionCaseManifestEntry,
    FullExecutionCleanScope,
    FullExecutionProviderCall,
    FullExecutionValidationError,
    execution_case_manifest_sha256,
    validate_full_execution_slots,
)
from infinity_context_server.memory_comparison_full_run_evidence import FullComparisonRunBindings
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_provider_provenance import ProviderRouteAttestation
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
)

_TOKEN = object()
_LOCK = threading.RLock()


@final
class FullExecutionValidationSession:
    """Opaque reservation for one complete-run observation."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullExecutionValidationError("execution sessions must be issued")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("FullExecutionValidationSession is final")

    def __repr__(self) -> str:
        return "FullExecutionValidationSession(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("FullExecutionValidationSession is nonserializable")


@final
class VerifiedFullExecutionValidation:
    """Opaque component proof; public mappings are never composite admission."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullExecutionValidationError("execution validation must be sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("VerifiedFullExecutionValidation is final")

    def __repr__(self) -> str:
        return "VerifiedFullExecutionValidation(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("VerifiedFullExecutionValidation is nonserializable")


@dataclass(frozen=True, slots=True)
class _Identity:
    comparison_commitment_sha256: str
    run_id: str
    profile_id: str
    dataset_sha256: str
    selection_sha256: str
    case_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class _LiveInputs:
    """Private v1 compatibility shape retained for existing internal callers."""

    bindings: FullComparisonRunBindings
    benchmark: str
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...]
    required_model: str
    required_route: ProviderRouteAttestation
    provider_calls: tuple[FullExecutionProviderCall, ...]
    session_verifier: RunScopedSessionHmacKey
    session_evidence: tuple[SessionIdentityEvidence, ...]
    transport_verifier: RunScopedLocomoTransportEvidenceKey | None
    transport_evidence: tuple[LocomoTimestampTransportEvidence, ...]
    clean_validation: VerifiedCleanStateValidation
    clean_scopes: tuple[FullExecutionCleanScope, ...]
    clean_attestation_key: bytes


@dataclass(frozen=True, slots=True)
class _EvidenceLiveInputs:
    """Neutral live inputs stored by newly issued sessions and proofs."""

    bindings: FullComparisonRunBindings
    benchmark: str
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...]
    required_model: str
    required_route: ProviderRouteAttestation
    provider_calls: tuple[FullExecutionProviderCall, ...]
    session_verifier: RunScopedSessionHmacKey
    session_evidence: tuple[SessionIdentityEvidence, ...]
    transport_evidence: FullExecutionTransportEvidence
    clean_state_evidence: tuple[FullExecutionCleanStateEvidence, ...]


@dataclass(frozen=True, slots=True)
class _BundleReservationLease:
    key: str
    pending_nonce: bytes
    generation: int
    resource_tokens: tuple[str, ...]
    resource_objects: tuple[object, ...]


@dataclass(slots=True)
class _BundleReservationRecord:
    pending_nonce: bytes
    generation: int
    resource_tokens: tuple[str, ...]
    resource_objects: tuple[object, ...]
    phase: str


@dataclass(slots=True)
class _SessionState:
    identity: _Identity
    inputs: _EvidenceLiveInputs
    reservation: _BundleReservationLease
    report: MappingProxyType[str, object]
    commitment: str
    secret: bytes
    phase: str


@dataclass(slots=True)
class _ProofState:
    identity: _Identity
    inputs: _EvidenceLiveInputs
    reservation: _BundleReservationLease
    report: MappingProxyType[str, object]
    commitment: str
    secret: bytes
    consumed: bool


_SESSIONS: weakref.WeakKeyDictionary[
    FullExecutionValidationSession, _SessionState
] = weakref.WeakKeyDictionary()
_PROOFS: weakref.WeakKeyDictionary[
    VerifiedFullExecutionValidation, _ProofState
] = weakref.WeakKeyDictionary()


def _build_bundle_reservation_api():
    reservations: dict[str, _BundleReservationRecord] = {}
    resource_owners: dict[str, tuple[str, bytes, int]] = {}
    generation = 0

    def reserve(
        key: str,
        resource_tokens: tuple[str, ...],
        resource_objects: tuple[object, ...],
    ) -> _BundleReservationLease:
        nonlocal generation
        with _LOCK:
            if key in reservations or any(token in resource_owners for token in resource_tokens):
                raise FullExecutionValidationError(
                    "execution input bundle or live capability was already reserved"
                )
            generation += 1
            lease = _BundleReservationLease(
                key,
                secrets.token_bytes(32),
                generation,
                resource_tokens,
                resource_objects,
            )
            reservations[key] = _BundleReservationRecord(
                lease.pending_nonce,
                lease.generation,
                lease.resource_tokens,
                lease.resource_objects,
                "pending",
            )
            for token in resource_tokens:
                resource_owners[token] = (
                    lease.key,
                    lease.pending_nonce,
                    lease.generation,
                )
            return lease

    def make_terminal(lease: _BundleReservationLease) -> None:
        with _LOCK:
            record = reservations.get(lease.key)
            if not _reservation_matches(record, lease, phase="pending") or not all(
                _resource_owner_matches(resource_owners.get(token), lease)
                for token in lease.resource_tokens
            ):
                raise FullExecutionValidationError(
                    "execution input bundle reservation is not pending"
                )
            record.phase = "terminal"

    def rollback_pending(lease: _BundleReservationLease) -> None:
        with _LOCK:
            record = reservations.get(lease.key)
            if _reservation_matches(record, lease, phase="pending"):
                del reservations[lease.key]
                for token in lease.resource_tokens:
                    if _resource_owner_matches(resource_owners.get(token), lease):
                        del resource_owners[token]

    def require_terminal(lease: _BundleReservationLease) -> None:
        with _LOCK:
            record = reservations.get(lease.key)
            if not _reservation_matches(record, lease, phase="terminal") or not all(
                _resource_owner_matches(resource_owners.get(token), lease)
                for token in lease.resource_tokens
            ):
                raise FullExecutionValidationError(
                    "execution input bundle reservation is not terminal"
                )

    return reserve, make_terminal, rollback_pending, require_terminal


def _resource_owner_matches(
    owner: tuple[str, bytes, int] | None,
    lease: _BundleReservationLease,
) -> bool:
    return bool(
        owner is not None
        and owner[0] == lease.key
        and owner[2] == lease.generation
        and hmac.compare_digest(owner[1], lease.pending_nonce)
    )


def _reservation_matches(
    record: _BundleReservationRecord | None,
    lease: _BundleReservationLease,
    *,
    phase: str,
) -> bool:
    return bool(
        record is not None
        and record.phase == phase
        and record.generation == lease.generation
        and hmac.compare_digest(record.pending_nonce, lease.pending_nonce)
    )


(
    _reserve_bundle,
    _make_bundle_terminal,
    _rollback_pending_bundle,
    _require_terminal_bundle,
) = _build_bundle_reservation_api()


def issue_full_execution_validation_session(
    *,
    bindings: FullComparisonRunBindings,
    benchmark: str,
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
    required_model: str,
    required_route: ProviderRouteAttestation,
    provider_calls: tuple[FullExecutionProviderCall, ...],
    session_verifier: RunScopedSessionHmacKey,
    session_evidence: tuple[SessionIdentityEvidence, ...],
    transport_verifier: RunScopedLocomoTransportEvidenceKey | None,
    transport_evidence: tuple[LocomoTimestampTransportEvidence, ...],
    clean_validation: VerifiedCleanStateValidation,
    clean_scopes: tuple[FullExecutionCleanScope, ...],
    clean_attestation_key: bytes,
) -> FullExecutionValidationSession:
    """Legacy v1 facade preserving the exact public input contract."""

    # Preserve legacy validation order and errors before constructing neutral wrappers.
    validate_full_execution_slots(
        bindings=bindings,
        benchmark=benchmark,
        case_manifest=case_manifest,
        required_model=required_model,
        required_route=required_route,
        provider_calls=provider_calls,
        session_verifier=session_verifier,
        session_evidence=session_evidence,
        transport_verifier=transport_verifier,
        transport_evidence=transport_evidence,
        clean_validation=clean_validation,
        clean_scopes=clean_scopes,
        clean_attestation_key=clean_attestation_key,
    )
    transport = issue_legacy_full_execution_transport_evidence(
        benchmark=benchmark,
        verifier=transport_verifier,
        evidence=transport_evidence,
    )
    clean = issue_legacy_full_execution_clean_state_evidence(
        validation=clean_validation,
        scopes=clean_scopes,
        attestation_key=clean_attestation_key,
    )
    return issue_full_execution_validation_session_from_evidence(
        bindings=bindings,
        benchmark=benchmark,
        case_manifest=case_manifest,
        required_model=required_model,
        required_route=required_route,
        provider_calls=provider_calls,
        session_verifier=session_verifier,
        session_evidence=session_evidence,
        transport_evidence=transport,
        clean_state_evidence=(clean,),
    )


def issue_full_execution_validation_session_from_evidence(
    *,
    bindings: FullComparisonRunBindings,
    benchmark: str,
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
    required_model: str,
    required_route: ProviderRouteAttestation,
    provider_calls: tuple[FullExecutionProviderCall, ...],
    session_verifier: RunScopedSessionHmacKey,
    session_evidence: tuple[SessionIdentityEvidence, ...],
    transport_evidence: FullExecutionTransportEvidence,
    clean_state_evidence: tuple[FullExecutionCleanStateEvidence, ...],
) -> FullExecutionValidationSession:
    """Reserve authenticated neutral evidence and bind its issue-time report."""

    inputs = _EvidenceLiveInputs(
        bindings,
        benchmark,
        case_manifest,
        required_model,
        required_route,
        provider_calls,
        session_verifier,
        session_evidence,
        transport_evidence,
        clean_state_evidence,
    )
    initial_report = _validate_live(inputs)
    reservation_key = _bundle_reservation_key(inputs, initial_report)
    resource_tokens, resource_objects = _bundle_resources(inputs)
    try:
        reservation = _reserve_bundle(
            reservation_key,
            resource_tokens,
            resource_objects,
        )
    except FullExecutionValidationError as error:
        if _uses_managed_v5(inputs) and "already reserved" in str(error):
            raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_REPLAY) from None
        raise
    session: FullExecutionValidationSession | None = None
    try:
        report = _validate_live(inputs)
        if report != initial_report or _bundle_reservation_key(inputs, report) != reservation_key:
            raise FullExecutionValidationError("execution input bundle changed during issue")
        frozen = _freeze_report(report)
        secret = secrets.token_bytes(32)
        session = FullExecutionValidationSession(_token=_TOKEN)
        state = _SessionState(
            _identity(report),
            inputs,
            reservation,
            frozen,
            _commitment(secret, report),
            secret,
            "issued",
        )
        with _LOCK:
            _SESSIONS[session] = state
            try:
                _make_bundle_terminal(reservation)
            except BaseException:
                del _SESSIONS[session]
                raise
        return session
    except BaseException:
        _rollback_pending_bundle(reservation)
        raise


def seal_full_execution_validation(
    session: FullExecutionValidationSession,
) -> VerifiedFullExecutionValidation:
    """Revalidate all live slots and seal one immutable component proof."""

    if type(session) is not FullExecutionValidationSession:
        raise FullExecutionValidationError("execution session type must be exact")
    with _LOCK:
        state = _SESSIONS.get(session)
        if state is None or state.phase != "issued":
            raise FullExecutionValidationError("execution session is not live")
        state.phase = "observing"
    try:
        _require_terminal_bundle(state.reservation)
        _check_commitment(state.secret, state.report, state.commitment)
        report = _validate_live(state.inputs)
        frozen = _freeze_report(report)
        if frozen != state.report or _identity(report) != state.identity:
            raise FullExecutionValidationError("execution inputs changed after issue")
    except BaseException:
        with _LOCK:
            state.phase = "failed"
        raise
    proof = VerifiedFullExecutionValidation(_token=_TOKEN)
    with _LOCK:
        if state.phase != "observing":
            raise FullExecutionValidationError("execution session changed during validation")
        state.phase = "sealed"
        _PROOFS[proof] = _ProofState(
            state.identity,
            state.inputs,
            state.reservation,
            frozen,
            _commitment(state.secret, report),
            state.secret,
            False,
        )
    return proof


def public_full_execution_validation_report(
    proof: VerifiedFullExecutionValidation,
) -> dict[str, object]:
    """Return component-only telemetry after fresh live revalidation."""

    return _thaw(_verified_proof(proof).report)


def consume_full_execution_validation(
    proof: VerifiedFullExecutionValidation,
    *,
    comparison_commitment_sha256: str,
    run_id: str,
    profile_id: str,
    dataset_sha256: str,
    selection_sha256: str,
    case_manifest_sha256: str,
) -> dict[str, object]:
    """Consume the exact component proof once for later composite wiring."""

    supplied = _Identity(
        _digest(comparison_commitment_sha256, "comparison commitment"),
        _text(run_id, "run_id"),
        _text(profile_id, "profile_id"),
        _digest(dataset_sha256, "dataset"),
        _digest(selection_sha256, "selection"),
        _digest(case_manifest_sha256, "case manifest"),
    )
    with _LOCK:
        state = _verified_proof(proof)
        if state.consumed:
            raise FullExecutionValidationError("execution validation was already consumed")
        if supplied != state.identity:
            raise FullExecutionValidationError("execution validation identity does not match")
        state.consumed = True
        return _thaw(state.report)


def _verified_proof(proof: object) -> _ProofState:
    if type(proof) is not VerifiedFullExecutionValidation:
        raise FullExecutionValidationError("execution validation type must be exact")
    with _LOCK:
        state = _PROOFS.get(proof)
    if state is None:
        raise FullExecutionValidationError("execution validation integrity check failed")
    _require_terminal_bundle(state.reservation)
    _check_commitment(state.secret, state.report, state.commitment)
    report = _validate_live(state.inputs)
    if _freeze_report(report) != state.report or _identity(report) != state.identity:
        raise FullExecutionValidationError("sealed execution inputs changed")
    return state


def _validate_live(inputs: _LiveInputs | _EvidenceLiveInputs) -> dict[str, object]:
    if type(inputs) is _LiveInputs:
        return validate_full_execution_slots(
            bindings=inputs.bindings,
            benchmark=inputs.benchmark,
            case_manifest=inputs.case_manifest,
            required_model=inputs.required_model,
            required_route=inputs.required_route,
            provider_calls=inputs.provider_calls,
            session_verifier=inputs.session_verifier,
            session_evidence=inputs.session_evidence,
            transport_verifier=inputs.transport_verifier,
            transport_evidence=inputs.transport_evidence,
            clean_validation=inputs.clean_validation,
            clean_scopes=inputs.clean_scopes,
            clean_attestation_key=inputs.clean_attestation_key,
        )
    return validate_full_execution_evidence_slots(
        bindings=inputs.bindings,
        benchmark=inputs.benchmark,
        case_manifest=inputs.case_manifest,
        required_model=inputs.required_model,
        required_route=inputs.required_route,
        provider_calls=inputs.provider_calls,
        session_verifier=inputs.session_verifier,
        session_evidence=inputs.session_evidence,
        transport_evidence=inputs.transport_evidence,
        clean_state_evidence=inputs.clean_state_evidence,
    )


def _bundle_resources(
    inputs: _LiveInputs | _EvidenceLiveInputs,
) -> tuple[tuple[str, ...], tuple[object, ...]]:
    inputs = _as_evidence_inputs(inputs)
    transport = _inspect_full_execution_transport_evidence_for_validation(inputs.transport_evidence)
    clean = tuple(
        _inspect_full_execution_clean_state_evidence_for_validation(item)
        for item in inputs.clean_state_evidence
    )
    values = [
        *(f"provider-call:{id(item)}" for item in inputs.provider_calls),
        f"session-verifier:{id(inputs.session_verifier)}",
        *(f"session-evidence:{id(item)}" for item in inputs.session_evidence),
        f"transport-wrapper:{id(inputs.transport_evidence)}",
        *transport.resource_tokens,
        *(f"clean-wrapper:{id(item)}" for item in inputs.clean_state_evidence),
        *(token for inspection in clean for token in inspection.resource_tokens),
    ]
    if len(set(values)) != len(values):
        raise FullExecutionValidationError("execution input bundle repeats a live capability")
    objects: tuple[object, ...] = (
        *inputs.provider_calls,
        inputs.session_verifier,
        *inputs.session_evidence,
        inputs.transport_evidence,
        *transport.resources,
        *inputs.clean_state_evidence,
        *(item for inspection in clean for item in inspection.resources),
    )
    if len(objects) != len(values):
        raise FullExecutionValidationError("execution input bundle resource shape is invalid")
    return tuple(values), objects


def _bundle_reservation_key(
    inputs: _LiveInputs | _EvidenceLiveInputs,
    report: dict[str, object],
) -> str:
    inputs = _as_evidence_inputs(inputs)
    transport_inspection = _inspect_full_execution_transport_evidence_for_validation(
        inputs.transport_evidence
    )
    transport = transport_inspection.descriptor
    clean = tuple(
        _inspect_full_execution_clean_state_evidence_for_validation(item)
        for item in inputs.clean_state_evidence
    )
    provider_calls = [
        {
            "identity": id(call),
            "commitment": _json_commitment(
                {
                    "comparison_commitment_sha256": call.comparison_commitment_sha256,
                    "run_id": call.run_id,
                    "profile_id": call.profile_id,
                    "case_id": call.case_id,
                    "backend_role": call.backend_role,
                    "stage": call.stage,
                    "pending": call.pending,
                    "provenance": call.provenance.public_payload(),
                }
            ),
        }
        for call in inputs.provider_calls
    ]
    session_evidence = [
        {
            "identity": id(item),
            "commitment": _json_commitment(
                {
                    "mapping": {
                        "corpus_id": item.mapping.corpus_id,
                        "thread_id": item.mapping.thread_id,
                        "case_id": item.mapping.case_id,
                        "conversation_role": item.mapping.conversation_role,
                        "session_alias": item.mapping.session_alias,
                    },
                    "proof_sha256": hashlib.sha256(item.proof).hexdigest(),
                }
            ),
        }
        for item in inputs.session_evidence
    ]
    return _json_commitment(
        {
            "comparison_commitment_sha256": report["comparison_commitment_sha256"],
            "case_manifest_sha256": report["case_manifest_sha256"],
            "required_model": inputs.required_model,
            "ordered_targets": report["ordered_targets"],
            "required_route_identity": id(inputs.required_route),
            "provider_calls": provider_calls,
            "provider_coverage_commitment_sha256": report["provider_call_coverage"][
                "coverage_commitment_sha256"
            ],
            "session_verifier_identity": id(inputs.session_verifier),
            "session_evidence": session_evidence,
            "session_mapping_commitment_sha256": report["session_identity_coverage"][
                "mapping_commitment_sha256"
            ],
            "transport_evidence_identity": id(inputs.transport_evidence),
            "transport_evidence_variant": transport.variant,
            "transport_live_resource_tokens": list(transport_inspection.resource_tokens),
            "transport_commitment_sha256": report["official_transport_coverage"][
                "evidence_commitment_sha256"
            ],
            "clean_evidence": [
                {
                    "identity": id(item),
                    "variant": inspection.descriptor.variant,
                    "backend_roles": list(inspection.descriptor.backend_roles),
                    "evidence_commitment_sha256": (
                        inspection.descriptor.evidence_commitment_sha256
                    ),
                    "live_resource_tokens": list(inspection.resource_tokens),
                }
                for item, inspection in zip(inputs.clean_state_evidence, clean, strict=True)
            ],
        }
    )


def _uses_managed_v5(inputs: _EvidenceLiveInputs) -> bool:
    transport = inspect_full_execution_transport_evidence(inputs.transport_evidence)
    if transport.variant == "managed_mem0_v5":
        return True
    return any(
        inspect_full_execution_clean_state_evidence(item).variant == "managed_mem0_v5"
        for item in inputs.clean_state_evidence
    )


def _as_evidence_inputs(
    inputs: _LiveInputs | _EvidenceLiveInputs,
) -> _EvidenceLiveInputs:
    if type(inputs) is _EvidenceLiveInputs:
        return inputs
    transport = issue_legacy_full_execution_transport_evidence(
        benchmark=inputs.benchmark,
        verifier=inputs.transport_verifier,
        evidence=inputs.transport_evidence,
    )
    clean = issue_legacy_full_execution_clean_state_evidence(
        validation=inputs.clean_validation,
        scopes=inputs.clean_scopes,
        attestation_key=inputs.clean_attestation_key,
    )
    return _EvidenceLiveInputs(
        inputs.bindings,
        inputs.benchmark,
        inputs.case_manifest,
        inputs.required_model,
        inputs.required_route,
        inputs.provider_calls,
        inputs.session_verifier,
        inputs.session_evidence,
        transport,
        (clean,),
    )


def _json_commitment(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _identity(report: dict[str, object]) -> _Identity:
    return _Identity(
        _digest(report.get("comparison_commitment_sha256"), "comparison commitment"),
        _text(report.get("run_id"), "run_id"),
        _text(report.get("profile_id"), "profile_id"),
        _digest(report.get("dataset_sha256"), "dataset"),
        _digest(report.get("selection_sha256"), "selection"),
        _digest(report.get("case_manifest_sha256"), "case manifest"),
    )


def _commitment(secret: bytes, report: dict[str, object]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _check_commitment(
    secret: bytes,
    report: MappingProxyType[str, object],
    commitment: str,
) -> None:
    if not hmac.compare_digest(commitment, _commitment(secret, _thaw(report))):
        raise FullExecutionValidationError("execution validation integrity check failed")


def _freeze_report(value: object) -> MappingProxyType[str, object]:
    frozen = _freeze(value, depth=0)
    if type(frozen) is not MappingProxyType:
        raise FullExecutionValidationError("execution report root must be exact mapping")
    return frozen


def _freeze(value: object, *, depth: int) -> object:
    if depth > 16:
        raise FullExecutionValidationError("execution report nesting is too deep")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise FullExecutionValidationError("execution report float must be finite")
        return value
    if type(value) is dict:
        if len(value) > 1_000:
            raise FullExecutionValidationError("execution report mapping is too large")
        return MappingProxyType(
            {_report_key(key): _freeze(item, depth=depth + 1) for key, item in value.items()}
        )
    if type(value) in {list, tuple}:
        if len(value) > 1_000:
            raise FullExecutionValidationError("execution report sequence is too large")
        return tuple(_freeze(item, depth=depth + 1) for item in value)
    raise FullExecutionValidationError("execution report contains a non-JSON exact type")


def _thaw(value: object) -> dict[str, object]:
    thawed = _thaw_value(value, depth=0)
    if type(thawed) is not dict:
        raise FullExecutionValidationError("execution report root must be exact mapping")
    return thawed


def _thaw_value(value: object, *, depth: int) -> object:
    if depth > 16:
        raise FullExecutionValidationError("execution report nesting is too deep")
    if value is None or type(value) in {str, bool, int, float}:
        return value
    if type(value) in {dict, MappingProxyType}:
        if len(value) > 1_000:
            raise FullExecutionValidationError("execution report mapping is too large")
        return {_report_key(key): _thaw_value(item, depth=depth + 1) for key, item in value.items()}
    if type(value) in {list, tuple}:
        if len(value) > 1_000:
            raise FullExecutionValidationError("execution report sequence is too large")
        return [_thaw_value(item, depth=depth + 1) for item in value]
    raise FullExecutionValidationError("execution report contains a non-JSON exact type")


def _report_key(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise FullExecutionValidationError("execution report key is invalid")
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise FullExecutionValidationError(f"{name} must be a nonblank exact string")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FullExecutionValidationError(f"{name} must be SHA-256")
    return value


__all__ = (
    "FULL_EXECUTION_VALIDATION_EVIDENCE_SCHEMA_VERSION",
    "FULL_EXECUTION_VALIDATION_SCHEMA_VERSION",
    "FullExecutionCaseManifestEntry",
    "FullExecutionCleanScope",
    "FullExecutionProviderCall",
    "FullExecutionValidationError",
    "FullExecutionValidationSession",
    "VerifiedFullExecutionValidation",
    "consume_full_execution_validation",
    "execution_case_manifest_sha256",
    "issue_full_execution_validation_session",
    "issue_full_execution_validation_session_from_evidence",
    "public_full_execution_validation_report",
    "seal_full_execution_validation",
)
