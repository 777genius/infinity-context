from __future__ import annotations

import copy
import gc
import hashlib
import hmac
import json

import pytest
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_transport_evidence as _evidence,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_request_binding import (
    ManagedMem0V5AuthenticatedRequestBindingV2Witness,
    ManagedMem0V5RequestBindingV2Context,
    verify_request_binding_v2_payload,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    VerifiedManagedTransportCoverage,
    authenticate_managed_transport_coverage,
    issue_managed_transport_coverage_capability,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssAdmissionRequest,
    Mem0OssFullRunAdmission,
    canonical_sha256,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


KEY = b"k" * 32


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _authority() -> ManagedMem0V5ManifestAuthority:
    cases = []
    for index in range(2):
        corpus_id = f"locomo-corpus-{_sha(f'corpus-{index}')}"
        record = {
            "schema_version": "memory-comparison-managed-corpus.v2",
            "benchmark": "locomo",
            "corpus_id": corpus_id,
            "thread_id": f"locomo-thread-{_sha(f'thread-{index}')}",
            "memories": [
                {
                    "kind": "fact",
                    "role": "user",
                    "session_alias": "session-0001",
                    "source_alias": "memory-000001",
                    "speaker": "Alice",
                    "session_date": "2024-03-10",
                    "text": f"Fact {index}.",
                    "timestamp": 1,
                }
            ],
            "documents": [],
            "conversations": [],
        }
        cases.append(ManagedRunCase(f"case-{index}", corpus_id, record))
    return ManagedMem0V5ManifestProjector().project(tuple(cases), current_date="2026-08-07")


def _admission(authority: ManagedMem0V5ManifestAuthority) -> Mem0OssFullRunAdmission:
    request = Mem0OssAdmissionRequest(
        run_id="transport-coverage-test",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_sha("runtime-source"),
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=authority.operation_count,
    )
    return Mem0OssFullRunAdmission(
        request=request,
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )


def _observations(
    authority: ManagedMem0V5ManifestAuthority,
    admission: Mem0OssFullRunAdmission,
) -> tuple[ManagedMem0V5AuthenticatedRequestBindingV2Witness, ...]:
    receipts = []
    for index, unit in enumerate(authority.units):
        context = ManagedMem0V5RequestBindingV2Context.from_authority(
            authority=authority,
            unit=unit,
            operation_id_sha256=_sha(f"operation-{index}"),
            admission=admission,
        )
        request_body = _sha(f"request-{index}")
        evidence = {**context.evidence_payload(), "request_body_sha256": request_body}
        unsigned = {
            **evidence,
            "request_binding_evidence_sha256": canonical_sha256(evidence),
        }
        receipts.append(
            verify_request_binding_v2_payload(
                payload={
                    **unsigned,
                    "request_binding_hmac_sha256": hmac.new(
                        KEY, _canonical(unsigned), hashlib.sha256
                    ).hexdigest(),
                },
                context=context,
                hmac_key=KEY,
            )
        )
    return tuple(receipts)


@pytest.mark.parametrize("benchmark,locomo_count", (("locomo", 2), ("longmemeval", 0)))
def test_complete_coverage_is_exact_and_longmemeval_claims_zero_locomo(
    benchmark: str, locomo_count: int
) -> None:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    capability = issue_managed_transport_coverage_capability(
        benchmark=benchmark,
        run_id_sha256=_sha(admission.request.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )

    coverage = capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=admission.commitment_sha256,
        expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
    )

    assert coverage.per_corpus_operation_counts == tuple(
        (unit.corpus_id, 1) for unit in authority.units
    )
    assert coverage.operation_count == 2
    assert coverage.locomo_operation_count == locomo_count
    assert coverage.admission_commitment_sha256 == admission.commitment_sha256
    assert coverage.authority_commitment_sha256 == authority.authority_commitment_sha256
    assert coverage.public_payload()["evidence_commitment_sha256"] == (
        coverage.evidence_commitment_sha256
    )
    with pytest.raises(ManagedRunError, match="already consumed"):
        capability.consume_complete_transport_coverage(
            expected_admission_commitment_sha256=admission.commitment_sha256,
            expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
        )


def _coverage() -> VerifiedManagedTransportCoverage:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    capability = issue_managed_transport_coverage_capability(
        benchmark="locomo",
        run_id_sha256=_sha(admission.request.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    return capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=admission.commitment_sha256,
        expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
    )


def test_transport_coverage_authentication_requires_factory_identity() -> None:
    coverage = _coverage()
    values = {
        "benchmark": coverage.benchmark,
        "run_id_sha256": coverage.run_id_sha256,
        "backend_role": coverage.backend_role,
        "admission_commitment_sha256": coverage.admission_commitment_sha256,
        "authority_commitment_sha256": coverage.authority_commitment_sha256,
        "per_corpus_operation_counts": coverage.per_corpus_operation_counts,
        "operation_count": coverage.operation_count,
        "request_binding_evidence_root_sha256": (coverage.request_binding_evidence_root_sha256),
        "evidence_commitment_sha256": coverage.evidence_commitment_sha256,
        "_authentication_sha256": coverage._authentication_sha256,
        "_token": _evidence._VERIFIED_TOKEN,
    }

    class CopiedCoverage(VerifiedManagedTransportCoverage):
        pass

    candidates = (
        copy.copy(coverage),
        copy.deepcopy(coverage),
        VerifiedManagedTransportCoverage(**values),
        CopiedCoverage(**values),
    )
    for candidate in candidates:
        with pytest.raises(ManagedRunError, match="unauthenticated"):
            authenticate_managed_transport_coverage(candidate)
    assert authenticate_managed_transport_coverage(coverage) is coverage


def test_transport_coverage_registry_returns_to_gc_baseline() -> None:
    gc.collect()
    baseline = len(_evidence._VERIFIED_REGISTRY)
    for _ in range(20):
        coverage = _coverage()
        assert authenticate_managed_transport_coverage(coverage) is coverage
        del coverage
    gc.collect()

    assert len(_evidence._VERIFIED_REGISTRY) == baseline


def test_raw_receipts_reissue_and_post_issue_mutation_are_rejected() -> None:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    common = {
        "benchmark": "locomo",
        "run_id_sha256": _sha(admission.request.run_id),
        "backend_role": "mem0",
        "authority": authority,
        "admission": admission,
    }
    with pytest.raises(ManagedRunError, match="input is invalid"):
        issue_managed_transport_coverage_capability(
            observations=tuple(item.receipt for item in observations), **common
        )
    capability = issue_managed_transport_coverage_capability(observations=observations, **common)
    with pytest.raises(ManagedRunError, match="unauthenticated"):
        issue_managed_transport_coverage_capability(observations=observations, **common)
    coverage = capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=admission.commitment_sha256,
        expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
    )
    object.__setattr__(coverage, "operation_count", 1)
    object.__setattr__(
        coverage,
        "evidence_commitment_sha256",
        canonical_sha256(coverage.commitment_payload()),
    )
    with pytest.raises(ManagedRunError, match="coverage is invalid"):
        coverage.public_payload()


def test_coverage_rejects_missing_duplicate_and_misbound_observations() -> None:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    common = {
        "benchmark": "locomo",
        "run_id_sha256": _sha(admission.request.run_id),
        "backend_role": "mem0",
        "authority": authority,
        "admission": admission,
    }
    with pytest.raises(ManagedRunError, match="authority differs"):
        issue_managed_transport_coverage_capability(observations=observations[:-1], **common)
    with pytest.raises(ManagedRunError, match="observation differs"):
        issue_managed_transport_coverage_capability(
            observations=(observations[0], observations[0]),
            **common,
        )


def test_coverage_rejects_mutated_authenticated_witness() -> None:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    object.__setattr__(observations[0].receipt, "corpus_id", "forged-corpus")

    with pytest.raises(ManagedRunError, match="unauthenticated"):
        issue_managed_transport_coverage_capability(
            benchmark="locomo",
            run_id_sha256=_sha(admission.request.run_id),
            backend_role="mem0",
            authority=authority,
            admission=admission,
            observations=observations,
        )


def test_capability_uses_private_snapshot_after_caller_mutates_receipt() -> None:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    operation_ids = tuple(item.operation_id_sha256 for item in observations)
    original_root = canonical_sha256(
        {
            "request_binding_evidence_sha256": [
                item.receipt.request_binding_evidence_sha256 for item in observations
            ]
        }
    )
    capability = issue_managed_transport_coverage_capability(
        benchmark="locomo",
        run_id_sha256=_sha(admission.request.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    exposed_receipt = observations[0].receipt
    object.__setattr__(exposed_receipt, "request_body_sha256", _sha("mutated-request"))
    mutated_evidence = exposed_receipt.payload()
    mutated_evidence.pop("request_binding_evidence_sha256")
    object.__setattr__(
        exposed_receipt,
        "request_binding_evidence_sha256",
        canonical_sha256(mutated_evidence),
    )

    coverage = capability.consume_complete_transport_coverage(
        expected_admission_commitment_sha256=admission.commitment_sha256,
        expected_operation_ids=operation_ids,
    )

    assert coverage.request_binding_evidence_root_sha256 == original_root


def test_capability_consumes_before_expectation_failure() -> None:
    authority = _authority()
    admission = _admission(authority)
    observations = _observations(authority, admission)
    capability = issue_managed_transport_coverage_capability(
        benchmark="locomo",
        run_id_sha256=_sha(admission.request.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    with pytest.raises(ManagedRunError, match="expectation differs"):
        capability.consume_complete_transport_coverage(
            expected_admission_commitment_sha256="0" * 64,
            expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
        )
    with pytest.raises(ManagedRunError, match="already consumed"):
        capability.consume_complete_transport_coverage(
            expected_admission_commitment_sha256=admission.commitment_sha256,
            expected_operation_ids=tuple(item.operation_id_sha256 for item in observations),
        )
