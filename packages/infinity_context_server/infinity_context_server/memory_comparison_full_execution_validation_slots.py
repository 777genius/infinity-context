"""Typed complete-run slot validation for full comparison evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import final

from infinity_context_server import memory_comparison_full_run_evidence as _run_evidence
from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
    verify_clean_state_contract_for_publication,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_locomo_transport import (
    LocomoTimestampTransportEvidence,
    RunScopedLocomoTransportEvidenceKey,
    locomo_timestamp_transport_contract,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
    SessionIdentityMapping,
    session_identity_contract,
    session_identity_contract_is_verified,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

FULL_EXECUTION_VALIDATION_SCHEMA_VERSION = "memory-comparison-full-execution-validation.v1"
_PROVIDER_STAGES = ("answerer", "judge")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CREDENTIAL = re.compile(r"^sha256:[0-9a-f]{64}$")


class FullExecutionValidationError(BenchmarkValidationError):
    """Raised when complete-run coverage cannot be proven."""


@final
@dataclass(frozen=True, slots=True)
class FullExecutionCaseManifestEntry:
    case_id: str
    corpus_id: str
    thread_id: str
    session_roles: tuple[str, ...]
    session_aliases: tuple[str, ...]
    official_turn_count: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.case_id, "case_id"),
            (self.corpus_id, "corpus_id"),
            (self.thread_id, "thread_id"),
        ):
            _identifier(value, name)
        if (
            type(self.session_roles) is not tuple
            or not self.session_roles
            or type(self.session_aliases) is not tuple
            or len(self.session_aliases) != len(self.session_roles)
        ):
            raise FullExecutionValidationError("session role mapping must be an exact tuple")
        if any(type(item) is not str or not _ID.fullmatch(item) for item in self.session_roles):
            raise FullExecutionValidationError("session role is invalid")
        if any(
            type(item) is not str or re.fullmatch(r"session-[0-9]{4}", item) is None
            for item in self.session_aliases
        ):
            raise FullExecutionValidationError("session alias is invalid")
        if len(set(self.session_roles)) != len(self.session_roles) or len(
            set(self.session_aliases)
        ) != len(self.session_aliases):
            raise FullExecutionValidationError("session role mapping is duplicated")
        if type(self.official_turn_count) is not int or self.official_turn_count < 0:
            raise FullExecutionValidationError("official turn count must be nonnegative")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("FullExecutionCaseManifestEntry is final")


@final
@dataclass(frozen=True, slots=True)
class FullExecutionProviderCall:
    comparison_commitment_sha256: str
    run_id: str
    profile_id: str
    case_id: str
    backend_role: str
    stage: str
    pending: bool
    provenance: ProviderCallProvenance

    def __post_init__(self) -> None:
        _digest(self.comparison_commitment_sha256, "comparison commitment")
        for value, name in (
            (self.run_id, "run_id"),
            (self.profile_id, "profile_id"),
            (self.case_id, "case_id"),
            (self.backend_role, "backend_role"),
        ):
            _identifier(value, name)
        if type(self.stage) is not str or self.stage not in _PROVIDER_STAGES:
            raise FullExecutionValidationError("provider stage is invalid")
        if type(self.pending) is not bool:
            raise FullExecutionValidationError("provider pending flag must be exact")
        if type(self.provenance) is not ProviderCallProvenance:
            raise FullExecutionValidationError("provider provenance type must be exact")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("FullExecutionProviderCall is final")


@final
@dataclass(frozen=True, slots=True)
class FullExecutionCleanScope:
    backend_role: str
    corpus_identity_sha256: str
    scope_identity_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.backend_role, "clean backend_role")
        _digest(self.corpus_identity_sha256, "clean corpus identity")
        _digest(self.scope_identity_sha256, "clean scope identity")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("FullExecutionCleanScope is final")


def validate_full_execution_slots(
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
) -> dict[str, object]:
    """Re-run every unwired slot from exact live typed inputs."""

    try:
        trusted_bindings = _run_evidence._validate_bindings(bindings)
    except Exception:
        raise FullExecutionValidationError("full comparison binding is invalid") from None
    profile = resolve_full_comparison_profile(trusted_bindings.profile_id)
    if profile is None or profile.benchmark != benchmark:
        raise FullExecutionValidationError("benchmark differs from bound profile")
    manifest = _validated_manifest(case_manifest, benchmark=benchmark)
    route_payload = _validated_route(required_route)
    model = _identifier(required_model, "required_model")
    provider = _provider_coverage(
        trusted_bindings,
        manifest,
        model=model,
        route=required_route,
        route_payload=route_payload,
        calls=provider_calls,
    )
    session = _session_coverage(
        trusted_bindings,
        manifest,
        verifier=session_verifier,
        evidence=session_evidence,
    )
    transport = _transport_coverage(
        trusted_bindings,
        benchmark=benchmark,
        manifest=manifest,
        verifier=transport_verifier,
        evidence=transport_evidence,
    )
    clean = _clean_coverage(
        trusted_bindings,
        manifest,
        validation=clean_validation,
        scopes=clean_scopes,
        attestation_key=clean_attestation_key,
    )
    return {
        "schema_version": FULL_EXECUTION_VALIDATION_SCHEMA_VERSION,
        "comparison_commitment_sha256": trusted_bindings.binding_commitment_sha256,
        "run_id": trusted_bindings.run_id,
        "profile_id": trusted_bindings.profile_id,
        "dataset_sha256": trusted_bindings.dataset_sha256,
        "selection_sha256": trusted_bindings.selection_fingerprint_sha256,
        "scope": trusted_bindings.scope,
        "benchmark": benchmark,
        "ordered_targets": [
            {
                "backend_role": item.backend_role,
                "target_identity_sha256": item.target_identity_sha256,
            }
            for item in trusted_bindings.backend_targets
        ],
        "case_manifest_sha256": execution_case_manifest_sha256(manifest),
        "case_count": len(manifest),
        "provider_call_coverage": provider,
        "session_identity_coverage": session,
        "official_transport_coverage": transport,
        "clean_state_coverage": clean,
        "component_only": True,
        "externally_authentic": False,
        "composite_wiring_required": True,
        "admission_from_public_mapping": False,
    }


def execution_case_manifest_sha256(
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
) -> str:
    trusted = _validated_manifest_shape(manifest)
    payload = [
        {
            "case_id": item.case_id,
            "corpus_id": item.corpus_id,
            "thread_id": item.thread_id,
            "session_roles": list(item.session_roles),
            "session_aliases": list(item.session_aliases),
            "official_turn_count": item.official_turn_count,
        }
        for item in trusted
    ]
    return _json_sha256(payload)


def _validated_manifest(
    value: object,
    *,
    benchmark: str,
) -> tuple[FullExecutionCaseManifestEntry, ...]:
    if type(benchmark) is not str or benchmark not in {"locomo", "longmemeval"}:
        raise FullExecutionValidationError("benchmark is invalid")
    manifest = _validated_manifest_shape(value)
    turn_counts = tuple(item.official_turn_count for item in manifest)
    if benchmark == "locomo" and any(count < 1 for count in turn_counts):
        raise FullExecutionValidationError("LoCoMo official turn coverage is empty")
    if benchmark == "longmemeval" and any(count != 0 for count in turn_counts):
        raise FullExecutionValidationError("LongMemEval cannot claim LoCoMo turns")
    return manifest


def _validated_manifest_shape(
    value: object,
) -> tuple[FullExecutionCaseManifestEntry, ...]:
    if type(value) is not tuple or not value:
        raise FullExecutionValidationError("case manifest must be a nonempty exact tuple")
    if any(type(item) is not FullExecutionCaseManifestEntry for item in value):
        raise FullExecutionValidationError("case manifest type must be exact")
    manifest = value
    for item in manifest:
        item.__post_init__()
    for values, label in (
        ((item.case_id for item in manifest), "case"),
        ((item.corpus_id for item in manifest), "corpus"),
        ((item.thread_id for item in manifest), "thread"),
        ((alias for item in manifest for alias in item.session_aliases), "session alias"),
    ):
        material = tuple(values)
        if len(set(material)) != len(material):
            raise FullExecutionValidationError(f"{label} mapping is duplicated")
    return manifest


def _provider_coverage(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    *,
    model: str,
    route: ProviderRouteAttestation,
    route_payload: dict[str, object],
    calls: tuple[FullExecutionProviderCall, ...],
) -> dict[str, object]:
    if type(calls) is not tuple:
        raise FullExecutionValidationError("provider calls must be an exact tuple")
    required = tuple(
        (case.case_id, target.backend_role, stage)
        for case in manifest
        for target in bindings.backend_targets
        for stage in _PROVIDER_STAGES
    )
    seen: list[tuple[str, str, str]] = []
    response_ids: list[str] = []
    call_commitments: list[dict[str, object]] = []
    for call in calls:
        if type(call) is not FullExecutionProviderCall:
            raise FullExecutionValidationError("provider call type must be exact")
        call.__post_init__()
        if (
            call.comparison_commitment_sha256 != bindings.binding_commitment_sha256
            or call.run_id != bindings.run_id
            or call.profile_id != bindings.profile_id
            or call.pending is not False
        ):
            raise FullExecutionValidationError("provider call binding is invalid or pending")
        key = (call.case_id, call.backend_role, call.stage)
        if key in seen:
            raise FullExecutionValidationError("provider call stage is duplicated")
        seen.append(key)
        provenance = call.provenance
        if type(provenance.route) is not ProviderRouteAttestation:
            raise FullExecutionValidationError("provider route type must be exact")
        if _validated_route(provenance.route) != route_payload:
            raise FullExecutionValidationError("provider route differs from run route")
        for value, name in (
            (provenance.requested_model, "requested model"),
            (provenance.observed_model, "observed model"),
            (provenance.response_id, "response id"),
            (provenance.system_fingerprint, "system fingerprint"),
        ):
            _identifier(value, name)
        if provenance.requested_model != model or provenance.observed_model != model:
            raise FullExecutionValidationError("provider model differs from run model")
        _digest(provenance.request_sha256, "provider request")
        if provenance.response_id in response_ids:
            raise FullExecutionValidationError("provider response id is duplicated")
        response_ids.append(provenance.response_id)
        call_commitments.append(
            {
                "case_id_sha256": hashlib.sha256(call.case_id.encode()).hexdigest(),
                "backend_role": call.backend_role,
                "stage": call.stage,
                "provenance": provenance.public_payload(),
            }
        )
    if tuple(seen) != required:
        raise FullExecutionValidationError("provider stage coverage is missing or reordered")
    return {
        "required_call_count": len(required),
        "verified_call_count": len(seen),
        "coverage_commitment_sha256": _json_sha256(call_commitments),
        "pending_call_count": 0,
        "unique_response_id_count": len(response_ids),
        "required_model": model,
        "route_sha256": route.route_sha256,
        "credential_binding_id": route.credential_binding_id,
        "stages": list(_PROVIDER_STAGES),
    }


def _validated_route(route: object) -> dict[str, object]:
    if type(route) is not ProviderRouteAttestation:
        raise FullExecutionValidationError("provider route type must be exact")
    for value, name in (
        (route.trust, "route trust"),
        (route.origin, "route origin"),
        (route.endpoint_path, "route path"),
        (route.transport_evidence, "route transport"),
        (route.request_method, "route method"),
    ):
        if type(value) is not str or not value or value != value.strip():
            raise FullExecutionValidationError(f"{name} is invalid")
    _digest(route.route_sha256, "provider route")
    if (
        type(route.credential_binding_id) is not str
        or _CREDENTIAL.fullmatch(route.credential_binding_id) is None
        or route.request_method != "POST"
        or type(route.response_status) is not int
        or route.response_status != 200
    ):
        raise FullExecutionValidationError("provider route credential or response is invalid")
    payload = route.public_payload()
    if (
        type(payload) is not dict
        or payload.get("credential_bound") is not True
        or payload.get("credential_binding_id") != route.credential_binding_id
    ):
        raise FullExecutionValidationError("provider route projection is invalid")
    return payload


def _session_coverage(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    *,
    verifier: RunScopedSessionHmacKey,
    evidence: tuple[SessionIdentityEvidence, ...],
) -> dict[str, object]:
    mappings = tuple(
        SessionIdentityMapping(
            corpus_id=item.corpus_id,
            thread_id=item.thread_id,
            case_id=item.case_id,
            conversation_role=role,
            session_alias=alias,
        )
        for item in manifest
        for role, alias in zip(item.session_roles, item.session_aliases, strict=True)
    )
    if (
        type(verifier) is not RunScopedSessionHmacKey
        or not verifier._is_sealed()
        or verifier._run_id != bindings.run_id
        or type(evidence) is not tuple
        or any(type(item) is not SessionIdentityEvidence for item in evidence)
    ):
        raise FullExecutionValidationError("session live validation is invalid")
    contract = session_identity_contract(mappings, evidence, verifier=verifier)
    if not session_identity_contract_is_verified(
        contract,
        expected_mappings=mappings,
        evidence=evidence,
        verifier=verifier,
    ):
        raise FullExecutionValidationError("session mapping coverage is incomplete")
    return {
        "required_mapping_count": len(mappings),
        "verified_mapping_count": len(evidence),
        "corpus_mapping_count": len(manifest),
        "live_verifier": True,
        "mapping_commitment_sha256": _json_sha256(
            [
                {
                    "corpus_id_sha256": hashlib.sha256(item.corpus_id.encode()).hexdigest(),
                    "thread_id_sha256": hashlib.sha256(item.thread_id.encode()).hexdigest(),
                    "case_id_sha256": hashlib.sha256(item.case_id.encode()).hexdigest(),
                    "conversation_role": item.conversation_role,
                    "session_alias_sha256": hashlib.sha256(item.session_alias.encode()).hexdigest(),
                }
                for item in mappings
            ]
        ),
    }


def _transport_coverage(
    bindings: FullComparisonRunBindings,
    *,
    benchmark: str,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    verifier: RunScopedLocomoTransportEvidenceKey | None,
    evidence: tuple[LocomoTimestampTransportEvidence, ...],
) -> dict[str, object]:
    if type(evidence) is not tuple or any(
        type(item) is not LocomoTimestampTransportEvidence for item in evidence
    ):
        raise FullExecutionValidationError("transport evidence must be an exact typed tuple")
    if benchmark == "longmemeval":
        contract = locomo_timestamp_transport_contract(
            benchmark=benchmark,
            evaluations=tuple(
                {"benchmark": "longmemeval", "backend": target.backend_role}
                for target in bindings.backend_targets
                for _item in manifest
            ),
            declared_sent=None,
            run_id=None,
            verifier=None,
            timestamp_evidence=(),
        )
        if verifier is not None or evidence or contract.get("matches") is not True:
            raise FullExecutionValidationError("LongMemEval transport state is not exact")
        return {
            "required": False,
            "required_turn_count": 0,
            "verified_turn_count": 0,
            "corpus_count": 0,
            "live_verifier": False,
            "evidence_commitment_sha256": _json_sha256([]),
        }
    if (
        type(verifier) is not RunScopedLocomoTransportEvidenceKey
        or not verifier._is_sealed()
        or verifier._run_id != bindings.run_id
    ):
        raise FullExecutionValidationError("LoCoMo transport verifier is invalid")
    evaluations = tuple(
        {
            "benchmark": "locomo",
            "backend": "mem0",
            "ingestion": {"metadata": {"corpus_key": item.corpus_id}},
        }
        for item in manifest
    )
    contract = locomo_timestamp_transport_contract(
        benchmark="locomo",
        evaluations=evaluations,
        declared_sent=True,
        run_id=bindings.run_id,
        verifier=verifier,
        timestamp_evidence=evidence,
    )
    if contract.get("matches") is not True:
        raise FullExecutionValidationError("LoCoMo transport contract is incomplete")
    public_evidence = contract.get("evidence")
    if type(public_evidence) is not list:
        raise FullExecutionValidationError("LoCoMo transport projection is invalid")
    counts: dict[str, int] = {}
    triggers: dict[str, set[str]] = {}
    for item in public_evidence:
        if type(item) is not dict:
            raise FullExecutionValidationError("LoCoMo transport projection is invalid")
        corpus_hash = item.get("corpus_key_sha256")
        trigger_hash = item.get("trigger_case_id_sha256")
        if type(corpus_hash) is not str or type(trigger_hash) is not str:
            raise FullExecutionValidationError("LoCoMo transport identity is invalid")
        counts[corpus_hash] = counts.get(corpus_hash, 0) + 1
        triggers.setdefault(corpus_hash, set()).add(trigger_hash)
    for item in manifest:
        corpus_hash = hashlib.sha256(item.corpus_id.encode()).hexdigest()
        case_hash = hashlib.sha256(item.case_id.encode()).hexdigest()
        if counts.get(corpus_hash) != item.official_turn_count or triggers.get(corpus_hash) != {
            case_hash
        }:
            raise FullExecutionValidationError("LoCoMo official turn count differs")
    required_turns = sum(item.official_turn_count for item in manifest)
    if len(public_evidence) != required_turns:
        raise FullExecutionValidationError("LoCoMo total turn count differs")
    return {
        "required": True,
        "required_turn_count": required_turns,
        "verified_turn_count": len(public_evidence),
        "corpus_count": len(manifest),
        "live_verifier": True,
        "evidence_commitment_sha256": _json_sha256(public_evidence),
    }


def _clean_coverage(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    *,
    validation: VerifiedCleanStateValidation,
    scopes: tuple[FullExecutionCleanScope, ...],
    attestation_key: bytes,
) -> dict[str, object]:
    if (
        type(validation) is not VerifiedCleanStateValidation
        or type(scopes) is not tuple
        or any(type(item) is not FullExecutionCleanScope for item in scopes)
        or type(attestation_key) is not bytes
        or len(attestation_key) < 32
    ):
        raise FullExecutionValidationError("clean-state live validation type is invalid")
    required = tuple(
        (target.backend_role, hashlib.sha256(item.corpus_id.encode()).hexdigest())
        for target in bindings.backend_targets
        for item in manifest
    )
    seen: list[tuple[str, str]] = []
    scope_mapping: dict[str, dict[str, str]] = {
        target.backend_role: {} for target in bindings.backend_targets
    }
    for scope in scopes:
        scope.__post_init__()
        key = (scope.backend_role, scope.corpus_identity_sha256)
        if key in seen:
            raise FullExecutionValidationError("clean-state scope is duplicated")
        seen.append(key)
        if scope.backend_role not in scope_mapping:
            raise FullExecutionValidationError("clean-state backend is not a run target")
        scope_mapping[scope.backend_role][scope.corpus_identity_sha256] = (
            scope.scope_identity_sha256
        )
    if tuple(seen) != required:
        raise FullExecutionValidationError("clean-state scope coverage is missing or reordered")
    public = verify_clean_state_contract_for_publication(
        validation,
        expected_run_id_sha256=hashlib.sha256(bindings.run_id.encode()).hexdigest(),
        expected_scopes_by_backend=scope_mapping,
        attestation_key=attestation_key,
    )
    if type(public) is not dict:
        raise FullExecutionValidationError("clean-state live revalidation failed")
    return {
        "backend_count": len(scope_mapping),
        "scope_commitment_sha256": _json_sha256(
            [
                {
                    "backend_role": item.backend_role,
                    "corpus_identity_sha256": item.corpus_identity_sha256,
                    "scope_identity_sha256": item.scope_identity_sha256,
                }
                for item in scopes
            ]
        ),
        "validation_commitment_sha256": _json_sha256(public),
        "required_scope_count": len(required),
        "verified_scope_count": len(scopes),
        "per_backend_scope_count": {
            backend: len(items) for backend, items in scope_mapping.items()
        },
        "live_revalidated": True,
    }


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise FullExecutionValidationError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise FullExecutionValidationError(f"{name} must be SHA-256")
    return value


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = (
    "FULL_EXECUTION_VALIDATION_SCHEMA_VERSION",
    "FullExecutionCaseManifestEntry",
    "FullExecutionCleanScope",
    "FullExecutionProviderCall",
    "FullExecutionValidationError",
    "execution_case_manifest_sha256",
)
