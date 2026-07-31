from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCaseManifestEntry,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindContractError,
    verified_gold_blind_execution_report,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    _load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_managed_composite_assembler import (
    ManagedFullComparisonAssembler,
)
from infinity_context_server.memory_comparison_managed_run import (
    ManagedRunCase,
    ManagedRunPlan,
    public_managed_run,
    run_managed_comparison,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from managed_comparison_sandbox_adapters import (
    INFINITY_BACKEND,
    MEM0_BACKEND,
    RUNTIME_NONCE,
    SANDBOX_SCOPE,
    SandboxBackendState,
    SandboxTrace,
    implementation_sha256,
)
from managed_comparison_sandbox_execution import SandboxExecutionPort
from managed_comparison_sandbox_policy import SandboxPolicyPort
from managed_comparison_sandbox_runtime import SandboxRuntimePorts, build_runtime_ports

_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "memory_comparison" / "managed-locomo-sandbox.json"
)


@dataclass(frozen=True, slots=True)
class _Rig:
    plan: ManagedRunPlan
    public_case: PublicBenchmarkCase
    trace: SandboxTrace
    state: SandboxBackendState
    runtime: SandboxRuntimePorts
    execution: SandboxExecutionPort
    policy: SandboxPolicyPort
    assembler: ManagedFullComparisonAssembler


def test_managed_locomo_canary_runs_real_nine_slot_lifecycle_without_skips() -> None:
    rig = _rig("success")
    outcome = _run(rig)
    report = public_managed_run(outcome)

    assert rig.execution.case_manifest is rig.plan.case_manifest
    assert len(rig.execution.provider_calls) == 4
    assert tuple((call.backend_role, call.stage) for call in rig.execution.provider_calls) == (
        (INFINITY_BACKEND, "answerer"),
        (INFINITY_BACKEND, "judge"),
        (MEM0_BACKEND, "answerer"),
        (MEM0_BACKEND, "judge"),
    )
    assert rig.execution.gold_validation is not None
    gold = verified_gold_blind_execution_report(rig.execution.gold_validation)
    assert gold["expected_case_count"] == 2
    assert gold["retrieval_dispatch_count"] == 2
    assert gold["answer_dispatch_count"] == 2
    assert gold["judge_dispatch_count"] == 2
    assert report["scope"] == "canary"
    assert report["publishable"] is False
    assert [item["component_kind"] for item in report["components"]] == list(
        FULL_COMPARISON_COMPONENT_KINDS
    )
    assert {item["status"] for item in report["components"]} == {"verified"}
    assert report["managed_run"]["case_count"] == 1
    assert report["managed_run"]["component_count"] == 9
    assert report["managed_run"]["terminal_delete_complete"] is True

    case_id = rig.public_case.case_id
    assert rig.trace.events == _expected_adapter_trace(case_id)
    assert report["managed_run"]["trace"] == _expected_managed_trace(case_id)
    assert rig.trace.events.index("canonical_source.seal") < rig.trace.events.index(
        f"delete:{INFINITY_BACKEND}:1"
    )
    assert not rig.state.stores
    assert tuple(
        (
            observation.backend_role,
            observation.pass_index,
            observation.deleted_count,
            observation.remaining_count,
        )
        for observation in rig.state.delete_observations.values()
    ) == (
        (INFINITY_BACKEND, 1, 1, 0),
        (MEM0_BACKEND, 1, 1, 0),
        (INFINITY_BACKEND, 2, 0, 0),
        (MEM0_BACKEND, 2, 0, 0),
    )


def test_dirty_prestate_never_reaches_a_public_verdict() -> None:
    rig = _rig("dirty")
    rig.state.seed_dirty()
    with pytest.raises(RuntimeError, match="dirty prestate"):
        _run(rig)
    assert "canonical_source.seal" not in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events


def test_candidate_source_mismatch_never_reaches_a_public_verdict() -> None:
    rig = _rig("candidate-mismatch", answer_text="black coffee")
    with pytest.raises(
        GoldBlindContractError, match="Trusted judge evaluator failed"
    ) as raised:
        _run(rig)
    assert not getattr(raised.value, "__notes__", ())
    assert "delete.seal" in rig.trace.events
    assert "canonical_source.seal" not in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events


def test_nonzero_second_delete_pass_never_reaches_a_public_verdict() -> None:
    rig = _rig("pass2-nonzero")
    rig.state.repopulate_on_second_pass = True
    with pytest.raises(AssertionError):
        _run(rig)
    assert "canonical_source.seal" in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events


def test_wrong_scope_delete_cannot_remove_the_ingested_source() -> None:
    raw, _case = _fixture_case()
    state = SandboxBackendState.create()
    state.ingest(INFINITY_BACKEND, "sandbox-locomo-1", raw)
    observed = state.delete(
        INFINITY_BACKEND,
        "wrong-scope",
        "sandbox-locomo-1",
        1,
    )
    assert observed.deleted_count == 0
    assert state.source(INFINITY_BACKEND, "sandbox-locomo-1").text == (
        "Alice bought green tea after work."
    )
    assert (INFINITY_BACKEND, SANDBOX_SCOPE, "sandbox-locomo-1") in state.stores


def _rig(name: str, *, answer_text: str = "green tea") -> _Rig:
    raw, public_case = _fixture_case()
    run_id = f"managed-locomo-sandbox-{name}"
    corpus_id = str(raw["sample_id"])
    case = ManagedRunCase(public_case.case_id, corpus_id, raw)
    manifest = (
        FullExecutionCaseManifestEntry(
            public_case.case_id,
            corpus_id,
            f"sandbox-thread-{name}",
            ("memory", "query"),
            ("session-0001", "session-0002"),
            1,
        ),
    )
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    route = _provider_route(name)
    mem0_target = mem0_runtime_target_identity_sha256(
        f"https://mem0.example.test/managed-locomo-{name}"
    )
    plan = ManagedRunPlan(
        run_id=run_id,
        run_nonce_commitment_sha256=hashlib.sha256(f"{name}:run-nonce".encode()).hexdigest(),
        runtime_probe_nonce_sha256=hashlib.sha256(RUNTIME_NONCE.encode()).hexdigest(),
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=profile.expected_dataset_hash,
        selection_fingerprint_sha256=hashlib.sha256(f"{name}:one-case".encode()).hexdigest(),
        backend_targets=(
            FullComparisonBackendTarget(
                INFINITY_BACKEND,
                hashlib.sha256(name.encode()).hexdigest(),
            ),
            FullComparisonBackendTarget(MEM0_BACKEND, mem0_target),
        ),
        case_manifest=manifest,
        provider_route=route,
        cases=(case,),
        scope="canary",
    )
    trace = SandboxTrace.create()
    state = SandboxBackendState.create()
    runtime = build_runtime_ports(
        trace,
        state,
        run_id=run_id,
        probe_nonce_sha256=plan.runtime_probe_nonce_sha256,
        target_identity_sha256=mem0_target,
    )
    execution = SandboxExecutionPort(
        trace,
        state=state,
        public_case=public_case,
        case_manifest=manifest,
        provider_route=route,
        answer_text=answer_text,
    )
    policy = SandboxPolicyPort(trace, state)
    assembler = ManagedFullComparisonAssembler(
        adapter_id="managed-locomo-sandbox-assembler",
        implementation_sha256=implementation_sha256("assembler"),
        reset_port=runtime.reset,
        attestation_port=runtime.attestation,
        ingest_port=runtime.ingest,
        clock=runtime.clock,
    )
    return _Rig(plan, public_case, trace, state, runtime, execution, policy, assembler)


def _run(rig: _Rig):
    return run_managed_comparison(
        rig.plan,
        reset_port=rig.runtime.reset,
        attestation_port=rig.runtime.attestation,
        ingest_port=rig.runtime.ingest,
        clock=rig.runtime.clock,
        execution_port=rig.execution,
        policy_port=rig.policy,
        assembler=rig.assembler,
    )


def _fixture_case() -> tuple[dict[str, object], PublicBenchmarkCase]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert type(payload) is list and len(payload) == 1 and type(payload[0]) is dict
    public_cases = _load_memory_comparison_cases(
        _FIXTURE,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )
    assert len(public_cases) == 1
    return payload[0], public_cases[0]


def _provider_route(name: str) -> ProviderRouteAttestation:
    return ProviderRouteAttestation(
        trust="sandbox_only",
        origin="https://provider.example.test",
        endpoint_path="/sandbox/chat/completions",
        route_sha256=hashlib.sha256(f"{name}:provider-route".encode()).hexdigest(),
        transport_evidence="in_process_sandbox",
        credential_binding_id="sha256:" + hashlib.sha256(f"{name}:key".encode()).hexdigest(),
        request_method="POST",
        response_status=200,
    )


def _expected_adapter_trace(case_id: str) -> list[str]:
    return [
        "reset",
        "attest",
        f"ingest:{INFINITY_BACKEND}",
        f"ingest:{MEM0_BACKEND}",
        f"retrieve:{INFINITY_BACKEND}:{case_id}",
        f"answer:{INFINITY_BACKEND}:{case_id}",
        f"judge:{INFINITY_BACKEND}:{case_id}",
        f"retrieve:{MEM0_BACKEND}:{case_id}",
        f"answer:{MEM0_BACKEND}:{case_id}",
        f"judge:{MEM0_BACKEND}:{case_id}",
        "execution.seal",
        "canonical_source.issue",
        "canonical_source.seal",
        f"delete:{INFINITY_BACKEND}:1",
        f"delete:{MEM0_BACKEND}:1",
        f"delete:{INFINITY_BACKEND}:2",
        f"delete:{MEM0_BACKEND}:2",
        "delete.seal",
        "policy.aggregate",
    ]


def _expected_managed_trace(case_id: str) -> list[str]:
    return [
        "bindings.create",
        "issuer.create",
        "reset.complete",
        "attestation.live",
        f"ingest:{INFINITY_BACKEND}:sandbox-locomo-1",
        f"ingest:{MEM0_BACKEND}:sandbox-locomo-1",
        f"retrieve:{INFINITY_BACKEND}:{case_id}",
        f"answer:{INFINITY_BACKEND}:{case_id}",
        f"judge:{INFINITY_BACKEND}:{case_id}",
        f"retrieve:{MEM0_BACKEND}:{case_id}",
        f"answer:{MEM0_BACKEND}:{case_id}",
        f"judge:{MEM0_BACKEND}:{case_id}",
        "execution.seal",
        "canonical_source.seal",
        f"delete:{INFINITY_BACKEND}:1",
        f"delete:{MEM0_BACKEND}:1",
        f"delete:{INFINITY_BACKEND}:2",
        f"delete:{MEM0_BACKEND}:2",
        "delete.seal",
        "policy.aggregate",
        "components.issue",
        "verdict.seal",
        "verdict.public",
    ]
