"""Opaque aggregate validation for exact managed HTTP policy evidence."""

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

MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION = (
    "memory-comparison-managed-http-policy-validation.v3"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BACKEND_ROLES = ("infinity-context", "mem0")
_DERIVED_LANES = ("qdrant", "graphiti")
_CLEANUP_ORDER = (
    ("infinity-context", 1),
    ("mem0", 1),
    ("infinity-context", 2),
    ("mem0", 2),
)
_TOKEN = object()
_LOCK = threading.RLock()


class ManagedHttpPolicyValidationError(ValueError):
    """Stable fail-closed error for malformed, forged, or replayed evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyCorpusMaterial:
    """Exact source and derived-presence evidence for one unique corpus."""

    corpus_id: str
    ingest_manifest_sha256: str
    source_pairs: tuple[tuple[str, str], ...]
    presence_commitment_sha256: str
    derived_commitments: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _corpus_snapshot(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyCorpusMaterial is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyCleanupPassMaterial:
    """One backend cleanup pass with exact per-corpus absence evidence."""

    backend_role: str
    target_identity_sha256: str
    pass_index: int
    cleanup_commitment_sha256: str
    exact_absence_commitment_sha256: str
    replay_of_cleanup_commitment_sha256: str | None
    corpus_absence_commitments: tuple[tuple[str, str], ...]
    verified_absent: bool

    def __post_init__(self) -> None:
        _cleanup_snapshot(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyCleanupPassMaterial is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyRegistryMaterial:
    """Exact canonical registry completion evidence bound by the wrapper."""

    registration_commitment_sha256: str
    projection_manifest_sha256: str
    cleanup_initiation_receipt_sha256: str
    completion_receipt_sha256: str
    projection_absence_proof_sha256: str
    wrapper_adapter_id: str
    wrapper_implementation_sha256: str

    def __post_init__(self) -> None:
        _registry_snapshot(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyRegistryMaterial is final")


@final
@dataclass(frozen=True, slots=True)
class ManagedHttpPolicyValidationMaterial:
    """Complete provider-neutral material required to mint policy authority."""

    run_id: str
    profile_id: str
    scope_id: str
    binding_commitment_sha256: str
    managed_attestation_commitment_sha256: str
    backend_targets: tuple[tuple[str, str], ...]
    adapter_id: str
    implementation_sha256: str
    execution_case_manifest_sha256: str
    case_corpus_mapping: tuple[tuple[str, str], ...]
    corpora: tuple[ManagedHttpPolicyCorpusMaterial, ...]
    cleanup_passes: tuple[ManagedHttpPolicyCleanupPassMaterial, ...]
    registry: ManagedHttpPolicyRegistryMaterial | None = None

    def __post_init__(self) -> None:
        _material_snapshot(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedHttpPolicyValidationMaterial is final")


class _Opaque:
    __slots__ = ()

    def __copy__(self) -> object:
        raise TypeError("managed policy validations are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed policy validations are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed policy validations are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed policy validations are nonserializable")


@final
class VerifiedManagedHttpPolicyValidation(_Opaque):
    """Opaque live authority over one fully bound exact policy proof."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise ManagedHttpPolicyValidationError("managed_policy_validation_forged")
        self.__commitment = commitment

    def __repr__(self) -> str:
        return "VerifiedManagedHttpPolicyValidation(<sealed>)"

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("VerifiedManagedHttpPolicyValidation is final")


@dataclass(frozen=True, slots=True)
class _CorpusSnapshot:
    corpus_id: str
    ingest_manifest_sha256: str
    source_pairs: tuple[tuple[str, str], ...]
    presence_commitment_sha256: str
    derived_commitments: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _CleanupSnapshot:
    backend_role: str
    target_identity_sha256: str
    pass_index: int
    cleanup_commitment_sha256: str
    exact_absence_commitment_sha256: str
    replay_of_cleanup_commitment_sha256: str | None
    corpus_absence_commitments: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _RegistrySnapshot:
    registration_commitment_sha256: str
    projection_manifest_sha256: str
    cleanup_initiation_receipt_sha256: str
    completion_receipt_sha256: str
    projection_absence_proof_sha256: str
    wrapper_adapter_id: str
    wrapper_implementation_sha256: str


@dataclass(frozen=True, slots=True)
class _MaterialSnapshot:
    run_id: str
    profile_id: str
    scope_id: str
    binding_commitment_sha256: str
    managed_attestation_commitment_sha256: str
    backend_targets: tuple[tuple[str, str], ...]
    adapter_id: str
    implementation_sha256: str
    execution_case_manifest_sha256: str
    case_corpus_mapping: tuple[tuple[str, str], ...]
    corpora: tuple[_CorpusSnapshot, ...]
    cleanup_passes: tuple[_CleanupSnapshot, ...]
    registry: _RegistrySnapshot | None


@dataclass(slots=True)
class _ValidationState:
    material: _MaterialSnapshot
    secret: bytes
    commitment: str
    report: MappingProxyType[str, object]
    phase: str = "live"


_VALIDATIONS: weakref.WeakKeyDictionary[VerifiedManagedHttpPolicyValidation, _ValidationState] = (
    weakref.WeakKeyDictionary()
)


def seal_managed_http_policy_validation(
    *, material: ManagedHttpPolicyValidationMaterial
) -> VerifiedManagedHttpPolicyValidation:
    """Validate complete material and mint one HMAC-backed live authority."""

    snapshot = _material_snapshot(material)
    secret = secrets.token_bytes(32)
    commitment = _commitment(secret, snapshot)
    validation = VerifiedManagedHttpPolicyValidation(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _VALIDATIONS[validation] = _ValidationState(
            snapshot,
            secret,
            commitment,
            MappingProxyType(_report(snapshot, commitment)),
        )
    return validation


def public_managed_http_policy_validation(
    validation: VerifiedManagedHttpPolicyValidation,
) -> dict[str, object]:
    """Return sanitized JSON-safe telemetry after live integrity revalidation."""

    with _LOCK:
        state = _validation_state(validation)
        _verify_integrity(validation, state)
        return _thaw(state.report)


def consume_managed_http_policy_validation(
    validation: VerifiedManagedHttpPolicyValidation,
    *,
    binding_commitment_sha256: str,
    managed_attestation_commitment_sha256: str,
) -> dict[str, object]:
    """Consume once for one exact binding and attestation commitment."""

    binding = _digest(binding_commitment_sha256, "managed_policy_binding_invalid")
    attestation = _digest(
        managed_attestation_commitment_sha256,
        "managed_policy_attestation_invalid",
    )
    with _LOCK:
        state = _validation_state(validation)
        if state.phase == "consuming":
            raise ManagedHttpPolicyValidationError("managed_policy_validation_consume_active")
        if state.phase == "consumed":
            raise ManagedHttpPolicyValidationError("managed_policy_validation_replay")
        if state.phase != "live":
            raise ManagedHttpPolicyValidationError("managed_policy_validation_state_invalid")
        state.phase = "consuming"
    try:
        _verify_integrity(validation, state)
        if not hmac.compare_digest(state.material.binding_commitment_sha256, binding):
            raise ManagedHttpPolicyValidationError("managed_policy_validation_binding_mismatch")
        if not hmac.compare_digest(
            state.material.managed_attestation_commitment_sha256,
            attestation,
        ):
            raise ManagedHttpPolicyValidationError("managed_policy_validation_attestation_mismatch")
        with _LOCK:
            if state.phase != "consuming":
                raise ManagedHttpPolicyValidationError("managed_policy_validation_state_invalid")
            report = _thaw(state.report)
            state.phase = "consumed"
            return report
    except BaseException:
        with _LOCK:
            if state.phase == "consuming":
                state.phase = "live"
        raise


def managed_http_policy_validation_material_sha256(
    material: ManagedHttpPolicyValidationMaterial,
) -> str:
    """Return a deterministic commitment of complete non-secret material."""

    return _json_sha256(_material_payload(_material_snapshot(material)))


def managed_http_policy_registry_material_sha256(
    material: ManagedHttpPolicyRegistryMaterial,
) -> str:
    """Return a deterministic integrity commitment for copied registry evidence."""

    snapshot = _registry_snapshot(material)
    return _json_sha256(
        (
            snapshot.registration_commitment_sha256,
            snapshot.projection_manifest_sha256,
            snapshot.cleanup_initiation_receipt_sha256,
            snapshot.completion_receipt_sha256,
            snapshot.projection_absence_proof_sha256,
            snapshot.wrapper_adapter_id,
            snapshot.wrapper_implementation_sha256,
        )
    )


def _material_snapshot(value: object) -> _MaterialSnapshot:
    if type(value) is not ManagedHttpPolicyValidationMaterial:
        raise ManagedHttpPolicyValidationError("managed_policy_material_type_invalid")
    targets = _pairs(value.backend_targets, digest_second=True)
    if tuple(role for role, _ in targets) != _BACKEND_ROLES:
        raise ManagedHttpPolicyValidationError("managed_policy_target_order_invalid")
    try:
        mapping = _pairs(value.case_corpus_mapping)
    except ManagedHttpPolicyValidationError as exc:
        if exc.code == "managed_policy_pairs_duplicate":
            raise ManagedHttpPolicyValidationError("managed_policy_case_mapping_invalid") from None
        raise
    if not mapping or len({case_id for case_id, _ in mapping}) != len(mapping):
        raise ManagedHttpPolicyValidationError("managed_policy_case_mapping_invalid")
    corpora = _exact_tuple(
        value.corpora,
        ManagedHttpPolicyCorpusMaterial,
        "managed_policy_corpora_invalid",
    )
    corpus_snapshots = tuple(_corpus_snapshot(item) for item in corpora)
    corpus_ids = tuple(item.corpus_id for item in corpus_snapshots)
    first_seen = tuple(dict.fromkeys(corpus_id for _, corpus_id in mapping))
    if not corpus_ids or corpus_ids != first_seen or len(set(corpus_ids)) != len(corpus_ids):
        raise ManagedHttpPolicyValidationError("managed_policy_corpus_order_invalid")
    all_source_ids = tuple(
        source_id for corpus in corpus_snapshots for source_id, _ in corpus.source_pairs
    )
    if len(set(all_source_ids)) != len(all_source_ids):
        raise ManagedHttpPolicyValidationError("managed_policy_source_alias_invalid")
    cleanup = _exact_tuple(
        value.cleanup_passes,
        ManagedHttpPolicyCleanupPassMaterial,
        "managed_policy_cleanup_invalid",
    )
    cleanup_snapshots = tuple(_cleanup_snapshot(item) for item in cleanup)
    _validate_cleanup(cleanup_snapshots, targets, corpus_ids)
    registry = None if value.registry is None else _registry_snapshot(value.registry)
    adapter_id = _text(value.adapter_id, "managed_policy_adapter_id_invalid")
    implementation = _digest(
        value.implementation_sha256,
        "managed_policy_implementation_invalid",
    )
    if registry is not None and (
        registry.wrapper_adapter_id != adapter_id
        or registry.wrapper_implementation_sha256 != implementation
    ):
        raise ManagedHttpPolicyValidationError("managed_policy_registry_adapter_binding_invalid")
    return _MaterialSnapshot(
        _text(value.run_id, "managed_policy_run_id_invalid"),
        _text(value.profile_id, "managed_policy_profile_id_invalid"),
        _text(value.scope_id, "managed_policy_scope_id_invalid"),
        _digest(value.binding_commitment_sha256, "managed_policy_binding_invalid"),
        _digest(
            value.managed_attestation_commitment_sha256,
            "managed_policy_attestation_invalid",
        ),
        targets,
        adapter_id,
        implementation,
        _digest(
            value.execution_case_manifest_sha256,
            "managed_policy_case_manifest_invalid",
        ),
        mapping,
        corpus_snapshots,
        cleanup_snapshots,
        registry,
    )


def _corpus_snapshot(value: object) -> _CorpusSnapshot:
    if type(value) is not ManagedHttpPolicyCorpusMaterial:
        raise ManagedHttpPolicyValidationError("managed_policy_corpus_type_invalid")
    sources = _pairs(value.source_pairs, digest_second=True)
    if not sources or len({source_id for source_id, _ in sources}) != len(sources):
        raise ManagedHttpPolicyValidationError("managed_policy_source_pairs_invalid")
    derived = _pairs(value.derived_commitments, digest_second=True)
    lanes = tuple(lane for lane, _ in derived)
    if not lanes or lanes != tuple(lane for lane in _DERIVED_LANES if lane in lanes):
        raise ManagedHttpPolicyValidationError("managed_policy_derived_order_invalid")
    return _CorpusSnapshot(
        _text(value.corpus_id, "managed_policy_corpus_id_invalid"),
        _digest(value.ingest_manifest_sha256, "managed_policy_ingest_manifest_invalid"),
        sources,
        _digest(value.presence_commitment_sha256, "managed_policy_presence_invalid"),
        derived,
    )


def _cleanup_snapshot(value: object) -> _CleanupSnapshot:
    if type(value) is not ManagedHttpPolicyCleanupPassMaterial:
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_type_invalid")
    if type(value.pass_index) is not int or value.pass_index not in (1, 2):
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_pass_invalid")
    if value.verified_absent is not True:
        raise ManagedHttpPolicyValidationError("managed_policy_exact_absence_unverified")
    replay = value.replay_of_cleanup_commitment_sha256
    if replay is not None:
        replay = _digest(replay, "managed_policy_cleanup_replay_invalid")
    return _CleanupSnapshot(
        _text(value.backend_role, "managed_policy_cleanup_backend_invalid"),
        _digest(value.target_identity_sha256, "managed_policy_cleanup_target_invalid"),
        value.pass_index,
        _digest(value.cleanup_commitment_sha256, "managed_policy_cleanup_commitment_invalid"),
        _digest(value.exact_absence_commitment_sha256, "managed_policy_exact_absence_invalid"),
        replay,
        _pairs(value.corpus_absence_commitments, digest_second=True),
    )


def _registry_snapshot(value: object) -> _RegistrySnapshot:
    if type(value) is not ManagedHttpPolicyRegistryMaterial:
        raise ManagedHttpPolicyValidationError("managed_policy_registry_type_invalid")
    return _RegistrySnapshot(
        _digest(
            value.registration_commitment_sha256,
            "managed_policy_registry_registration_invalid",
        ),
        _digest(
            value.projection_manifest_sha256,
            "managed_policy_registry_projection_invalid",
        ),
        _digest(
            value.cleanup_initiation_receipt_sha256,
            "managed_policy_registry_cleanup_invalid",
        ),
        _digest(
            value.completion_receipt_sha256,
            "managed_policy_registry_completion_invalid",
        ),
        _digest(
            value.projection_absence_proof_sha256,
            "managed_policy_registry_absence_invalid",
        ),
        _text(value.wrapper_adapter_id, "managed_policy_registry_adapter_invalid"),
        _digest(
            value.wrapper_implementation_sha256,
            "managed_policy_registry_implementation_invalid",
        ),
    )


def _validate_cleanup(
    passes: tuple[_CleanupSnapshot, ...],
    targets: tuple[tuple[str, str], ...],
    corpus_ids: tuple[str, ...],
) -> None:
    if tuple((item.backend_role, item.pass_index) for item in passes) != _CLEANUP_ORDER:
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_order_invalid")
    target_map = dict(targets)
    if any(item.target_identity_sha256 != target_map[item.backend_role] for item in passes):
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_target_mismatch")
    if any(
        tuple(corpus_id for corpus_id, _ in item.corpus_absence_commitments) != corpus_ids
        for item in passes
    ):
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_corpus_coverage_invalid")
    if any(item.replay_of_cleanup_commitment_sha256 is not None for item in passes[:2]):
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_replay_invalid")
    if passes[2].replay_of_cleanup_commitment_sha256 != passes[0].cleanup_commitment_sha256 or (
        passes[3].replay_of_cleanup_commitment_sha256 != passes[1].cleanup_commitment_sha256
    ):
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_replay_invalid")
    if len({item.cleanup_commitment_sha256 for item in passes}) != 4:
        raise ManagedHttpPolicyValidationError("managed_policy_cleanup_duplicate_invalid")


def _validation_state(value: object) -> _ValidationState:
    if type(value) is not VerifiedManagedHttpPolicyValidation:
        raise ManagedHttpPolicyValidationError("managed_policy_validation_type_invalid")
    state = _VALIDATIONS.get(value)
    if state is None:
        raise ManagedHttpPolicyValidationError("managed_policy_validation_unknown")
    return state


def _verify_integrity(
    validation: VerifiedManagedHttpPolicyValidation,
    state: _ValidationState,
) -> None:
    current = validation._VerifiedManagedHttpPolicyValidation__commitment
    if (
        type(current) is not str
        or not hmac.compare_digest(current, state.commitment)
        or not hmac.compare_digest(_commitment(state.secret, state.material), state.commitment)
        or state.report.get("validation_commitment_sha256") != state.commitment
    ):
        raise ManagedHttpPolicyValidationError("managed_policy_validation_integrity_failed")


def _report(snapshot: _MaterialSnapshot, commitment: str) -> dict[str, object]:
    payload = _material_payload(snapshot)
    registry = snapshot.registry
    return {
        "schema_version": MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION,
        "run_id": snapshot.run_id,
        "profile_id": snapshot.profile_id,
        "scope_id": snapshot.scope_id,
        "binding_commitment_sha256": snapshot.binding_commitment_sha256,
        "managed_attestation_commitment_sha256": snapshot.managed_attestation_commitment_sha256,
        "adapter_id": snapshot.adapter_id,
        "implementation_sha256": snapshot.implementation_sha256,
        "execution_case_manifest_sha256": snapshot.execution_case_manifest_sha256,
        "backend_targets": [
            {"backend_role": role, "target_identity_sha256": target}
            for role, target in snapshot.backend_targets
        ],
        "case_count": len(snapshot.case_corpus_mapping),
        "unique_corpus_count": len(snapshot.corpora),
        "source_pair_count": sum(len(item.source_pairs) for item in snapshot.corpora),
        "derived_commitment_count": sum(len(item.derived_commitments) for item in snapshot.corpora),
        "cleanup_pass_count": len(snapshot.cleanup_passes),
        "case_corpus_mapping_sha256": _json_sha256(payload["case_corpus_mapping"]),
        "corpus_evidence_commitment_sha256": _json_sha256(payload["corpora"]),
        "cleanup_commitment_sha256": _json_sha256(payload["cleanup_passes"]),
        "registry_evidence": (
            None
            if registry is None
            else {
                "registration_commitment_sha256": (registry.registration_commitment_sha256),
                "projection_manifest_sha256": registry.projection_manifest_sha256,
                "cleanup_initiation_receipt_sha256": (registry.cleanup_initiation_receipt_sha256),
                "completion_receipt_sha256": registry.completion_receipt_sha256,
                "projection_absence_proof_sha256": (registry.projection_absence_proof_sha256),
                "wrapper_adapter_id": registry.wrapper_adapter_id,
                "wrapper_implementation_sha256": (registry.wrapper_implementation_sha256),
            }
        ),
        "material_commitment_sha256": _json_sha256(payload),
        "validation_commitment_sha256": commitment,
    }


def _material_payload(snapshot: _MaterialSnapshot) -> dict[str, object]:
    return {
        "schema_version": MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION,
        "run_id": snapshot.run_id,
        "profile_id": snapshot.profile_id,
        "scope_id": snapshot.scope_id,
        "binding_commitment_sha256": snapshot.binding_commitment_sha256,
        "managed_attestation_commitment_sha256": snapshot.managed_attestation_commitment_sha256,
        "backend_targets": snapshot.backend_targets,
        "adapter_id": snapshot.adapter_id,
        "implementation_sha256": snapshot.implementation_sha256,
        "execution_case_manifest_sha256": snapshot.execution_case_manifest_sha256,
        "case_corpus_mapping": snapshot.case_corpus_mapping,
        "corpora": tuple(
            (
                item.corpus_id,
                item.ingest_manifest_sha256,
                item.source_pairs,
                item.presence_commitment_sha256,
                item.derived_commitments,
            )
            for item in snapshot.corpora
        ),
        "cleanup_passes": tuple(
            (
                item.backend_role,
                item.target_identity_sha256,
                item.pass_index,
                item.cleanup_commitment_sha256,
                item.exact_absence_commitment_sha256,
                item.replay_of_cleanup_commitment_sha256,
                item.corpus_absence_commitments,
            )
            for item in snapshot.cleanup_passes
        ),
        "registry": (
            None
            if snapshot.registry is None
            else (
                snapshot.registry.registration_commitment_sha256,
                snapshot.registry.projection_manifest_sha256,
                snapshot.registry.cleanup_initiation_receipt_sha256,
                snapshot.registry.completion_receipt_sha256,
                snapshot.registry.projection_absence_proof_sha256,
                snapshot.registry.wrapper_adapter_id,
                snapshot.registry.wrapper_implementation_sha256,
            )
        ),
    }


def _pairs(value: object, *, digest_second: bool = False) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        raise ManagedHttpPolicyValidationError("managed_policy_pairs_invalid")
    checked: list[tuple[str, str]] = []
    for item in value:
        if type(item) is not tuple or len(item) != 2:
            raise ManagedHttpPolicyValidationError("managed_policy_pairs_invalid")
        first = _text(item[0], "managed_policy_pair_identity_invalid")
        second = (
            _digest(item[1], "managed_policy_pair_commitment_invalid")
            if digest_second
            else _text(item[1], "managed_policy_pair_identity_invalid")
        )
        checked.append((first, second))
    result = tuple(checked)
    if len(set(result)) != len(result):
        raise ManagedHttpPolicyValidationError("managed_policy_pairs_duplicate")
    return result


def _exact_tuple(value: object, item_type: type, code: str) -> tuple:
    if type(value) is not tuple or any(type(item) is not item_type for item in value):
        raise ManagedHttpPolicyValidationError(code)
    return value


def _text(value: object, code: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 512
        or value.strip() != value
        or any(ord(character) < 32 for character in value)
    ):
        raise ManagedHttpPolicyValidationError(code)
    return value


def _digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedHttpPolicyValidationError(code)
    return value


def _commitment(secret: bytes, snapshot: _MaterialSnapshot) -> str:
    encoded = json.dumps(
        _material_payload(snapshot), sort_keys=True, separators=(",", ":")
    ).encode()
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _thaw(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, list):
        return [_thaw(item) for item in value]
    return value


__all__ = (
    "MANAGED_HTTP_POLICY_VALIDATION_SCHEMA_VERSION",
    "ManagedHttpPolicyCleanupPassMaterial",
    "ManagedHttpPolicyCorpusMaterial",
    "ManagedHttpPolicyRegistryMaterial",
    "ManagedHttpPolicyValidationError",
    "ManagedHttpPolicyValidationMaterial",
    "VerifiedManagedHttpPolicyValidation",
    "consume_managed_http_policy_validation",
    "managed_http_policy_registry_material_sha256",
    "managed_http_policy_validation_material_sha256",
    "public_managed_http_policy_validation",
    "seal_managed_http_policy_validation",
)
