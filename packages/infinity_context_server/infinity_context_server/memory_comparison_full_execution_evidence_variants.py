"""Authenticated neutral evidence variants for complete-run validation.

The wrappers in this module are nominal process-local capabilities.  They keep
legacy and managed-v5 evidence in separate variants instead of projecting one
provider contract into another provider's types.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCleanScope,
    FullExecutionValidationError,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5AuthenticatedCleanStateWitness,
    ManagedMem0V5CleanStateWitnessVerifierPort,
    require_managed_mem0_v5_clean_state_witness_verifier,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    VerifiedManagedTransportCoverage,
    authenticate_managed_transport_coverage,
)

FULL_EXECUTION_EVIDENCE_VARIANT_INVALID = "full_execution_evidence_variant_invalid"
FULL_EXECUTION_EVIDENCE_BINDING_INVALID = "full_execution_evidence_binding_invalid"
FULL_EXECUTION_EVIDENCE_COVERAGE_MISSING = "full_execution_evidence_coverage_missing"
FULL_EXECUTION_EVIDENCE_COVERAGE_DUPLICATE = "full_execution_evidence_coverage_duplicate"
FULL_EXECUTION_EVIDENCE_CROSS_VARIANT_MISMATCH = "full_execution_evidence_cross_variant_mismatch"
FULL_EXECUTION_EVIDENCE_REPLAY = "full_execution_evidence_replay"
FULL_EXECUTION_EVIDENCE_CHANGED = "full_execution_evidence_changed"

_VARIANT_LEGACY = "legacy_v1"
_VARIANT_MANAGED_MEM0_V5 = "managed_mem0_v5"
_BENCHMARKS = frozenset(("locomo", "longmemeval"))
_TOKEN = object()
_HMAC_KEY = secrets.token_bytes(32)
_LOCK = threading.RLock()


class _OpaqueEvidence:
    __slots__ = ()

    def __copy__(self) -> object:
        raise TypeError("full execution evidence is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("full execution evidence is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("full execution evidence is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("full execution evidence is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("full execution evidence is nonserializable")


@final
class FullExecutionTransportEvidence(_OpaqueEvidence):
    """Opaque exact transport variant admitted to full-run validation."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_VARIANT_INVALID)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullExecutionTransportEvidence is final")

    def __repr__(self) -> str:
        return "FullExecutionTransportEvidence(<opaque>)"


@final
class FullExecutionCleanStateEvidence(_OpaqueEvidence):
    """Opaque exact clean-state backend claim admitted to full validation."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_VARIANT_INVALID)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullExecutionCleanStateEvidence is final")

    def __repr__(self) -> str:
        return "FullExecutionCleanStateEvidence(<opaque>)"


@final
@dataclass(frozen=True, slots=True, repr=False)
class FullExecutionTransportEvidenceDescriptor:
    """Sanitized verifier-authenticated immutable transport metadata."""

    variant: str
    benchmark: str
    run_id_sha256: str | None
    backend_roles: tuple[str, ...]
    admission_commitment_sha256: str | None
    authority_commitment_sha256: str | None
    per_corpus_operation_counts: tuple[tuple[str, int], ...]
    operation_count: int
    evidence_commitment_sha256: str

    def __reduce__(self) -> object:
        raise TypeError("full execution evidence descriptors are nonserializable")


@final
@dataclass(frozen=True, slots=True, repr=False)
class FullExecutionCleanStateEvidenceDescriptor:
    """Sanitized verifier-authenticated immutable clean-state metadata."""

    variant: str
    backend_roles: tuple[str, ...]
    run_id_sha256: str | None
    admission_commitment_sha256: str | None
    authority_commitment_sha256: str | None
    corpus_scopes: tuple[tuple[str, str, int], ...]
    evidence_commitment_sha256: str

    def __reduce__(self) -> object:
        raise TypeError("full execution evidence descriptors are nonserializable")


@dataclass(frozen=True, slots=True, repr=False)
class _TransportInspection:
    descriptor: FullExecutionTransportEvidenceDescriptor
    resource_tokens: tuple[str, ...]
    resources: tuple[object, ...]

    def __reduce__(self) -> object:
        raise TypeError("private full execution inspections are nonserializable")


@dataclass(frozen=True, slots=True, repr=False)
class _CleanInspection:
    descriptor: FullExecutionCleanStateEvidenceDescriptor
    resource_tokens: tuple[str, ...]
    resources: tuple[object, ...]

    def __reduce__(self) -> object:
        raise TypeError("private full execution inspections are nonserializable")


@dataclass(frozen=True, slots=True)
class _TransportState:
    variant: str
    benchmark: str
    resources: tuple[object, ...]
    signature: bytes


@dataclass(frozen=True, slots=True)
class _CleanState:
    variant: str
    backend_roles: tuple[str, ...]
    resources: tuple[object, ...]
    signature: bytes


_TRANSPORT: weakref.WeakKeyDictionary[
    FullExecutionTransportEvidence, _TransportState
] = weakref.WeakKeyDictionary()
_CLEAN: weakref.WeakKeyDictionary[
    FullExecutionCleanStateEvidence, _CleanState
] = weakref.WeakKeyDictionary()


def issue_legacy_full_execution_transport_evidence(
    *,
    benchmark: str,
    verifier: RunScopedLocomoTransportEvidenceKey | None,
    evidence: tuple[LocomoTimestampTransportEvidence, ...],
) -> FullExecutionTransportEvidence:
    """Wrap the exact legacy transport resources without changing their contract."""

    if (
        type(benchmark) is not str  # noqa: E721 - exact nominal input required
        or benchmark not in _BENCHMARKS
        or type(evidence) is not tuple
        or any(type(item) is not LocomoTimestampTransportEvidence for item in evidence)
        or (verifier is not None and type(verifier) is not RunScopedLocomoTransportEvidenceKey)
        or (benchmark == "longmemeval" and (verifier is not None or evidence))
        or (benchmark == "locomo" and type(verifier) is not RunScopedLocomoTransportEvidenceKey)
    ):
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID)
    resources: tuple[object, ...] = (
        *((verifier,) if verifier is not None else ()),
        *evidence,
    )
    payload = _legacy_transport_payload(benchmark, verifier, evidence)
    return _register_transport(_VARIANT_LEGACY, benchmark, resources, payload)


def issue_managed_mem0_v5_full_execution_transport_evidence(
    *, coverage: VerifiedManagedTransportCoverage
) -> FullExecutionTransportEvidence:
    """Wrap one exact authenticated managed-v5 transport coverage proof."""

    try:
        trusted = authenticate_managed_transport_coverage(coverage)
    except Exception:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID) from None
    if trusted is not coverage:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID)
    payload = _managed_transport_payload(trusted)
    return _register_transport(
        _VARIANT_MANAGED_MEM0_V5,
        trusted.benchmark,
        (trusted,),
        payload,
    )


def inspect_full_execution_transport_evidence(
    value: object,
) -> FullExecutionTransportEvidenceDescriptor:
    """Return sanitized metadata after revalidating the live origin."""

    return _inspect_full_execution_transport_evidence_for_validation(value).descriptor


def _inspect_full_execution_transport_evidence_for_validation(
    value: object,
) -> _TransportInspection:
    """Private reservation inspection retaining replay resources."""

    if type(value) is not FullExecutionTransportEvidence:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_VARIANT_INVALID)
    with _LOCK:
        state = _TRANSPORT.get(value)
    if state is None:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_VARIANT_INVALID)
    try:
        if state.variant == _VARIANT_LEGACY:
            verifier, evidence = _legacy_transport_resources(state.benchmark, state.resources)
            payload = _legacy_transport_payload(state.benchmark, verifier, evidence)
            descriptor = _legacy_transport_descriptor(state.benchmark, verifier, evidence, payload)
        elif state.variant == _VARIANT_MANAGED_MEM0_V5:
            if len(state.resources) != 1:
                raise ValueError
            coverage = authenticate_managed_transport_coverage(state.resources[0])
            if coverage is not state.resources[0]:
                raise ValueError
            payload = _managed_transport_payload(coverage)
            descriptor = _managed_transport_descriptor(coverage)
        else:
            raise ValueError
    except FullExecutionValidationError:
        raise
    except Exception:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_CHANGED) from None
    _require_signature(state.signature, payload)
    if state.variant == _VARIANT_LEGACY:
        tokens = tuple(f"legacy-transport:{id(item)}" for item in state.resources)
    else:
        tokens = (f"managed-v5-transport:{id(state.resources[0])}",)
    return _TransportInspection(descriptor, tokens, state.resources)


def issue_legacy_full_execution_clean_state_evidence(
    *,
    validation: VerifiedCleanStateValidation,
    scopes: tuple[FullExecutionCleanScope, ...],
    attestation_key: bytes,
    backend_roles: tuple[str, ...] | None = None,
) -> FullExecutionCleanStateEvidence:
    """Wrap an exact legacy DI-authenticated clean-state claim."""

    if (
        type(validation) is not VerifiedCleanStateValidation
        or type(scopes) is not tuple
        or not scopes
        or any(type(item) is not FullExecutionCleanScope for item in scopes)
        or type(attestation_key) is not bytes  # noqa: E721 - exact key type required
        or len(attestation_key) < 32
    ):
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID)
    scope_roles = tuple(dict.fromkeys(item.backend_role for item in scopes))
    roles = scope_roles if backend_roles is None else backend_roles
    if (
        type(roles) is not tuple
        or not roles
        or any(
            type(role) is not str or not role  # noqa: E721 - exact role type required
            for role in roles
        )
        or len(set(roles)) != len(roles)
        or any(role not in scope_roles for role in roles)
    ):
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID)
    for scope in scopes:
        scope.__post_init__()
    resources = (validation, *scopes, attestation_key)
    payload = _legacy_clean_payload(roles, validation, scopes, attestation_key)
    return _register_clean(_VARIANT_LEGACY, roles, resources, payload)


def issue_managed_mem0_v5_full_execution_clean_state_evidence(
    *,
    backend_role: str,
    witness: ManagedMem0V5AuthenticatedCleanStateWitness,
    verifier: ManagedMem0V5CleanStateWitnessVerifierPort,
) -> FullExecutionCleanStateEvidence:
    """Wrap one exact managed-v5 clean-state backend claim."""

    if type(backend_role) is not str or not backend_role:  # noqa: E721
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID)
    try:
        trusted_verifier = require_managed_mem0_v5_clean_state_witness_verifier(verifier)
        trusted = trusted_verifier.authenticate_clean_state(witness)
    except Exception:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID) from None
    if trusted is not witness:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID)
    resources = (trusted, trusted_verifier)
    payload = _managed_clean_payload(backend_role, trusted)
    return _register_clean(
        _VARIANT_MANAGED_MEM0_V5,
        (backend_role,),
        resources,
        payload,
    )


def inspect_full_execution_clean_state_evidence(
    value: object,
) -> FullExecutionCleanStateEvidenceDescriptor:
    """Return sanitized metadata for one authenticated clean-state claim."""

    return _inspect_full_execution_clean_state_evidence_for_validation(value).descriptor


def _inspect_full_execution_clean_state_evidence_for_validation(
    value: object,
) -> _CleanInspection:
    """Private reservation inspection retaining clean replay resources."""

    if type(value) is not FullExecutionCleanStateEvidence:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_VARIANT_INVALID)
    with _LOCK:
        state = _CLEAN.get(value)
    if state is None:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_VARIANT_INVALID)
    try:
        if state.variant == _VARIANT_LEGACY:
            validation, scopes, key = _legacy_clean_resources(state.resources)
            payload = _legacy_clean_payload(state.backend_roles, validation, scopes, key)
            descriptor = _legacy_clean_descriptor(state.backend_roles, validation, scopes, payload)
        elif state.variant == _VARIANT_MANAGED_MEM0_V5:
            if len(state.resources) != 2:
                raise ValueError
            witness = state.resources[0]
            verifier = require_managed_mem0_v5_clean_state_witness_verifier(state.resources[1])
            trusted = verifier.authenticate_clean_state(witness)
            if trusted is not witness:
                raise ValueError
            payload = _managed_clean_payload(state.backend_roles[0], trusted)
            descriptor = _managed_clean_descriptor(state.backend_roles[0], trusted)
        else:
            raise ValueError
    except FullExecutionValidationError:
        raise
    except Exception:
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_CHANGED) from None
    _require_signature(state.signature, payload)
    if state.variant == _VARIANT_LEGACY:
        tokens = (
            f"legacy-clean-validation:{id(state.resources[0])}",
            *(f"legacy-clean-scope:{id(item)}" for item in state.resources[1:-1]),
            "legacy-clean-key:" + hashlib.sha256(state.resources[-1]).hexdigest(),
        )
    else:
        tokens = (
            f"managed-v5-clean-witness:{id(state.resources[0])}",
            f"managed-v5-clean-verifier:{id(state.resources[1])}",
        )
    return _CleanInspection(descriptor, tokens, state.resources)


def _register_transport(
    variant: str,
    benchmark: str,
    resources: tuple[object, ...],
    payload: dict[str, object],
) -> FullExecutionTransportEvidence:
    evidence = FullExecutionTransportEvidence(_token=_TOKEN)
    state = _TransportState(variant, benchmark, resources, _signature(payload))
    with _LOCK:
        _TRANSPORT[evidence] = state
    return evidence


def _register_clean(
    variant: str,
    roles: tuple[str, ...],
    resources: tuple[object, ...],
    payload: dict[str, object],
) -> FullExecutionCleanStateEvidence:
    evidence = FullExecutionCleanStateEvidence(_token=_TOKEN)
    state = _CleanState(variant, roles, resources, _signature(payload))
    with _LOCK:
        _CLEAN[evidence] = state
    return evidence


def _legacy_transport_resources(
    benchmark: str,
    resources: tuple[object, ...],
) -> tuple[
    RunScopedLocomoTransportEvidenceKey | None,
    tuple[LocomoTimestampTransportEvidence, ...],
]:
    if benchmark == "longmemeval":
        if resources:
            raise ValueError
        return None, ()
    if not resources or type(resources[0]) is not RunScopedLocomoTransportEvidenceKey:
        raise ValueError
    evidence = resources[1:]
    if any(type(item) is not LocomoTimestampTransportEvidence for item in evidence):
        raise ValueError
    return resources[0], evidence


def _legacy_clean_resources(
    resources: tuple[object, ...],
) -> tuple[VerifiedCleanStateValidation, tuple[FullExecutionCleanScope, ...], bytes]:
    if len(resources) < 3 or type(resources[0]) is not VerifiedCleanStateValidation:
        raise ValueError
    key = resources[-1]
    scopes = resources[1:-1]
    if (
        type(key) is not bytes  # noqa: E721 - exact key type required
        or len(key) < 32
        or any(type(item) is not FullExecutionCleanScope for item in scopes)
    ):
        raise ValueError
    return resources[0], scopes, key


def _legacy_transport_payload(
    benchmark: str,
    verifier: RunScopedLocomoTransportEvidenceKey | None,
    evidence: tuple[LocomoTimestampTransportEvidence, ...],
) -> dict[str, object]:
    if verifier is not None and not verifier._is_sealed():
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_CHANGED)
    return {
        "variant": _VARIANT_LEGACY,
        "benchmark": benchmark,
        "verifier_identity": id(verifier) if verifier is not None else None,
        "verifier_run_id": verifier._run_id if verifier is not None else None,
        "evidence": [
            {
                "identity": id(item),
                "run_id": item._run_id,
                "commitment_sha256": item._commitment_sha256,
                "proof_sha256": hashlib.sha256(item._proof).hexdigest(),
            }
            for item in evidence
        ],
    }


def _managed_transport_payload(
    coverage: VerifiedManagedTransportCoverage,
) -> dict[str, object]:
    return {
        "variant": _VARIANT_MANAGED_MEM0_V5,
        "resource_identity": id(coverage),
        **coverage.public_payload(),
    }


def _legacy_clean_payload(
    roles: tuple[str, ...],
    validation: VerifiedCleanStateValidation,
    scopes: tuple[FullExecutionCleanScope, ...],
    key: bytes,
) -> dict[str, object]:
    return {
        "variant": _VARIANT_LEGACY,
        "backend_roles": list(roles),
        "validation_identity": id(validation),
        "validation_payload": _json_exact(validation.payload),
        "scopes": [
            {
                "identity": id(item),
                "backend_role": item.backend_role,
                "corpus_identity_sha256": item.corpus_identity_sha256,
                "scope_identity_sha256": item.scope_identity_sha256,
            }
            for item in scopes
        ],
        "attestation_key_sha256": hashlib.sha256(key).hexdigest(),
    }


def _managed_clean_payload(
    backend_role: str,
    witness: ManagedMem0V5AuthenticatedCleanStateWitness,
) -> dict[str, object]:
    return {
        "variant": _VARIANT_MANAGED_MEM0_V5,
        "backend_role": backend_role,
        "resource_identity": id(witness),
        **witness.commitment_payload(),
        "evidence_commitment_sha256": witness.evidence_commitment_sha256,
    }


def _legacy_transport_descriptor(
    benchmark: str,
    verifier: RunScopedLocomoTransportEvidenceKey | None,
    evidence: tuple[LocomoTimestampTransportEvidence, ...],
    payload: dict[str, object],
) -> FullExecutionTransportEvidenceDescriptor:
    return FullExecutionTransportEvidenceDescriptor(
        _VARIANT_LEGACY,
        benchmark,
        hashlib.sha256(verifier._run_id.encode()).hexdigest() if verifier else None,
        (),
        None,
        None,
        (),
        len(evidence),
        _json_sha256(payload),
    )


def _managed_transport_descriptor(
    coverage: VerifiedManagedTransportCoverage,
) -> FullExecutionTransportEvidenceDescriptor:
    return FullExecutionTransportEvidenceDescriptor(
        _VARIANT_MANAGED_MEM0_V5,
        coverage.benchmark,
        coverage.run_id_sha256,
        (coverage.backend_role,),
        coverage.admission_commitment_sha256,
        coverage.authority_commitment_sha256,
        coverage.per_corpus_operation_counts,
        coverage.operation_count,
        coverage.evidence_commitment_sha256,
    )


def _legacy_clean_descriptor(
    roles: tuple[str, ...],
    validation: VerifiedCleanStateValidation,
    scopes: tuple[FullExecutionCleanScope, ...],
    payload: dict[str, object],
) -> FullExecutionCleanStateEvidenceDescriptor:
    del validation
    return FullExecutionCleanStateEvidenceDescriptor(
        _VARIANT_LEGACY,
        roles,
        None,
        None,
        None,
        tuple(
            (item.corpus_identity_sha256, item.scope_identity_sha256, 0)
            for item in scopes
            if item.backend_role in roles
        ),
        _json_sha256(payload),
    )


def _managed_clean_descriptor(
    backend_role: str,
    witness: ManagedMem0V5AuthenticatedCleanStateWitness,
) -> FullExecutionCleanStateEvidenceDescriptor:
    return FullExecutionCleanStateEvidenceDescriptor(
        _VARIANT_MANAGED_MEM0_V5,
        (backend_role,),
        witness.run_id_sha256,
        witness.admission_commitment_sha256,
        witness.authority_commitment_sha256,
        tuple(
            (
                item.corpus_identity_sha256,
                item.scope_identity_sha256,
                item.source_scope_count,
            )
            for item in witness.scopes
        ),
        witness.evidence_commitment_sha256,
    )


def _signature(payload: dict[str, object]) -> bytes:
    return hmac.digest(_HMAC_KEY, _json_bytes(payload), "sha256")


def _require_signature(signature: bytes, payload: dict[str, object]) -> None:
    if not hmac.compare_digest(signature, _signature(payload)):
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_CHANGED)


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _json_exact(value: object) -> object:
    """Detach exact JSON primitives from possibly mutable legacy mappings."""

    try:
        normalized = _normalize_json_mapping(value, depth=0)
        return json.loads(_json_bytes(normalized))
    except (TypeError, ValueError, RuntimeError, RecursionError):
        raise FullExecutionValidationError(FULL_EXECUTION_EVIDENCE_BINDING_INVALID) from None


def _normalize_json_mapping(value: object, *, depth: int) -> object:
    if depth > 32:
        raise ValueError
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:  # noqa: E721 - JSON contract uses exact keys
                raise TypeError
            normalized[key] = _normalize_json_mapping(item, depth=depth + 1)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_normalize_json_mapping(item, depth=depth + 1) for item in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise TypeError


__all__ = (
    "FULL_EXECUTION_EVIDENCE_BINDING_INVALID",
    "FULL_EXECUTION_EVIDENCE_CHANGED",
    "FULL_EXECUTION_EVIDENCE_COVERAGE_DUPLICATE",
    "FULL_EXECUTION_EVIDENCE_COVERAGE_MISSING",
    "FULL_EXECUTION_EVIDENCE_CROSS_VARIANT_MISMATCH",
    "FULL_EXECUTION_EVIDENCE_REPLAY",
    "FULL_EXECUTION_EVIDENCE_VARIANT_INVALID",
    "FullExecutionCleanStateEvidence",
    "FullExecutionCleanStateEvidenceDescriptor",
    "FullExecutionTransportEvidence",
    "FullExecutionTransportEvidenceDescriptor",
    "inspect_full_execution_clean_state_evidence",
    "inspect_full_execution_transport_evidence",
    "issue_legacy_full_execution_clean_state_evidence",
    "issue_legacy_full_execution_transport_evidence",
    "issue_managed_mem0_v5_full_execution_clean_state_evidence",
    "issue_managed_mem0_v5_full_execution_transport_evidence",
)
