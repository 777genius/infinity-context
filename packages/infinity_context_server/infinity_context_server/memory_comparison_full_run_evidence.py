"""Opaque, run-bound evidence for the full memory comparison verdict.

Only nominal live capabilities enter this module. Public report mappings are
projections and are never accepted as evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from dataclasses import dataclass
from typing import Final, final

from infinity_context_server.memory_comparison_full_methodology import (
    FrozenFullComparisonMethodology,
    full_comparison_methodology_contract,
    public_full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    REQUIRED_FULL_COMPARISON_BACKENDS,
    FullComparisonProfile,
    frozen_full_comparison_profile,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_components import (
    live_component_commitment,
    live_component_status,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
    FULL_COMPARISON_SCOPE_FULL,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

FULL_COMPARISON_RUN_EVIDENCE_SCHEMA_VERSION = "memory-comparison-full-run-evidence.v1"
FULL_COMPARISON_COMPONENT_KINDS: Final[tuple[str, ...]] = (
    "provider",
    "runtime",
    "session",
    "clean_state",
    "gold_blind",
    "transport",
    "delete",
    "canonical",
    "source",
)
FULL_COMPARISON_CANARY_WAIVER_CODES: Final[tuple[str, ...]] = (
    "corpus_count_mismatch",
    "dataset_distribution_mismatch",
    "dataset_scope_mismatch",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_BLOCKER_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_TOKEN = object()
_LOCK = threading.RLock()


class FullComparisonEvidenceError(BenchmarkValidationError):
    """Raised when opaque full-run evidence cannot be trusted."""


@final
@dataclass(frozen=True, slots=True)
class FullComparisonBackendTarget:
    """One ordered backend role and its sanitized target commitment."""

    backend_role: str
    target_identity_sha256: str

    def __post_init__(self) -> None:
        if type(self.backend_role) is not str or not _ID_RE.fullmatch(self.backend_role):
            raise FullComparisonEvidenceError("backend role is invalid")
        if not _sha256(self.target_identity_sha256):
            raise FullComparisonEvidenceError("backend target identity must be SHA-256")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonBackendTarget is final")


@final
@dataclass(frozen=True, slots=True)
class FullComparisonRunBindings:
    """Exact immutable primitive bindings shared by every run component."""

    run_id: str
    run_nonce_commitment_sha256: str
    runtime_probe_nonce_sha256: str
    profile_id: str
    methodology_commitment_sha256: str
    dataset_sha256: str
    selection_fingerprint_sha256: str
    backend_targets: tuple[FullComparisonBackendTarget, ...]
    scope: str
    binding_commitment_sha256: str

    def __post_init__(self) -> None:
        _validate_bindings_shape(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonRunBindings is final")


@final
@dataclass(frozen=True, slots=True)
class FullComparisonPolicyBlocker:
    """Nominal blocker input; mutable legacy dictionaries are never admitted."""

    code: str

    def __post_init__(self) -> None:
        if type(self.code) is not str or not _BLOCKER_RE.fullmatch(self.code):
            raise FullComparisonEvidenceError("policy blocker code is invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonPolicyBlocker is final")


class _Opaque:
    __slots__ = ()

    def __copy__(self) -> object:
        raise TypeError("full comparison capabilities are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("full comparison capabilities are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("full comparison capabilities are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("full comparison capabilities are nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("full comparison capabilities are nonserializable")


@final
class FullComparisonEvidenceIssuer(_Opaque):
    """Opaque issuer scoped to one exact binding commitment."""

    __slots__ = ("__binding_commitment", "__nonce", "__weakref__")

    def __init__(self, *, binding_commitment: str, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullComparisonEvidenceError("evidence issuers must be created")
        self.__binding_commitment = binding_commitment
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonEvidenceIssuer is final")

    def __repr__(self) -> str:
        return "FullComparisonEvidenceIssuer(<opaque>)"


@final
class FullComparisonComponentEvidence(_Opaque):
    """Nominal live component admission bound to one opaque issuer."""

    __slots__ = ("__binding_commitment", "__component_kind", "__nonce", "__weakref__")

    def __init__(
        self,
        *,
        component_kind: str,
        binding_commitment: str,
        nonce: str,
        _token: object,
    ) -> None:
        if _token is not _TOKEN:
            raise FullComparisonEvidenceError("component evidence must be issued")
        self.__component_kind = component_kind
        self.__binding_commitment = binding_commitment
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonComponentEvidence is final")

    def __repr__(self) -> str:
        return "FullComparisonComponentEvidence(<sealed>)"


@final
class FullComparisonRunEvidence(_Opaque):
    """Opaque one-shot composite consumed only by verdict verification."""

    __slots__ = ("__binding_commitment", "__nonce", "__weakref__")

    def __init__(self, *, binding_commitment: str, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullComparisonEvidenceError("run evidence must be issued")
        self.__binding_commitment = binding_commitment
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullComparisonRunEvidence is final")

    def __repr__(self) -> str:
        return "FullComparisonRunEvidence(<sealed>)"


@dataclass(frozen=True, slots=True)
class _IssuerState:
    bindings: FullComparisonRunBindings
    secret: bytes
    nonce: str


@dataclass(frozen=True, slots=True)
class _ComponentState:
    issuer: FullComparisonEvidenceIssuer
    component_kind: str
    binding_commitment: str
    nonce: str
    live_validation: object
    live_commitment: str
    proof: str


@dataclass(slots=True)
class _EvidenceState:
    issuer: FullComparisonEvidenceIssuer
    bindings: FullComparisonRunBindings
    components: tuple[FullComparisonComponentEvidence, ...]
    policy_blockers: tuple[FullComparisonPolicyBlocker, ...]
    nonce: str
    proof: str
    consumed: bool = False


@dataclass(frozen=True, slots=True)
class _ComponentResult:
    component_kind: str
    status: str
    blocker: str | None
    binding_commitment_sha256: str


@dataclass(frozen=True, slots=True)
class _InspectedRunEvidence:
    evidence: FullComparisonRunEvidence
    bindings: FullComparisonRunBindings
    components: tuple[_ComponentResult, ...]
    policy_blockers: tuple[str, ...]
    evidence_commitment_sha256: str


_ISSUERS: weakref.WeakKeyDictionary[FullComparisonEvidenceIssuer, _IssuerState] = (
    weakref.WeakKeyDictionary()
)
_COMPONENTS: weakref.WeakKeyDictionary[FullComparisonComponentEvidence, _ComponentState] = (
    weakref.WeakKeyDictionary()
)
_EVIDENCE: weakref.WeakKeyDictionary[FullComparisonRunEvidence, _EvidenceState] = (
    weakref.WeakKeyDictionary()
)


def create_full_comparison_run_bindings(
    *,
    run_id: str,
    run_nonce_commitment_sha256: str,
    runtime_probe_nonce_sha256: str,
    profile: FullComparisonProfile,
    methodology: FrozenFullComparisonMethodology,
    dataset_sha256: str,
    selection_fingerprint_sha256: str,
    backend_targets: tuple[FullComparisonBackendTarget, ...],
    scope: str = FULL_COMPARISON_SCOPE_FULL,
) -> FullComparisonRunBindings:
    """Build bindings after revalidating frozen profile and methodology policy."""

    trusted_profile = frozen_full_comparison_profile(profile)
    methodology_payload = public_full_comparison_methodology_contract(methodology)
    methodology_commitment = _json_sha256(methodology_payload)
    if methodology_payload.get("benchmark") != trusted_profile.benchmark:
        raise FullComparisonEvidenceError("methodology benchmark differs from profile")
    if methodology_payload.get("dataset_sha256") != trusted_profile.expected_dataset_hash:
        raise FullComparisonEvidenceError("methodology dataset differs from profile")
    if (
        scope == FULL_COMPARISON_SCOPE_FULL
        and dataset_sha256 != trusted_profile.expected_dataset_hash
    ):
        raise FullComparisonEvidenceError("dataset differs from frozen profile")
    fields = _binding_fields(
        run_id=run_id,
        run_nonce_commitment_sha256=run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=runtime_probe_nonce_sha256,
        profile_id=trusted_profile.profile_id,
        methodology_commitment_sha256=methodology_commitment,
        dataset_sha256=dataset_sha256,
        selection_fingerprint_sha256=selection_fingerprint_sha256,
        backend_targets=backend_targets,
        scope=scope,
    )
    binding = FullComparisonRunBindings(
        run_id=run_id,
        run_nonce_commitment_sha256=run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=runtime_probe_nonce_sha256,
        profile_id=trusted_profile.profile_id,
        methodology_commitment_sha256=methodology_commitment,
        dataset_sha256=dataset_sha256,
        selection_fingerprint_sha256=selection_fingerprint_sha256,
        backend_targets=backend_targets,
        scope=scope,
        binding_commitment_sha256=_json_sha256(fields),
    )
    return _validate_bindings(binding)


def create_full_comparison_evidence_issuer(
    bindings: FullComparisonRunBindings,
) -> FullComparisonEvidenceIssuer:
    """Create one opaque issuer for exact, currently valid bindings."""

    trusted = _validate_bindings(bindings)
    nonce = secrets.token_hex(32)
    issuer = FullComparisonEvidenceIssuer(
        binding_commitment=trusted.binding_commitment_sha256,
        nonce=nonce,
        _token=_TOKEN,
    )
    with _LOCK:
        _ISSUERS[issuer] = _IssuerState(trusted, secrets.token_bytes(32), nonce)
    return issuer


def issue_full_comparison_run_evidence(
    bindings: FullComparisonRunBindings,
    components: tuple[FullComparisonComponentEvidence, ...],
    issuer: FullComparisonEvidenceIssuer,
    *,
    policy_blockers: tuple[FullComparisonPolicyBlocker, ...] = (),
) -> FullComparisonRunEvidence:
    """Issue one composite without upgrading missing or unwired slots."""

    trusted = _validate_bindings(bindings)
    issuer_state = _issuer_state(issuer)
    if issuer_state.bindings is not bindings:
        raise FullComparisonEvidenceError("issuer and run bindings differ")
    if type(components) is not tuple:
        raise FullComparisonEvidenceError("components must be an exact tuple")
    if type(policy_blockers) is not tuple:
        raise FullComparisonEvidenceError("policy blockers must be an exact tuple")

    kinds: list[str] = []
    component_proofs: list[str] = []
    for component in components:
        state = _component_state(component)
        if state.issuer is not issuer:
            raise FullComparisonEvidenceError("component belongs to another issuer")
        if state.binding_commitment != trusted.binding_commitment_sha256:
            raise FullComparisonEvidenceError("component belongs to another run")
        if state.component_kind in kinds:
            raise FullComparisonEvidenceError("component kind is duplicated")
        kinds.append(state.component_kind)
        component_proofs.append(state.proof)

    blocker_codes: list[str] = []
    for blocker in policy_blockers:
        if type(blocker) is not FullComparisonPolicyBlocker:
            raise FullComparisonEvidenceError("policy blocker type must be exact")
        blocker.__post_init__()
        if blocker.code in blocker_codes:
            raise FullComparisonEvidenceError("policy blocker is duplicated")
        blocker_codes.append(blocker.code)

    nonce = secrets.token_hex(32)
    proof = _evidence_proof(
        secret=issuer_state.secret,
        binding_commitment=trusted.binding_commitment_sha256,
        component_proofs=tuple(component_proofs),
        blocker_codes=tuple(blocker_codes),
        nonce=nonce,
    )
    evidence = FullComparisonRunEvidence(
        binding_commitment=trusted.binding_commitment_sha256,
        nonce=nonce,
        _token=_TOKEN,
    )
    with _LOCK:
        _EVIDENCE[evidence] = _EvidenceState(
            issuer=issuer,
            bindings=bindings,
            components=components,
            policy_blockers=policy_blockers,
            nonce=nonce,
            proof=proof,
        )
    return evidence


def _issue_component(
    issuer: FullComparisonEvidenceIssuer,
    component_kind: str,
    live_validation: object,
    expected_type: type[object],
) -> FullComparisonComponentEvidence:
    issuer_state = _issuer_state(issuer)
    if type(live_validation) is not expected_type:
        raise FullComparisonEvidenceError(f"{component_kind} validation type must be exact")
    nonce = secrets.token_hex(32)
    live_commitment = live_component_commitment(component_kind, live_validation)
    material = {
        "binding_commitment_sha256": issuer_state.bindings.binding_commitment_sha256,
        "component_kind": component_kind,
        "live_commitment": live_commitment,
        "nonce": nonce,
    }
    proof = hmac.new(issuer_state.secret, _canonical_json(material), hashlib.sha256).hexdigest()
    component = FullComparisonComponentEvidence(
        component_kind=component_kind,
        binding_commitment=issuer_state.bindings.binding_commitment_sha256,
        nonce=nonce,
        _token=_TOKEN,
    )
    with _LOCK:
        _COMPONENTS[component] = _ComponentState(
            issuer=issuer,
            component_kind=component_kind,
            binding_commitment=issuer_state.bindings.binding_commitment_sha256,
            nonce=nonce,
            live_validation=live_validation,
            live_commitment=live_commitment,
            proof=proof,
        )
    return component


def _consume_full_comparison_run_evidence(
    evidence: FullComparisonRunEvidence,
) -> _InspectedRunEvidence:
    return _inspect_full_comparison_run_evidence(evidence, consume=True)


def _revalidate_consumed_full_comparison_run_evidence(
    evidence: FullComparisonRunEvidence,
) -> _InspectedRunEvidence:
    return _inspect_full_comparison_run_evidence(evidence, consume=False)


def _inspect_full_comparison_run_evidence(
    evidence: FullComparisonRunEvidence,
    *,
    consume: bool,
) -> _InspectedRunEvidence:
    if type(evidence) is not FullComparisonRunEvidence:
        raise FullComparisonEvidenceError("run evidence type must be exact")
    with _LOCK:
        state = _EVIDENCE.get(evidence)
        if state is None:
            raise FullComparisonEvidenceError("run evidence was not issued")
        if consume and state.consumed:
            raise FullComparisonEvidenceError("run evidence was already consumed")
        if not consume and not state.consumed:
            raise FullComparisonEvidenceError("run evidence has not been consumed")
        if consume:
            state.consumed = True

    bindings = _validate_bindings(state.bindings)
    issuer_state = _issuer_state(state.issuer)
    _validate_opaque(
        evidence,
        bindings.binding_commitment_sha256,
        state.nonce,
        class_name="FullComparisonRunEvidence",
    )
    component_proofs: list[str] = []
    results: list[_ComponentResult] = []
    seen: set[str] = set()
    for component in state.components:
        component_state = _component_state(component)
        if component_state.issuer is not state.issuer:
            raise FullComparisonEvidenceError("component issuer changed")
        if component_state.component_kind in seen:
            raise FullComparisonEvidenceError("component kind became duplicated")
        seen.add(component_state.component_kind)
        component_proofs.append(component_state.proof)
        results.append(_revalidate_component(component, component_state, bindings))

    blocker_codes: list[str] = []
    for blocker in state.policy_blockers:
        if type(blocker) is not FullComparisonPolicyBlocker:
            raise FullComparisonEvidenceError("policy blocker type changed")
        blocker.__post_init__()
        if blocker.code in blocker_codes:
            raise FullComparisonEvidenceError("policy blocker became duplicated")
        blocker_codes.append(blocker.code)

    expected_proof = _evidence_proof(
        secret=issuer_state.secret,
        binding_commitment=bindings.binding_commitment_sha256,
        component_proofs=tuple(component_proofs),
        blocker_codes=tuple(blocker_codes),
        nonce=state.nonce,
    )
    if not hmac.compare_digest(expected_proof, state.proof):
        raise FullComparisonEvidenceError("run evidence integrity failed")
    commitment = _json_sha256(
        {
            "binding_commitment_sha256": bindings.binding_commitment_sha256,
            "component_proofs": component_proofs,
            "policy_blockers": blocker_codes,
            "proof": state.proof,
        }
    )
    return _InspectedRunEvidence(
        evidence=evidence,
        bindings=bindings,
        components=tuple(results),
        policy_blockers=tuple(blocker_codes),
        evidence_commitment_sha256=commitment,
    )


def _revalidate_component(
    component: FullComparisonComponentEvidence,
    state: _ComponentState,
    bindings: FullComparisonRunBindings,
) -> _ComponentResult:
    _validate_opaque(
        component,
        state.binding_commitment,
        state.nonce,
        class_name="FullComparisonComponentEvidence",
        component_kind=state.component_kind,
    )
    issuer_state = _issuer_state(state.issuer)
    current_live_commitment = live_component_commitment(state.component_kind, state.live_validation)
    material = {
        "binding_commitment_sha256": state.binding_commitment,
        "component_kind": state.component_kind,
        "live_commitment": current_live_commitment,
        "nonce": state.nonce,
    }
    expected_proof = hmac.new(
        issuer_state.secret, _canonical_json(material), hashlib.sha256
    ).hexdigest()
    if not (
        hmac.compare_digest(current_live_commitment, state.live_commitment)
        and hmac.compare_digest(expected_proof, state.proof)
    ):
        raise FullComparisonEvidenceError("component evidence integrity failed")
    status, blocker = live_component_status(state.component_kind, state.live_validation, bindings)
    return _ComponentResult(
        component_kind=state.component_kind,
        status=status,
        blocker=blocker,
        binding_commitment_sha256=state.binding_commitment,
    )


def _issuer_state(issuer: FullComparisonEvidenceIssuer) -> _IssuerState:
    if type(issuer) is not FullComparisonEvidenceIssuer:
        raise FullComparisonEvidenceError("issuer type must be exact")
    with _LOCK:
        state = _ISSUERS.get(issuer)
    if state is None:
        raise FullComparisonEvidenceError("issuer was not created")
    _validate_opaque(
        issuer,
        state.bindings.binding_commitment_sha256,
        state.nonce,
        class_name="FullComparisonEvidenceIssuer",
    )
    _validate_bindings(state.bindings)
    return state


def _component_state(component: FullComparisonComponentEvidence) -> _ComponentState:
    if type(component) is not FullComparisonComponentEvidence:
        raise FullComparisonEvidenceError("component evidence type must be exact")
    with _LOCK:
        state = _COMPONENTS.get(component)
    if state is None:
        raise FullComparisonEvidenceError("component evidence was not issued")
    return state


def _validate_opaque(
    value: object,
    binding_commitment: str,
    nonce: str,
    *,
    class_name: str,
    component_kind: str | None = None,
) -> None:
    prefix = f"_{class_name}__"
    try:
        current_binding = getattr(value, f"{prefix}binding_commitment")
        current_nonce = getattr(value, f"{prefix}nonce")
        current_kind = (
            getattr(value, f"{prefix}component_kind") if component_kind is not None else None
        )
    except (AttributeError, TypeError):
        raise FullComparisonEvidenceError(f"{class_name} integrity failed") from None
    if (
        type(current_binding) is not str
        or type(current_nonce) is not str
        or not hmac.compare_digest(current_binding, binding_commitment)
        or not hmac.compare_digest(current_nonce, nonce)
        or (component_kind is not None and current_kind != component_kind)
    ):
        raise FullComparisonEvidenceError(f"{class_name} integrity failed")


def _validate_bindings(bindings: FullComparisonRunBindings) -> FullComparisonRunBindings:
    if type(bindings) is not FullComparisonRunBindings:
        raise FullComparisonEvidenceError("run bindings type must be exact")
    _validate_bindings_shape(bindings)
    fields = _binding_fields(
        run_id=bindings.run_id,
        run_nonce_commitment_sha256=bindings.run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=bindings.runtime_probe_nonce_sha256,
        profile_id=bindings.profile_id,
        methodology_commitment_sha256=bindings.methodology_commitment_sha256,
        dataset_sha256=bindings.dataset_sha256,
        selection_fingerprint_sha256=bindings.selection_fingerprint_sha256,
        backend_targets=bindings.backend_targets,
        scope=bindings.scope,
    )
    if not hmac.compare_digest(_json_sha256(fields), bindings.binding_commitment_sha256):
        raise FullComparisonEvidenceError("run binding commitment differs from fields")
    profile = _profile(bindings.profile_id)
    if (
        bindings.scope == FULL_COMPARISON_SCOPE_FULL
        and bindings.dataset_sha256 != profile.expected_dataset_hash
    ):
        raise FullComparisonEvidenceError("run dataset differs from profile")
    expected_methodology = _json_sha256(
        public_full_comparison_methodology_contract(full_comparison_methodology_contract(profile))
    )
    if not hmac.compare_digest(bindings.methodology_commitment_sha256, expected_methodology):
        raise FullComparisonEvidenceError("run methodology differs from profile")
    return bindings


def _validate_bindings_shape(bindings: FullComparisonRunBindings) -> None:
    if type(bindings.run_id) is not str or not _ID_RE.fullmatch(bindings.run_id):
        raise FullComparisonEvidenceError("run_id is invalid")
    for value in (
        bindings.run_nonce_commitment_sha256,
        bindings.runtime_probe_nonce_sha256,
        bindings.methodology_commitment_sha256,
        bindings.dataset_sha256,
        bindings.selection_fingerprint_sha256,
        bindings.binding_commitment_sha256,
    ):
        if not _sha256(value):
            raise FullComparisonEvidenceError("run binding digest must be SHA-256")
    if type(bindings.profile_id) is not str or not _ID_RE.fullmatch(bindings.profile_id):
        raise FullComparisonEvidenceError("profile_id is invalid")
    if bindings.scope not in {FULL_COMPARISON_SCOPE_FULL, FULL_COMPARISON_SCOPE_CANARY}:
        raise FullComparisonEvidenceError("full comparison scope is invalid")
    if type(bindings.backend_targets) is not tuple or any(
        type(item) is not FullComparisonBackendTarget for item in bindings.backend_targets
    ):
        raise FullComparisonEvidenceError("backend targets must be an exact typed tuple")
    for item in bindings.backend_targets:
        item.__post_init__()
    roles = tuple(item.backend_role for item in bindings.backend_targets)
    if roles != REQUIRED_FULL_COMPARISON_BACKENDS:
        raise FullComparisonEvidenceError("backend targets must match exact ordered roles")
    identities = tuple(item.target_identity_sha256 for item in bindings.backend_targets)
    if len(set(identities)) != len(identities):
        raise FullComparisonEvidenceError("backend target identities must be distinct")


def _binding_fields(
    *,
    run_id: str,
    run_nonce_commitment_sha256: str,
    runtime_probe_nonce_sha256: str,
    profile_id: str,
    methodology_commitment_sha256: str,
    dataset_sha256: str,
    selection_fingerprint_sha256: str,
    backend_targets: tuple[FullComparisonBackendTarget, ...],
    scope: str,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "run_nonce_commitment_sha256": run_nonce_commitment_sha256,
        "runtime_probe_nonce_sha256": runtime_probe_nonce_sha256,
        "profile_id": profile_id,
        "methodology_commitment_sha256": methodology_commitment_sha256,
        "dataset_sha256": dataset_sha256,
        "selection_fingerprint_sha256": selection_fingerprint_sha256,
        "backend_targets": [
            {
                "backend_role": item.backend_role,
                "target_identity_sha256": item.target_identity_sha256,
            }
            for item in backend_targets
        ],
        "scope": scope,
    }


def _profile(profile_id: str) -> FullComparisonProfile:
    profile = resolve_full_comparison_profile(profile_id)
    if profile is None:
        raise FullComparisonEvidenceError("full comparison profile is missing")
    return frozen_full_comparison_profile(profile)


def _evidence_proof(
    *,
    secret: bytes,
    binding_commitment: str,
    component_proofs: tuple[str, ...],
    blocker_codes: tuple[str, ...],
    nonce: str,
) -> str:
    return hmac.new(
        secret,
        _canonical_json(
            {
                "binding_commitment_sha256": binding_commitment,
                "component_proofs": component_proofs,
                "policy_blockers": blocker_codes,
                "nonce": nonce,
            }
        ),
        hashlib.sha256,
    ).hexdigest()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


__all__ = (
    "FULL_COMPARISON_CANARY_WAIVER_CODES",
    "FULL_COMPARISON_COMPONENT_KINDS",
    "FULL_COMPARISON_RUN_EVIDENCE_SCHEMA_VERSION",
    "FullComparisonBackendTarget",
    "FullComparisonComponentEvidence",
    "FullComparisonEvidenceError",
    "FullComparisonEvidenceIssuer",
    "FullComparisonPolicyBlocker",
    "FullComparisonRunBindings",
    "FullComparisonRunEvidence",
    "create_full_comparison_evidence_issuer",
    "create_full_comparison_run_bindings",
    "issue_full_comparison_run_evidence",
)
