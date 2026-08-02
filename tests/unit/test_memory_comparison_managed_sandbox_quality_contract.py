from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionProviderCall,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    JUDGE_RESULT_SCHEMA_VERSION,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedCaseExecution,
    create_managed_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderRouteAttestation,
)
from managed_run_test_support import make_plan

sys.path.insert(0, str(Path(__file__).parents[1] / "e2e"))
_sealed_quality_outcome = importlib.import_module(
    "managed_comparison_sandbox_execution"
)._sealed_quality_outcome


def test_sandbox_quality_producer_issues_an_opaque_receipt_proof() -> None:
    bindings = create_managed_comparison_run_bindings(make_plan())
    execution = ManagedCaseExecution(
        case_id="case-1",
        backend_role="infinity-context",
        target_identity_sha256="4" * 64,
        retrieval_receipt=object(),
        answer_receipt={"answer": "safe"},
        judge_receipt={
            "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
            "verdict": "partial",
            "score": 0.4,
        },
    )
    calls = _provider_calls(bindings, execution)

    proof = _sealed_quality_outcome(
        bindings=bindings,
        execution=execution,
        provider_calls=calls,
    )

    assert repr(proof) == "ManagedSealedJudgeOutcome(<opaque>)"
    assert not any(
        hasattr(proof, field)
        for field in ("case_alias", "backend_role", "verdict", "score", "judge_result_sha256")
    )


def _provider_calls(bindings, execution: ManagedCaseExecution):
    route = ProviderRouteAttestation(
        trust="official_openai",
        origin="https://api.openai.com",
        endpoint_path="/v1/chat/completions",
        route_sha256="a" * 64,
        transport_evidence="direct_https",
        credential_binding_id="sha256:" + "b" * 64,
        request_method="POST",
        response_status=200,
    )
    return {
        (execution.case_id, execution.backend_role, stage): FullExecutionProviderCall(
            bindings.binding_commitment_sha256,
            bindings.run_id,
            bindings.profile_id,
            execution.case_id,
            execution.backend_role,
            stage,
            False,
            ProviderCallProvenance(
                route,
                "sandbox-model",
                "sandbox-model",
                f"receipt-{stage}",
                "sandbox-fingerprint",
                hashlib.sha256(stage.encode()).hexdigest(),
            ),
        )
        for stage in ("answerer", "judge")
    }
