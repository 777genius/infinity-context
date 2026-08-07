"""Neutral v2 slot policy for full-execution evidence variants."""

from __future__ import annotations

import hashlib

from infinity_context_server import memory_comparison_full_run_evidence as _run_evidence
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    _inspect_full_execution_clean_state_evidence_for_validation,
    _inspect_full_execution_transport_evidence_for_validation,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    FullExecutionProviderCall,
    FullExecutionValidationError,
    _clean_coverage,
    _identifier,
    _json_sha256,
    _provider_coverage,
    _session_coverage,
    _validated_manifest,
    _validated_route,
    execution_case_manifest_sha256,
    validate_full_execution_slots,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_session_identity_contract import (
    RunScopedSessionHmacKey,
    SessionIdentityEvidence,
)

FULL_EXECUTION_VALIDATION_EVIDENCE_SCHEMA_VERSION = "memory-comparison-full-execution-validation.v2"


def validate_full_execution_evidence_slots(
    *,
    bindings: FullComparisonRunBindings,
    benchmark: str,
    case_manifest: tuple[FullExecutionCaseManifestEntry, ...],
    required_model: str,
    required_route: ProviderRouteAttestation,
    provider_calls: tuple[FullExecutionProviderCall, ...],
    session_verifier: RunScopedSessionHmacKey,
    session_evidence: tuple[SessionIdentityEvidence, ...],
    transport_evidence: object,
    clean_state_evidence: tuple[object, ...],
) -> dict[str, object]:
    """Validate neutral evidence variants without coercing provider contracts."""

    try:
        trusted_bindings = _run_evidence._validate_bindings(bindings)
    except Exception:
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid") from None
    profile = resolve_full_comparison_profile(trusted_bindings.profile_id)
    if profile is None or profile.benchmark != benchmark:
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    manifest = _validated_manifest(case_manifest, benchmark=benchmark)
    transport_inspection = _inspect_full_execution_transport_evidence_for_validation(
        transport_evidence
    )
    transport = transport_inspection.descriptor
    if type(clean_state_evidence) is not tuple or not clean_state_evidence:
        raise FullExecutionValidationError("full_execution_evidence_coverage_missing")
    clean_inspections = tuple(
        _inspect_full_execution_clean_state_evidence_for_validation(item)
        for item in clean_state_evidence
    )
    clean_claims = tuple(item.descriptor for item in clean_inspections)

    target_roles = tuple(item.backend_role for item in trusted_bindings.backend_targets)
    if transport.variant == "legacy_v1" and len(clean_claims) == 1:
        claim = clean_claims[0]
        if claim.variant == "legacy_v1" and claim.backend_roles == target_roles:
            verifier, legacy_transport = _legacy_transport_resources(
                benchmark, transport_inspection.resources
            )
            validation, scopes, key = _legacy_clean_resources(clean_inspections[0].resources)
            return validate_full_execution_slots(
                bindings=bindings,
                benchmark=benchmark,
                case_manifest=case_manifest,
                required_model=required_model,
                required_route=required_route,
                provider_calls=provider_calls,
                session_verifier=session_verifier,
                session_evidence=session_evidence,
                transport_verifier=verifier,
                transport_evidence=legacy_transport,
                clean_validation=validation,
                clean_scopes=scopes,
                clean_attestation_key=key,
            )

    if transport.variant != "managed_mem0_v5":
        raise FullExecutionValidationError("full_execution_evidence_cross_variant_mismatch")
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
    transport_report = _managed_v5_transport_coverage(
        trusted_bindings,
        benchmark=benchmark,
        manifest=manifest,
        descriptor=transport,
    )
    clean_report = _variant_clean_coverage(
        trusted_bindings,
        manifest,
        inspections=clean_inspections,
        transport=transport,
    )
    return {
        "schema_version": FULL_EXECUTION_VALIDATION_EVIDENCE_SCHEMA_VERSION,
        "evidence_variant": "neutral_v2",
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
        "official_transport_coverage": transport_report,
        "clean_state_coverage": clean_report,
        "component_only": True,
        "externally_authentic": False,
        "composite_wiring_required": True,
        "admission_from_public_mapping": False,
    }


def _managed_v5_transport_coverage(
    bindings: FullComparisonRunBindings,
    *,
    benchmark: str,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    descriptor: object,
) -> dict[str, object]:
    run_id_sha256 = hashlib.sha256(bindings.run_id.encode()).hexdigest()
    target_roles = tuple(item.backend_role for item in bindings.backend_targets)
    if (
        descriptor.benchmark != benchmark
        or descriptor.run_id_sha256 != run_id_sha256
        or descriptor.backend_roles != ("mem0",)
        or "mem0" not in target_roles
        or not is_sha256(descriptor.admission_commitment_sha256)
        or not is_sha256(descriptor.authority_commitment_sha256)
    ):
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    corpus_order = tuple(dict.fromkeys(item.corpus_id for item in manifest))
    counts = descriptor.per_corpus_operation_counts
    if (
        type(counts) is not tuple  # noqa: E721 - exact tuple contract required
        or tuple(item[0] for item in counts) != corpus_order
        or any(
            type(item[1]) is not int or item[1] < 1  # noqa: E721
            for item in counts
        )
        or descriptor.operation_count != sum(item[1] for item in counts)
    ):
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    manifest_counts: dict[str, int] = {}
    for item in manifest:
        manifest_counts.setdefault(item.corpus_id, item.official_turn_count)
        if manifest_counts[item.corpus_id] != item.official_turn_count:
            raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    if benchmark == "locomo" and counts != tuple(manifest_counts.items()):
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    return {
        "variant": "managed_mem0_v5",
        "backend_role": "mem0",
        "operation_count": descriptor.operation_count,
        "per_corpus_operation_counts": [
            {"corpus_id_sha256": hashlib.sha256(corpus_id.encode()).hexdigest(), "count": count}
            for corpus_id, count in counts
        ],
        "admission_commitment_sha256": descriptor.admission_commitment_sha256,
        "authority_commitment_sha256": descriptor.authority_commitment_sha256,
        "evidence_commitment_sha256": descriptor.evidence_commitment_sha256,
        "live_revalidated": True,
    }


def _variant_clean_coverage(
    bindings: FullComparisonRunBindings,
    manifest: tuple[FullExecutionCaseManifestEntry, ...],
    *,
    inspections: tuple[object, ...],
    transport: object,
) -> dict[str, object]:
    claims = tuple(item.descriptor for item in inspections)
    target_roles = tuple(item.backend_role for item in bindings.backend_targets)
    claimed_roles: list[str] = []
    for claim in claims:
        for role in claim.backend_roles:
            if role in claimed_roles:
                raise FullExecutionValidationError("full_execution_evidence_coverage_duplicate")
            claimed_roles.append(role)
    if any(role not in target_roles for role in claimed_roles):
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    if set(claimed_roles) != set(target_roles):
        raise FullExecutionValidationError("full_execution_evidence_coverage_missing")
    managed_roles = {
        role
        for claim in claims
        if claim.variant == "managed_mem0_v5"
        for role in claim.backend_roles
    }
    if managed_roles != set(transport.backend_roles):
        raise FullExecutionValidationError("full_execution_evidence_cross_variant_mismatch")

    run_id_sha256 = hashlib.sha256(bindings.run_id.encode()).hexdigest()
    corpus_ids = tuple(dict.fromkeys(item.corpus_id for item in manifest))
    corpus_hashes = tuple(canonical_sha256({"corpus_id": item}) for item in corpus_ids)
    transport_counts = dict(transport.per_corpus_operation_counts)
    public_claims: list[dict[str, object]] = []
    total_scopes = 0
    for inspection in inspections:
        claim = inspection.descriptor
        if claim.variant == "infinity_di":
            if claim.backend_roles != ("infinity-context",) or claim.run_id_sha256 != run_id_sha256:
                raise FullExecutionValidationError("full_execution_evidence_cross_variant_mismatch")
            scopes = claim.corpus_scopes
            if tuple(item[0] for item in scopes) != corpus_hashes or any(
                item[2] != 0 for item in scopes
            ):
                raise FullExecutionValidationError("full_execution_evidence_coverage_missing")
            total_scopes += len(scopes)
            public_claims.append(
                {
                    "variant": "infinity_di",
                    "backend_roles": ["infinity-context"],
                    "verified_scope_count": len(scopes),
                    "evidence_commitment_sha256": claim.evidence_commitment_sha256,
                }
            )
            continue
        if claim.variant == "legacy_v1":
            validation, scopes, key = _legacy_clean_resources(inspection.resources)
            legacy = _clean_coverage(
                bindings,
                manifest,
                validation=validation,
                scopes=scopes,
                attestation_key=key,
            )
            selected = tuple(item for item in scopes if item.backend_role in claim.backend_roles)
            expected_selected = len(corpus_ids) * len(claim.backend_roles)
            if len(selected) != expected_selected:
                raise FullExecutionValidationError("full_execution_evidence_coverage_missing")
            total_scopes += len(selected)
            public_claims.append(
                {
                    "variant": "di_authenticated",
                    "backend_roles": list(claim.backend_roles),
                    "verified_scope_count": len(selected),
                    "evidence_commitment_sha256": claim.evidence_commitment_sha256,
                    "validation_commitment_sha256": legacy["validation_commitment_sha256"],
                }
            )
            continue
        if claim.variant != "managed_mem0_v5" or claim.backend_roles != ("mem0",):
            raise FullExecutionValidationError("full_execution_evidence_cross_variant_mismatch")
        if (
            claim.run_id_sha256 != run_id_sha256
            or claim.admission_commitment_sha256 != transport.admission_commitment_sha256
            or claim.authority_commitment_sha256 != transport.authority_commitment_sha256
        ):
            raise FullExecutionValidationError("full_execution_evidence_cross_variant_mismatch")
        scopes = claim.corpus_scopes
        if tuple(item[0] for item in scopes) != corpus_hashes:
            raise FullExecutionValidationError("full_execution_evidence_coverage_missing")
        expected_counts = tuple(transport_counts[item] for item in corpus_ids)
        if tuple(item[2] for item in scopes) != expected_counts:
            raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
        total_scopes += len(scopes)
        public_claims.append(
            {
                "variant": "managed_mem0_v5",
                "backend_roles": ["mem0"],
                "verified_scope_count": len(scopes),
                "admission_commitment_sha256": claim.admission_commitment_sha256,
                "authority_commitment_sha256": claim.authority_commitment_sha256,
                "evidence_commitment_sha256": claim.evidence_commitment_sha256,
            }
        )
    return {
        "variant": "mixed_exact_claims",
        "backend_count": len(target_roles),
        "required_scope_count": len(target_roles) * len(corpus_ids),
        "verified_scope_count": total_scopes,
        "claims": public_claims,
        "coverage_commitment_sha256": _json_sha256(public_claims),
        "live_revalidated": True,
    }


def _legacy_transport_resources(
    benchmark: str,
    resources: tuple[object, ...],
) -> tuple[object | None, tuple[object, ...]]:
    if benchmark == "longmemeval":
        if resources:
            raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
        return None, ()
    if not resources:
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    return resources[0], resources[1:]


def _legacy_clean_resources(
    resources: tuple[object, ...],
) -> tuple[object, tuple[object, ...], bytes]:
    if len(resources) < 3 or type(resources[-1]) is not bytes:  # noqa: E721
        raise FullExecutionValidationError("full_execution_evidence_binding_invalid")
    return resources[0], resources[1:-1], resources[-1]


__all__ = (
    "FULL_EXECUTION_VALIDATION_EVIDENCE_SCHEMA_VERSION",
    "validate_full_execution_evidence_slots",
)
