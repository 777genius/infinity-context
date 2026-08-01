"""Opaque complete execution evidence authority for managed HTTP lifecycle."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import weakref
from collections.abc import Mapping
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_backend_target import FullComparisonBackendTarget
from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
    public_clean_state_validation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCleanScope,
)
from infinity_context_server.memory_comparison_full_profiles import (
    REQUIRED_FULL_COMPARISON_BACKENDS,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase

_TOKEN = object()
_LOCK = threading.RLock()


class ManagedHttpExecutionEvidenceError(RuntimeError):
    """Fixed-code evidence authority failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedHttpExecutionEvidenceCapability:
    """Opaque one-use complete reset and timestamp evidence authority."""

    __slots__ = ("__weakref__",)

    def __init__(self, *, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_evidence_forged")

    def __repr__(self) -> str:
        return "ManagedHttpExecutionEvidenceCapability(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedHttpExecutionEvidenceCapability is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpExecutionEvidenceCapability is final")


@final
class ManagedHttpExecutionEvidenceView:
    """Reverification inputs with a repr-hidden run-scoped attestation key."""

    __slots__ = (
        "validation",
        "scopes",
        "provenance",
        "__attestation_key",
        "__locomo_verifier",
        "__locomo_evidence",
    )

    def __init__(
        self,
        *,
        validation: VerifiedCleanStateValidation,
        scopes: tuple[FullExecutionCleanScope, ...],
        provenance: Mapping[str, object],
        attestation_key: bytes,
        locomo_verifier: RunScopedLocomoTransportEvidenceKey | None,
        locomo_evidence: tuple[LocomoTimestampTransportEvidence, ...],
        _token: object,
    ) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_view_forged")
        self.validation = validation
        self.scopes = scopes
        self.provenance = MappingProxyType(dict(provenance))
        self.__attestation_key = attestation_key
        self.__locomo_verifier = locomo_verifier
        self.__locomo_evidence = locomo_evidence

    @property
    def attestation_key(self) -> bytes:
        return self.__attestation_key

    @property
    def locomo_timestamp_verifier(self) -> RunScopedLocomoTransportEvidenceKey | None:
        return self.__locomo_verifier

    @property
    def locomo_timestamp_evidence(
        self,
    ) -> tuple[LocomoTimestampTransportEvidence, ...]:
        return self.__locomo_evidence

    def __repr__(self) -> str:
        return "ManagedHttpExecutionEvidenceView(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("ManagedHttpExecutionEvidenceView is nonserializable")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpExecutionEvidenceView is final")


class _State:
    def __init__(
        self,
        *,
        owner: object,
        secret: bytes,
        run_id: str,
        binding: str,
        target_pairs: tuple[tuple[str, str], ...],
        case_bindings: tuple[tuple[str, str], ...],
        validation: VerifiedCleanStateValidation,
        scopes: tuple[FullExecutionCleanScope, ...],
        provenance: MappingProxyType[str, object],
        attestation_key: bytes,
        expected_ingest_count: int,
    ) -> None:
        self.owner = owner
        self.secret = secret
        self.run_id = run_id
        self.binding = binding
        self.target_pairs = target_pairs
        self.case_bindings = case_bindings
        self.validation = validation
        self.scopes = scopes
        self.provenance = provenance
        self.attestation_key = attestation_key
        self.expected_ingest_count = expected_ingest_count
        self.completed_ingest_count = 0
        self.locomo_verifier: RunScopedLocomoTransportEvidenceKey | None = None
        self.locomo_evidence: tuple[LocomoTimestampTransportEvidence, ...] = ()
        self.phase = "live"
        self.commitment = _commitment(self)


_STATES: weakref.WeakKeyDictionary[ManagedHttpExecutionEvidenceCapability, _State] = (
    weakref.WeakKeyDictionary()
)


def _new_execution_evidence(
    *,
    owner: object,
    secret: bytes,
    run_id: str,
    binding: str,
    target_pairs: tuple[tuple[str, str], ...],
    case_bindings: tuple[tuple[str, str], ...],
    validation: VerifiedCleanStateValidation,
    scopes: tuple[FullExecutionCleanScope, ...],
    provenance: MappingProxyType[str, object],
    attestation_key: bytes,
    expected_ingest_count: int,
) -> ManagedHttpExecutionEvidenceCapability:
    capability = ManagedHttpExecutionEvidenceCapability(_token=_TOKEN)
    state = _State(
        owner=owner,
        secret=secret,
        run_id=run_id,
        binding=binding,
        target_pairs=target_pairs,
        case_bindings=case_bindings,
        validation=validation,
        scopes=scopes,
        provenance=provenance,
        attestation_key=attestation_key,
        expected_ingest_count=expected_ingest_count,
    )
    with _LOCK:
        _STATES[capability] = state
    return capability


def _advance_execution_evidence(
    capability: object,
    verifier: RunScopedLocomoTransportEvidenceKey | None,
    evidence: tuple[LocomoTimestampTransportEvidence, ...],
) -> None:
    with _LOCK:
        state = _state(capability)
        if state.phase != "live" or state.completed_ingest_count >= state.expected_ingest_count:
            state.phase = "terminal"
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_evidence_replay")
        if verifier is not None and type(verifier) is not RunScopedLocomoTransportEvidenceKey:
            state.phase = "terminal"
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_verifier_invalid")
        if type(evidence) is not tuple or any(
            type(item) is not LocomoTimestampTransportEvidence for item in evidence
        ):
            state.phase = "terminal"
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_timestamp_invalid")
        if (
            state.locomo_verifier is not None
            and verifier is not None
            and verifier is not state.locomo_verifier
        ):
            state.phase = "terminal"
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_verifier_changed")
        if verifier is not None:
            state.locomo_verifier = verifier
        state.locomo_evidence = (*state.locomo_evidence, *evidence)
        state.completed_ingest_count += 1
        state.commitment = _commitment(state)


def terminalize_managed_http_execution_evidence(capability: object) -> None:
    if type(capability) is not ManagedHttpExecutionEvidenceCapability:
        return
    with _LOCK:
        state = _STATES.get(capability)
        if state is not None:
            state.phase = "terminal"


def consume_managed_http_execution_evidence(
    capability: object,
    *,
    run_id: str,
    binding_commitment_sha256: str,
    backend_targets: tuple[FullComparisonBackendTarget, ...],
    cases: tuple[ManagedRunCase, ...],
) -> ManagedHttpExecutionEvidenceView:
    """Burn one exact fully-covered authority before exposing the live material."""

    with _LOCK:
        state = _state(capability)
        try:
            expected_targets = _target_pairs(backend_targets)
            expected_cases = _case_bindings(cases)
            if (
                state.phase != "live"
                or state.run_id != run_id
                or state.binding != binding_commitment_sha256
                or state.target_pairs != expected_targets
                or state.case_bindings != expected_cases
                or state.completed_ingest_count != state.expected_ingest_count
                or state.expected_ingest_count != len(expected_targets) * len(expected_cases)
                or not hmac.compare_digest(state.commitment, _commitment(state))
            ):
                raise ManagedHttpExecutionEvidenceError(
                    "managed_http_execution_evidence_binding_invalid"
                )
            _validate_scopes(state.scopes, expected_targets, expected_cases)
            state.phase = "consuming"
            view = ManagedHttpExecutionEvidenceView(
                validation=state.validation,
                scopes=state.scopes,
                provenance=state.provenance,
                attestation_key=state.attestation_key,
                locomo_verifier=state.locomo_verifier,
                locomo_evidence=state.locomo_evidence,
                _token=_TOKEN,
            )
        except BaseException:
            state.phase = "terminal"
            raise
        state.phase = "consumed"
        return view


def _state(value: object) -> _State:
    if type(value) is not ManagedHttpExecutionEvidenceCapability:
        raise ManagedHttpExecutionEvidenceError("managed_http_execution_capability_invalid")
    state = _STATES.get(value)
    if state is None:
        raise ManagedHttpExecutionEvidenceError("managed_http_execution_capability_unknown")
    return state


def _target_pairs(value: object) -> tuple[tuple[str, str], ...]:
    if (
        type(value) is not tuple
        or any(type(item) is not FullComparisonBackendTarget for item in value)
        or tuple(item.backend_role for item in value) != REQUIRED_FULL_COMPARISON_BACKENDS
    ):
        raise ManagedHttpExecutionEvidenceError("managed_http_execution_targets_invalid")
    return tuple((item.backend_role, item.target_identity_sha256) for item in value)


def _case_bindings(value: object) -> tuple[tuple[str, str], ...]:
    if (
        type(value) is not tuple
        or not value
        or any(type(item) is not ManagedRunCase for item in value)
    ):
        raise ManagedHttpExecutionEvidenceError("managed_http_execution_cases_invalid")
    by_corpus: dict[str, ManagedRunCase] = {}
    for case in value:
        current = by_corpus.get(case.corpus_id)
        if current is None:
            by_corpus[case.corpus_id] = case
        elif current.record != case.record:
            raise ManagedHttpExecutionEvidenceError("managed_http_execution_corpus_conflict")
    return tuple((case.case_id, case.corpus_id) for case in by_corpus.values())


def _validate_scopes(
    scopes: object,
    targets: tuple[tuple[str, str], ...],
    cases: tuple[tuple[str, str], ...],
) -> None:
    if (
        type(scopes) is not tuple
        or any(type(item) is not FullExecutionCleanScope for item in scopes)
        or tuple(item.backend_role for item in scopes)
        != tuple(role for role, _ in targets for _case in cases)
        or tuple(item.corpus_identity_sha256 for item in scopes)
        != tuple(
            hashlib.sha256(corpus_id.encode()).hexdigest()
            for _role, _target in targets
            for _case_id, corpus_id in cases
        )
    ):
        raise ManagedHttpExecutionEvidenceError("managed_http_execution_scopes_invalid")


def _commitment(state: _State) -> str:
    material = {
        "run_id": state.run_id,
        "binding": state.binding,
        "targets": state.target_pairs,
        "cases": state.case_bindings,
        "clean": public_clean_state_validation(state.validation),
        "scopes": [
            [item.backend_role, item.corpus_identity_sha256, item.scope_identity_sha256]
            for item in state.scopes
        ],
        "provenance": dict(state.provenance),
        "attestation_key_sha256": hashlib.sha256(state.attestation_key).hexdigest(),
        "expected_ingest_count": state.expected_ingest_count,
        "completed_ingest_count": state.completed_ingest_count,
        "locomo_verifier_identity": (
            id(state.locomo_verifier) if state.locomo_verifier is not None else None
        ),
        "locomo_evidence_identities": [id(item) for item in state.locomo_evidence],
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(state.secret, canonical, hashlib.sha256).hexdigest()


__all__ = (
    "ManagedHttpExecutionEvidenceCapability",
    "ManagedHttpExecutionEvidenceError",
    "ManagedHttpExecutionEvidenceView",
    "consume_managed_http_execution_evidence",
)
