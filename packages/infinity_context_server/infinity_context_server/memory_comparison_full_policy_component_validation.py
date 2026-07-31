"""One-shot aggregate admission for full-run policy evidence.

Canonical, source, and terminal-delete reports are telemetry. This module
accepts only their live nominal capabilities, checks exact manifest coverage,
and issues one opaque validation after every component has been consumed.
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
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_full_canonical_evidence import (
    INFINITY_CANONICAL_BACKEND_ID,
    VerifiedCanonicalEvidence,
    consume_canonical_evidence,
    public_canonical_evidence_report,
)
from infinity_context_server.memory_comparison_full_canonical_source_evidence_trust import (
    CanonicalSourceEvidenceTrustPolicy,
)
from infinity_context_server.memory_comparison_full_delete_evidence import (
    SealedTerminalDeleteEvidence,
    TerminalDeleteEvidenceSession,
    consume_terminal_delete_evidence,
    terminal_delete_evidence_report,
)
from infinity_context_server.memory_comparison_full_delete_evidence_trust import (
    DeleteVerificationTrustPolicy,
)
from infinity_context_server.memory_comparison_full_source_evidence import (
    INFINITY_SOURCE_BACKEND_ID,
    MEM0_SOURCE_BACKEND_ID,
    VerifiedSourceEvidence,
    consume_source_evidence,
    public_source_evidence_report,
)

FULL_POLICY_COMPONENT_VALIDATION_SCHEMA_VERSION = (
    "memory-comparison-full-policy-component-validation.v1"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_TEXT = 16_384
_TOKEN = object()
_LOCK = threading.RLock()


class FullPolicyComponentValidationError(ValueError):
    """Raised when policy components cannot produce exact aggregate admission."""


@final
@dataclass(frozen=True, slots=True)
class FullPolicyManifestItem:
    """One expected canonical/source identity in the selected run manifest."""

    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str

    def __post_init__(self) -> None:
        _manifest_item_snapshot(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullPolicyManifestItem is final")


@final
@dataclass(frozen=True, slots=True)
class FullPolicyRunManifest:
    """Exact primitive bindings expected from every policy component."""

    run_id: str
    profile_id: str
    infinity_backend_id: str
    mem0_backend_id: str
    scope_id: str
    delete_source_id: str
    managed_attestation_commitment_sha256: str
    items: tuple[FullPolicyManifestItem, ...]

    def __post_init__(self) -> None:
        _manifest_snapshot(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullPolicyRunManifest is final")


@final
@dataclass(frozen=True, slots=True)
class FullPolicyEvidencePair:
    """One canonical/source proof pair issued from one exact item policy."""

    canonical: VerifiedCanonicalEvidence
    source: VerifiedSourceEvidence
    trust_policy: CanonicalSourceEvidenceTrustPolicy

    def __post_init__(self) -> None:
        if type(self.canonical) is not VerifiedCanonicalEvidence:
            raise FullPolicyComponentValidationError("canonical proof type must be exact")
        if type(self.source) is not VerifiedSourceEvidence:
            raise FullPolicyComponentValidationError("source proof type must be exact")
        if type(self.trust_policy) is not CanonicalSourceEvidenceTrustPolicy:
            raise FullPolicyComponentValidationError("item trust policy type must be exact")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullPolicyEvidencePair is final")


@final
@dataclass(frozen=True, slots=True)
class FullPolicyTerminalDeleteEvidence:
    """The one terminal-delete capability required by the aggregate."""

    evidence: SealedTerminalDeleteEvidence
    session: TerminalDeleteEvidenceSession
    trust_policy: DeleteVerificationTrustPolicy

    def __post_init__(self) -> None:
        if type(self.evidence) is not SealedTerminalDeleteEvidence:
            raise FullPolicyComponentValidationError("delete proof type must be exact")
        if type(self.session) is not TerminalDeleteEvidenceSession:
            raise FullPolicyComponentValidationError("delete session type must be exact")
        if type(self.trust_policy) is not DeleteVerificationTrustPolicy:
            raise FullPolicyComponentValidationError("delete trust policy type must be exact")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullPolicyTerminalDeleteEvidence is final")


class _Opaque:
    __slots__ = ()

    def __copy__(self) -> object:
        raise TypeError("full policy capabilities are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("full policy capabilities are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("full policy capabilities are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("full policy capabilities are nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("full policy capabilities are nonserializable")


@final
class FullPolicyComponentValidationSession(_Opaque):
    """Opaque single-attempt aggregate lifecycle."""

    __slots__ = ("__nonce", "__weakref__")

    def __init__(self, *, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullPolicyComponentValidationError("validation sessions must be issued")
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("FullPolicyComponentValidationSession is final")

    def __repr__(self) -> str:
        return "FullPolicyComponentValidationSession(<opaque>)"


@final
class VerifiedFullPolicyComponentValidation(_Opaque):
    """Opaque live aggregate suitable for later composite component adapters."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise FullPolicyComponentValidationError("validations must be sealed")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedFullPolicyComponentValidation is final")

    def __repr__(self) -> str:
        return "VerifiedFullPolicyComponentValidation(<sealed>)"


@dataclass(frozen=True, slots=True)
class _ItemSnapshot:
    case_id: str
    source_ref: str
    source_revision: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class _ManifestSnapshot:
    run_id: str
    profile_id: str
    infinity_backend_id: str
    mem0_backend_id: str
    scope_id: str
    delete_source_id: str
    managed_attestation_commitment_sha256: str
    items: tuple[_ItemSnapshot, ...]
    commitment_sha256: str


@dataclass(slots=True)
class _SessionState:
    manifest: _ManifestSnapshot
    evidence_pairs: tuple[FullPolicyEvidencePair, ...]
    terminal_delete: FullPolicyTerminalDeleteEvidence
    consumer_id: str
    phase: str
    started_count: int
    completed_count: int
    active_position: str | None
    active_owner: int | None
    validation: VerifiedFullPolicyComponentValidation | None


@dataclass(frozen=True, slots=True)
class _PreflightSnapshot:
    canonical_reports: tuple[dict[str, object], ...]
    source_reports: tuple[dict[str, object], ...]
    delete_report: dict[str, object]
    item_policy_commitments: tuple[str, ...]
    delete_policy_commitment: str


@dataclass(frozen=True, slots=True)
class _ValidationState:
    session: FullPolicyComponentValidationSession
    manifest: _ManifestSnapshot
    evidence_pairs: tuple[FullPolicyEvidencePair, ...]
    terminal_delete: FullPolicyTerminalDeleteEvidence
    input_commitments: tuple[str, ...]
    report: MappingProxyType[str, object]
    secret: bytes
    commitment: str


_SESSIONS: weakref.WeakKeyDictionary[FullPolicyComponentValidationSession, _SessionState] = (
    weakref.WeakKeyDictionary()
)
_VALIDATIONS: weakref.WeakKeyDictionary[VerifiedFullPolicyComponentValidation, _ValidationState] = (
    weakref.WeakKeyDictionary()
)


def create_full_policy_component_validation_session(
    *,
    manifest: FullPolicyRunManifest,
    evidence_pairs: tuple[FullPolicyEvidencePair, ...],
    terminal_delete: FullPolicyTerminalDeleteEvidence,
    consumer_id: str,
) -> FullPolicyComponentValidationSession:
    """Register one exact single-attempt aggregate without consuming evidence."""

    snapshot = _manifest_snapshot(manifest)
    if type(evidence_pairs) is not tuple:
        raise FullPolicyComponentValidationError("evidence_pairs must be an exact tuple")
    if len(evidence_pairs) != len(snapshot.items):
        raise FullPolicyComponentValidationError("policy evidence count differs from manifest")
    if any(type(pair) is not FullPolicyEvidencePair for pair in evidence_pairs):
        raise FullPolicyComponentValidationError("policy evidence pair type must be exact")
    if type(terminal_delete) is not FullPolicyTerminalDeleteEvidence:
        raise FullPolicyComponentValidationError("terminal_delete type must be exact")
    checked_consumer = _text(consumer_id, "consumer_id", maximum=200)
    session = FullPolicyComponentValidationSession(nonce=secrets.token_hex(32), _token=_TOKEN)
    with _LOCK:
        _SESSIONS[session] = _SessionState(
            snapshot,
            evidence_pairs,
            terminal_delete,
            checked_consumer,
            "open",
            0,
            0,
            None,
            None,
            None,
        )
    return session


def seal_full_policy_component_validation(
    session: FullPolicyComponentValidationSession,
) -> VerifiedFullPolicyComponentValidation:
    """Preflight all proofs, consume deterministically, and delete strictly last.

    Lower-level proof APIs do not expose a cross-module rollback transaction.
    A failure after any successful consume permanently aborts this session as
    partial_component_consumption and never mints validation.
    Concurrent callers that observe active consumption fail immediately instead
    of joining the owner's lifecycle.
    """

    state = _session_state(session)
    owner = threading.get_ident()
    validation: VerifiedFullPolicyComponentValidation | None = None
    with _LOCK:
        if state.phase == "consuming":
            raise FullPolicyComponentValidationError("aggregate consumption already active")
        if state.phase != "open":
            raise FullPolicyComponentValidationError(
                f"validation session is terminal or active: {state.phase}"
            )
        state.phase = "preflighting"
        state.active_owner = owner
    try:
        preflight = _preflight(state)
    except BaseException as exc:
        with _LOCK:
            state.phase = "preflight_failed"
            state.active_owner = None
        if isinstance(exc, Exception):
            raise FullPolicyComponentValidationError("policy component preflight failed") from None
        raise

    with _LOCK:
        if state.phase != "preflighting" or state.active_owner != owner:
            raise FullPolicyComponentValidationError("validation session changed")
        state.phase = "consuming"
    try:
        _consume_components(state)
        secret = secrets.token_bytes(32)
        input_commitments = _input_commitments(preflight)
        report = _aggregate_report(state, preflight)
        commitment = _commitment(secret, report)
        report["commitment"] = commitment
        validation = VerifiedFullPolicyComponentValidation(
            commitment=commitment,
            _token=_TOKEN,
        )
        validation_state = _ValidationState(
            session,
            state.manifest,
            state.evidence_pairs,
            state.terminal_delete,
            input_commitments,
            MappingProxyType(report),
            secret,
            commitment,
        )
        with _LOCK:
            expected_count = len(state.evidence_pairs) * 2 + 1
            if (
                state.phase != "consuming"
                or state.active_owner != owner
                or state.active_position is not None
                or state.started_count != expected_count
                or state.completed_count != expected_count
            ):
                raise FullPolicyComponentValidationError("component consumption progress changed")
            _VALIDATIONS[validation] = validation_state
            state.validation = validation
            state.phase = "sealed"
            state.active_owner = None
    except BaseException as exc:
        with _LOCK:
            if validation is not None:
                _VALIDATIONS.pop(validation, None)
            state.validation = None
            state.phase = "partial_component_consumption"
            state.active_owner = None
        if isinstance(exc, Exception):
            raise FullPolicyComponentValidationError(
                "policy component consumption failed"
            ) from None
        raise
    assert validation is not None
    return validation


def full_policy_component_validation_session_status(
    session: FullPolicyComponentValidationSession,
) -> str:
    """Return lifecycle telemetry; the string is never admission evidence."""

    return _session_state(session).phase


def public_full_policy_component_validation(
    validation: VerifiedFullPolicyComponentValidation,
) -> dict[str, object]:
    """Revalidate the live capability and return JSON-safe telemetry."""

    state = _validation_state(validation)
    current = _preflight_from_validation(state)
    if _input_commitments(current) != state.input_commitments:
        raise FullPolicyComponentValidationError("policy component evidence changed")
    report = dict(state.report)
    commitment = report.pop("commitment", None)
    if (
        type(commitment) is not str
        or not hmac.compare_digest(commitment, state.commitment)
        or not hmac.compare_digest(_commitment(state.secret, report), state.commitment)
    ):
        raise FullPolicyComponentValidationError("policy validation integrity failed")
    report["commitment"] = commitment
    return _thaw(report)


def full_policy_run_manifest_commitment(manifest: FullPolicyRunManifest) -> str:
    """Return the deterministic primitive manifest commitment."""

    return _manifest_snapshot(manifest).commitment_sha256


def _preflight(state: _SessionState) -> _PreflightSnapshot:
    return _preflight_inputs(state.manifest, state.evidence_pairs, state.terminal_delete)


def _preflight_from_validation(state: _ValidationState) -> _PreflightSnapshot:
    return _preflight_inputs(state.manifest, state.evidence_pairs, state.terminal_delete)


def _preflight_inputs(
    manifest: _ManifestSnapshot,
    pairs: tuple[FullPolicyEvidencePair, ...],
    terminal: FullPolicyTerminalDeleteEvidence,
) -> _PreflightSnapshot:
    canonical_reports: list[dict[str, object]] = []
    source_reports: list[dict[str, object]] = []
    policy_commitments: list[str] = []
    seen_proofs: set[int] = set()
    for index, (item, pair) in enumerate(zip(manifest.items, pairs, strict=True)):
        pair.__post_init__()
        proof_ids = (id(pair.canonical), id(pair.source))
        if any(identity in seen_proofs for identity in proof_ids):
            raise FullPolicyComponentValidationError("policy proof is duplicated")
        seen_proofs.update(proof_ids)
        canonical = public_canonical_evidence_report(
            pair.canonical,
            trust_policy=pair.trust_policy,
        )
        source = public_source_evidence_report(
            pair.source,
            trust_policy=pair.trust_policy,
        )
        policy_commitment = _validate_pair(
            manifest,
            item,
            canonical,
            source,
            index=index,
        )
        if policy_commitment in policy_commitments:
            raise FullPolicyComponentValidationError("item trust policy is reused")
        policy_commitments.append(policy_commitment)
        canonical_reports.append(canonical)
        source_reports.append(source)

    terminal.__post_init__()
    delete_report = terminal_delete_evidence_report(
        terminal.evidence,
        policy=terminal.trust_policy,
    )
    delete_policy_commitment = _validate_delete(manifest, delete_report)
    return _PreflightSnapshot(
        tuple(canonical_reports),
        tuple(source_reports),
        delete_report,
        tuple(policy_commitments),
        delete_policy_commitment,
    )


def _validate_pair(
    manifest: _ManifestSnapshot,
    item: _ItemSnapshot,
    canonical: dict[str, object],
    source: dict[str, object],
    *,
    index: int,
) -> str:
    names = ("run_id", "profile_id", "scope_id", "case_id", "source_ref")
    expected = (
        manifest.run_id,
        manifest.profile_id,
        manifest.scope_id,
        item.case_id,
        item.source_ref,
    )
    if tuple(canonical.get(name) for name in names) != expected:
        raise FullPolicyComponentValidationError(f"manifest item {index} canonical differs")
    if tuple(source.get(name) for name in names) != expected:
        raise FullPolicyComponentValidationError(f"manifest item {index} source differs")
    if canonical.get("backend_id") != manifest.infinity_backend_id:
        raise FullPolicyComponentValidationError("canonical backend differs from manifest")
    if (
        source.get("infinity_backend_id") != manifest.infinity_backend_id
        or source.get("mem0_backend_id") != manifest.mem0_backend_id
        or source.get("source_revision") != item.source_revision
        or source.get("source_sha256") != item.source_sha256
    ):
        raise FullPolicyComponentValidationError("source binding differs from manifest")
    _require_component_only(canonical, name="canonical")
    _require_component_only(source, name="source")
    canonical_policy = _exact_dict(canonical.get("trust_policy"), "canonical trust policy")
    source_policy = _exact_dict(source.get("trust_policy"), "source trust policy")
    if canonical_policy != source_policy:
        raise FullPolicyComponentValidationError("canonical and source policy commitments differ")
    policy_commitment = _digest(canonical_policy.get("policy_commitment"), "policy commitment")
    if (
        canonical_policy.get("runtime_attestation_commitment")
        != manifest.managed_attestation_commitment_sha256
    ):
        raise FullPolicyComponentValidationError("managed attestation commitment differs")
    return policy_commitment


def _validate_delete(manifest: _ManifestSnapshot, report: dict[str, object]) -> str:
    names = (
        "run_id",
        "profile_id",
        "infinity_backend_id",
        "mem0_backend_id",
        "scope_id",
        "source_id",
    )
    expected = (
        manifest.run_id,
        manifest.profile_id,
        manifest.infinity_backend_id,
        manifest.mem0_backend_id,
        manifest.scope_id,
        manifest.delete_source_id,
    )
    if tuple(report.get(name) for name in names) != expected:
        raise FullPolicyComponentValidationError("terminal delete binding differs from manifest")
    _require_component_only(report, name="delete", evidence_role=True)
    policy = _exact_dict(report.get("verification_policy"), "delete verification policy")
    if (
        policy.get("external_attestation_commitment")
        != manifest.managed_attestation_commitment_sha256
    ):
        raise FullPolicyComponentValidationError("delete managed attestation differs")
    return _digest(policy.get("commitment"), "delete policy commitment")


def _consume_components(state: _SessionState) -> None:
    for item, pair in zip(state.manifest.items, state.evidence_pairs, strict=True):
        position = f"canonical:{item.case_id}:{item.source_ref}"
        _start_component_consume(state, position)
        consume_canonical_evidence(
            pair.canonical,
            trust_policy=pair.trust_policy,
            run_id=state.manifest.run_id,
            profile_id=state.manifest.profile_id,
            backend_id=state.manifest.infinity_backend_id,
            scope_id=state.manifest.scope_id,
            case_id=item.case_id,
            source_ref=item.source_ref,
        )
        _complete_component_consume(state, position)
        position = f"source:{item.case_id}:{item.source_ref}"
        _start_component_consume(state, position)
        consume_source_evidence(
            pair.source,
            trust_policy=pair.trust_policy,
            run_id=state.manifest.run_id,
            profile_id=state.manifest.profile_id,
            scope_id=state.manifest.scope_id,
            case_id=item.case_id,
            source_ref=item.source_ref,
            source_revision=item.source_revision,
            source_sha256=item.source_sha256,
            infinity_backend_id=state.manifest.infinity_backend_id,
            mem0_backend_id=state.manifest.mem0_backend_id,
        )
        _complete_component_consume(state, position)
    position = "delete"
    _start_component_consume(state, position)
    consume_terminal_delete_evidence(
        state.terminal_delete.evidence,
        state.terminal_delete.session,
        policy=state.terminal_delete.trust_policy,
        consumer_id=state.consumer_id,
        run_id=state.manifest.run_id,
        profile_id=state.manifest.profile_id,
        infinity_backend_id=state.manifest.infinity_backend_id,
        mem0_backend_id=state.manifest.mem0_backend_id,
        scope_id=state.manifest.scope_id,
        source_id=state.manifest.delete_source_id,
    )
    _complete_component_consume(state, position)


def _start_component_consume(state: _SessionState, position: str) -> None:
    with _LOCK:
        if (
            state.phase != "consuming"
            or state.active_owner != threading.get_ident()
            or state.active_position is not None
        ):
            raise FullPolicyComponentValidationError("component consumption lifecycle changed")
        state.started_count += 1
        state.active_position = position


def _complete_component_consume(state: _SessionState, position: str) -> None:
    with _LOCK:
        if (
            state.phase != "consuming"
            or state.active_owner != threading.get_ident()
            or state.active_position != position
        ):
            raise FullPolicyComponentValidationError("component consumption lifecycle changed")
        state.completed_count += 1
        state.active_position = None


def _aggregate_report(
    state: _SessionState,
    preflight: _PreflightSnapshot,
) -> dict[str, object]:
    manifest = state.manifest
    return {
        "schema_version": FULL_POLICY_COMPONENT_VALIDATION_SCHEMA_VERSION,
        "status": "verified",
        "run_id": manifest.run_id,
        "profile_id": manifest.profile_id,
        "infinity_backend_id": manifest.infinity_backend_id,
        "mem0_backend_id": manifest.mem0_backend_id,
        "scope_id": manifest.scope_id,
        "delete_source_id": manifest.delete_source_id,
        "managed_attestation_commitment_sha256": (manifest.managed_attestation_commitment_sha256),
        "manifest_commitment_sha256": manifest.commitment_sha256,
        "manifest_item_count": len(manifest.items),
        "coverage": {
            "canonical": len(preflight.canonical_reports),
            "source": len(preflight.source_reports),
            "delete": 1,
        },
        "item_policy_commitments": list(preflight.item_policy_commitments),
        "delete_policy_commitment": preflight.delete_policy_commitment,
        "delete_consumed_last": True,
        "all_components_consumed": True,
        "admission_from_public_json": False,
    }


def _input_commitments(preflight: _PreflightSnapshot) -> tuple[str, ...]:
    reports = (
        *preflight.canonical_reports,
        *preflight.source_reports,
        preflight.delete_report,
    )
    return tuple(_json_sha256(report) for report in reports)


def _manifest_snapshot(manifest: FullPolicyRunManifest) -> _ManifestSnapshot:
    if type(manifest) is not FullPolicyRunManifest:
        raise FullPolicyComponentValidationError("manifest type must be exact")
    fields = (
        _text(manifest.run_id, "run_id"),
        _text(manifest.profile_id, "profile_id"),
        _text(manifest.infinity_backend_id, "infinity_backend_id"),
        _text(manifest.mem0_backend_id, "mem0_backend_id"),
        _text(manifest.scope_id, "scope_id"),
        _text(manifest.delete_source_id, "delete_source_id"),
        _digest(
            manifest.managed_attestation_commitment_sha256,
            "managed_attestation_commitment_sha256",
        ),
    )
    if fields[2] != INFINITY_CANONICAL_BACKEND_ID or fields[2] != INFINITY_SOURCE_BACKEND_ID:
        raise FullPolicyComponentValidationError("Infinity backend identity is unsupported")
    if fields[3] != MEM0_SOURCE_BACKEND_ID:
        raise FullPolicyComponentValidationError("Mem0 backend identity is unsupported")
    if type(manifest.items) is not tuple or not manifest.items:
        raise FullPolicyComponentValidationError("manifest items must be a nonempty exact tuple")
    items = tuple(_manifest_item_snapshot(item) for item in manifest.items)
    keys = tuple((item.case_id, item.source_ref) for item in items)
    if len(set(keys)) != len(keys):
        raise FullPolicyComponentValidationError("manifest item identity is duplicated")
    payload = {
        "run_id": fields[0],
        "profile_id": fields[1],
        "infinity_backend_id": fields[2],
        "mem0_backend_id": fields[3],
        "scope_id": fields[4],
        "delete_source_id": fields[5],
        "managed_attestation_commitment_sha256": fields[6],
        "items": [_item_payload(item) for item in items],
    }
    return _ManifestSnapshot(*fields, items, _json_sha256(payload))


def _manifest_item_snapshot(item: FullPolicyManifestItem) -> _ItemSnapshot:
    if type(item) is not FullPolicyManifestItem:
        raise FullPolicyComponentValidationError("manifest item type must be exact")
    return _ItemSnapshot(
        _text(item.case_id, "case_id"),
        _text(item.source_ref, "source_ref"),
        _positive_int(item.source_revision, "source_revision"),
        _digest(item.source_sha256, "source_sha256"),
    )


def _item_payload(item: _ItemSnapshot) -> dict[str, object]:
    return {
        "case_id": item.case_id,
        "source_ref": item.source_ref,
        "source_revision": item.source_revision,
        "source_sha256": item.source_sha256,
    }


def _require_component_only(
    report: dict[str, object],
    *,
    name: str,
    evidence_role: bool = False,
) -> None:
    component_marker = (
        report.get("evidence_role") == "component_only"
        if evidence_role
        else report.get("component_only") is True
    )
    if (
        not component_marker
        or report.get("externally_authentic") is not False
        or report.get("composite_policy_consume_required") is not True
    ):
        raise FullPolicyComponentValidationError(f"{name} is not component-only evidence")


def _session_state(session: FullPolicyComponentValidationSession) -> _SessionState:
    if type(session) is not FullPolicyComponentValidationSession:
        raise FullPolicyComponentValidationError("validation session type must be exact")
    with _LOCK:
        state = _SESSIONS.get(session)
    if state is None:
        raise FullPolicyComponentValidationError("validation session is unregistered")
    return state


def _validation_state(validation: VerifiedFullPolicyComponentValidation) -> _ValidationState:
    if type(validation) is not VerifiedFullPolicyComponentValidation:
        raise FullPolicyComponentValidationError("validation type must be exact")
    with _LOCK:
        state = _VALIDATIONS.get(validation)
    if state is None:
        raise FullPolicyComponentValidationError("validation is unregistered")
    session = _session_state(state.session)
    try:
        current = validation._VerifiedFullPolicyComponentValidation__commitment
    except Exception:
        raise FullPolicyComponentValidationError("policy validation integrity failed") from None
    if (
        session.phase != "sealed"
        or session.validation is not validation
        or type(current) is not str
        or not hmac.compare_digest(current, state.commitment)
    ):
        raise FullPolicyComponentValidationError("policy validation integrity failed")
    return state


def _exact_dict(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise FullPolicyComponentValidationError(f"{name} must be an exact object")
    return value


def _text(value: object, name: str, *, maximum: int = _MAX_TEXT) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise FullPolicyComponentValidationError(f"{name} must be a bounded nonblank string")
    return value


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise FullPolicyComponentValidationError(f"{name} must be a positive exact integer")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise FullPolicyComponentValidationError(f"{name} must be lowercase sha256")
    return value


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _commitment(secret: bytes, report: dict[str, object]) -> str:
    return hmac.new(secret, _canonical_json(report), hashlib.sha256).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _thaw(value: object) -> object:
    if type(value) is MappingProxyType:
        return {str(key): _thaw(item) for key, item in value.items()}
    if type(value) is dict:
        return {str(key): _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    if type(value) is list:
        return [_thaw(item) for item in value]
    return value


__all__ = (
    "FULL_POLICY_COMPONENT_VALIDATION_SCHEMA_VERSION",
    "FullPolicyComponentValidationError",
    "FullPolicyComponentValidationSession",
    "FullPolicyEvidencePair",
    "FullPolicyManifestItem",
    "FullPolicyRunManifest",
    "FullPolicyTerminalDeleteEvidence",
    "VerifiedFullPolicyComponentValidation",
    "create_full_policy_component_validation_session",
    "full_policy_component_validation_session_status",
    "full_policy_run_manifest_commitment",
    "public_full_policy_component_validation",
    "seal_full_policy_component_validation",
)
