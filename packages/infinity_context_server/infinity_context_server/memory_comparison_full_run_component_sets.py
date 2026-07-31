"""Atomic aggregate-to-slot adapters for full-run evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_full_execution_validation import (
        VerifiedFullExecutionValidation,
    )
    from infinity_context_server.memory_comparison_full_policy_component_validation import (
        VerifiedFullPolicyComponentValidation,
    )
    from infinity_context_server.memory_comparison_full_run_evidence import (
        FullComparisonComponentEvidence,
        FullComparisonEvidenceIssuer,
    )
    from infinity_context_server.memory_comparison_managed_attestation import (
        VerifiedManagedCompositionAttestation,
    )
    from infinity_context_server.memory_comparison_managed_run_ports import (
        ManagedAttestationPort,
        ManagedClockPort,
        ManagedIngestPort,
        ManagedResetPort,
    )


def issue_runtime_component_evidence_from_managed_attestation(
    issuer: FullComparisonEvidenceIssuer,
    validation: VerifiedManagedCompositionAttestation,
    *,
    reset_port: ManagedResetPort,
    attestation_port: ManagedAttestationPort,
    ingest_port: ManagedIngestPort,
    clock: ManagedClockPort,
) -> FullComparisonComponentEvidence:
    """Consume one managed aggregate and atomically mint the runtime slot."""

    from infinity_context_server.memory_comparison_full_run_components import (
        _aggregate_wrapper,
        _begin_aggregate_consumption,
        _evidence_error,
        _finish_aggregate_set,
        _mint_component_set,
        _reserve_aggregate_set,
        _rollback_prevalidation,
        _validate_runtime_aggregate_report,
    )
    from infinity_context_server.memory_comparison_managed_attestation import (
        VerifiedManagedCompositionAttestation,
        _consume_verified_managed_composition_attestation_for_composite,
        public_managed_composition_attestation,
    )

    bindings, _ = _reserve_aggregate_set(issuer, "runtime", require_runtime=False)
    context = (reset_port, attestation_port, ingest_port, clock)
    try:
        if type(validation) is not VerifiedManagedCompositionAttestation:
            raise _evidence_error("runtime aggregate validation type must be exact")
        report = public_managed_composition_attestation(
            validation,
            bindings=bindings,
            reset_port=reset_port,
            attestation_port=attestation_port,
            ingest_port=ingest_port,
            clock=clock,
        )
        managed_commitment = _validate_runtime_aggregate_report(report, bindings)
    except BaseException:
        _rollback_prevalidation(issuer, "runtime")
        raise
    _begin_aggregate_consumption(issuer, "runtime")
    try:
        consumed = _consume_verified_managed_composition_attestation_for_composite(
            validation,
            bindings=bindings,
            reset_port=reset_port,
            attestation_port=attestation_port,
            ingest_port=ingest_port,
            clock=clock,
        )
        if consumed != report:
            raise _evidence_error("runtime aggregate changed during consume")
        wrapper = _aggregate_wrapper(
            source="runtime",
            kinds=("runtime",),
            capability=validation,
            context=context,
            bindings=bindings,
            managed_commitment=managed_commitment,
            report=report,
        )
        components = _mint_component_set(issuer, wrapper, ("runtime",))
    except BaseException:
        _finish_aggregate_set(issuer, "runtime", success=False)
        raise
    _finish_aggregate_set(
        issuer,
        "runtime",
        success=True,
        managed_commitment=managed_commitment,
    )
    return components[0]


def issue_execution_component_evidence_set(
    issuer: FullComparisonEvidenceIssuer,
    validation: VerifiedFullExecutionValidation,
    *,
    case_manifest_sha256: str,
) -> tuple[FullComparisonComponentEvidence, ...]:
    """Consume one execution aggregate and atomically mint its four slots."""

    from infinity_context_server.memory_comparison_full_execution_validation import (
        VerifiedFullExecutionValidation,
        consume_full_execution_validation,
        public_full_execution_validation_report,
    )
    from infinity_context_server.memory_comparison_full_run_components import (
        _EXECUTION_KINDS,
        _aggregate_wrapper,
        _begin_aggregate_consumption,
        _digest_value,
        _evidence_error,
        _finish_aggregate_set,
        _mint_component_set,
        _reserve_aggregate_set,
        _rollback_prevalidation,
        _validate_execution_aggregate_report,
    )

    bindings, managed_commitment = _reserve_aggregate_set(issuer, "execution", require_runtime=True)
    try:
        if type(validation) is not VerifiedFullExecutionValidation:
            raise _evidence_error("execution aggregate validation type must be exact")
        report = public_full_execution_validation_report(validation)
        case_manifest = _validate_execution_aggregate_report(report, bindings)
        if case_manifest != _digest_value(case_manifest_sha256, "case manifest"):
            raise _evidence_error("execution case manifest differs from expected")
    except BaseException:
        _rollback_prevalidation(issuer, "execution")
        raise
    _begin_aggregate_consumption(issuer, "execution")
    try:
        consumed = consume_full_execution_validation(
            validation,
            comparison_commitment_sha256=bindings.binding_commitment_sha256,
            run_id=bindings.run_id,
            profile_id=bindings.profile_id,
            dataset_sha256=bindings.dataset_sha256,
            selection_sha256=bindings.selection_fingerprint_sha256,
            case_manifest_sha256=case_manifest,
        )
        if consumed != report:
            raise _evidence_error("execution aggregate changed during consume")
        wrapper = _aggregate_wrapper(
            source="execution",
            kinds=_EXECUTION_KINDS,
            capability=validation,
            context=(),
            bindings=bindings,
            managed_commitment=managed_commitment,
            report=report,
        )
        components = _mint_component_set(issuer, wrapper, _EXECUTION_KINDS)
    except BaseException:
        _finish_aggregate_set(issuer, "execution", success=False)
        raise
    _finish_aggregate_set(issuer, "execution", success=True)
    return components


def issue_policy_component_evidence_set(
    issuer: FullComparisonEvidenceIssuer,
    validation: VerifiedFullPolicyComponentValidation,
) -> tuple[FullComparisonComponentEvidence, ...]:
    """Consume one policy aggregate and atomically mint delete/canonical/source."""

    from infinity_context_server.memory_comparison_full_policy_component_validation import (
        VerifiedFullPolicyComponentValidation,
        consume_full_policy_component_validation,
        public_full_policy_component_validation,
    )
    from infinity_context_server.memory_comparison_full_run_components import (
        _POLICY_KINDS,
        _aggregate_wrapper,
        _begin_aggregate_consumption,
        _evidence_error,
        _finish_aggregate_set,
        _mint_component_set,
        _reserve_aggregate_set,
        _rollback_prevalidation,
        _validate_policy_aggregate_report,
    )

    bindings, managed_commitment = _reserve_aggregate_set(issuer, "policy", require_runtime=True)
    try:
        if type(validation) is not VerifiedFullPolicyComponentValidation:
            raise _evidence_error("policy aggregate validation type must be exact")
        report = public_full_policy_component_validation(validation)
        policy_binding = _validate_policy_aggregate_report(
            report, bindings, managed_commitment=managed_commitment
        )
    except BaseException:
        _rollback_prevalidation(issuer, "policy")
        raise
    _begin_aggregate_consumption(issuer, "policy")
    try:
        consumed = consume_full_policy_component_validation(
            validation,
            binding_commitment_sha256=policy_binding,
            managed_attestation_commitment_sha256=managed_commitment,
        )
        if consumed != report:
            raise _evidence_error("policy aggregate changed during consume")
        wrapper = _aggregate_wrapper(
            source="policy",
            kinds=_POLICY_KINDS,
            capability=validation,
            context=(),
            bindings=bindings,
            managed_commitment=managed_commitment,
            report=report,
        )
        components = _mint_component_set(issuer, wrapper, _POLICY_KINDS)
    except BaseException:
        _finish_aggregate_set(issuer, "policy", success=False)
        raise
    _finish_aggregate_set(issuer, "policy", success=True)
    return components


__all__ = (
    "issue_execution_component_evidence_set",
    "issue_policy_component_evidence_set",
    "issue_runtime_component_evidence_from_managed_attestation",
)
