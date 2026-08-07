from __future__ import annotations

import copy
import hashlib
import pickle

import pytest
from infinity_context_server import memory_comparison_full_execution_evidence_variants as _variants
from infinity_context_server.memory_comparison_clean_state import (
    VerifiedCleanStateValidation,
)
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    FullExecutionCleanStateEvidence,
    FullExecutionTransportEvidence,
    inspect_full_execution_clean_state_evidence,
    inspect_full_execution_transport_evidence,
    issue_legacy_full_execution_clean_state_evidence,
    issue_legacy_full_execution_transport_evidence,
    issue_managed_mem0_v5_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCleanScope,
    FullExecutionValidationError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CleanCorpusScope,
    create_managed_mem0_v5_clean_state_witness_authority,
    require_managed_mem0_v5_clean_state_witness_verifier,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_legacy_transport_variant_is_opaque_and_exact() -> None:
    evidence = issue_legacy_full_execution_transport_evidence(
        benchmark="longmemeval",
        verifier=None,
        evidence=(),
    )

    descriptor = inspect_full_execution_transport_evidence(evidence)

    assert descriptor.variant == "legacy_v1"
    assert descriptor.benchmark == "longmemeval"
    assert not hasattr(descriptor, "live_resources")
    assert not hasattr(descriptor, "live_resource_tokens")
    for operation in (
        lambda: copy.copy(evidence),
        lambda: copy.deepcopy(evidence),
        lambda: pickle.dumps(evidence),
    ):
        with pytest.raises(TypeError):
            operation()
    with pytest.raises(FullExecutionValidationError, match="variant_invalid"):
        inspect_full_execution_transport_evidence(object.__new__(FullExecutionTransportEvidence))


def test_legacy_clean_variant_detects_post_issue_mutation() -> None:
    payload = {"eligible": True}
    validation = VerifiedCleanStateValidation(payload)
    scope = FullExecutionCleanScope("infinity-context", _sha("corpus"), _sha("scope"))
    evidence = issue_legacy_full_execution_clean_state_evidence(
        validation=validation,
        scopes=(scope,),
        attestation_key=b"k" * 32,
    )
    assert inspect_full_execution_clean_state_evidence(evidence).backend_roles == (
        "infinity-context",
    )

    payload["eligible"] = False

    with pytest.raises(FullExecutionValidationError, match="evidence_changed"):
        inspect_full_execution_clean_state_evidence(evidence)
    with pytest.raises(FullExecutionValidationError, match="variant_invalid"):
        inspect_full_execution_clean_state_evidence(object.__new__(FullExecutionCleanStateEvidence))


def test_managed_clean_variant_reauthenticates_original_witness() -> None:
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority(hmac_key=b"v" * 32)
    witness = issuer.issue_authenticated_clean_state(
        admission_commitment_sha256=_sha("admission"),
        run_id_sha256=_sha("run"),
        authority_commitment_sha256=_sha("authority"),
        scopes=(
            ManagedMem0V5CleanCorpusScope(
                corpus_identity_sha256=_sha("corpus"),
                scope_identity_sha256=_sha("scope"),
                source_scope_count=1,
                residual_record_count=0,
                residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
            ),
        ),
    )
    evidence = issue_managed_mem0_v5_full_execution_clean_state_evidence(
        backend_role="mem0",
        witness=witness,
        verifier=verifier,
    )

    descriptor = inspect_full_execution_clean_state_evidence(evidence)

    assert descriptor.variant == "managed_mem0_v5"
    assert descriptor.backend_roles == ("mem0",)
    assert not hasattr(descriptor, "live_resources")
    assert not hasattr(descriptor, "live_resource_tokens")
    assert "verifier" not in repr(descriptor).lower()
    with pytest.raises(TypeError):
        pickle.dumps(descriptor)
    object.__setattr__(witness, "run_id_sha256", _sha("changed"))
    with pytest.raises(FullExecutionValidationError, match="evidence_changed"):
        inspect_full_execution_clean_state_evidence(evidence)


def test_clean_verifier_rejects_structural_fake() -> None:
    class StructuralVerifier:
        def authenticate_clean_state(self, witness: object) -> object:
            return witness

    with pytest.raises(ManagedRunError, match="authority is invalid"):
        require_managed_mem0_v5_clean_state_witness_verifier(StructuralVerifier())


def test_public_evidence_api_does_not_export_replay_resource_access() -> None:
    assert all("resource" not in name for name in _variants.__all__)
    assert all(not name.startswith("_inspect") for name in _variants.__all__)
