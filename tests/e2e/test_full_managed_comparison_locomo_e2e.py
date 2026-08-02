from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
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
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
    build_verified_managed_run_plan,
)
from infinity_context_server.memory_comparison_managed_run import (
    public_managed_run,
    run_managed_comparison,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    mem0_runtime_target_identity_sha256,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)
from infinity_context_server.public_benchmark_checkpoint import (
    selected_case_fingerprint,
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
from managed_comparison_sandbox_execution import (
    SandboxExecutionPort,
    SandboxJudgePort,
    locomo_answer_from_source,
)
from managed_comparison_sandbox_policy import SandboxPolicyPort
from managed_comparison_sandbox_runtime import SandboxRuntimePorts, build_runtime_ports

_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "memory_comparison" / "managed-locomo-sandbox.json"
)


@dataclass(frozen=True, slots=True)
class _Rig:
    admission: VerifiedManagedRunPlan
    public_case: PublicBenchmarkCase
    trace: SandboxTrace
    state: SandboxBackendState
    runtime: SandboxRuntimePorts
    execution: SandboxExecutionPort
    judge: SandboxJudgePort
    policy: SandboxPolicyPort
    assembler: ManagedFullComparisonAssembler


def test_managed_locomo_canary_runs_real_nine_slot_lifecycle_without_skips() -> None:
    rig = _rig("success")
    outcome = _run(rig)
    report = public_managed_run(outcome)

    case_alias = _case_alias(rig.public_case)
    assert rig.judge.case_manifest is not None
    assert tuple(item.case_id for item in rig.judge.case_manifest) == (case_alias,)
    assert tuple(item.session_roles for item in rig.judge.case_manifest) == (("memory-0001",),)
    assert tuple(item.session_aliases for item in rig.judge.case_manifest) == (("session-0001",),)
    assert len(rig.execution.provider_calls) == 4
    assert tuple((call.backend_role, call.stage) for call in rig.execution.provider_calls) == (
        (INFINITY_BACKEND, "answerer"),
        (INFINITY_BACKEND, "judge"),
        (MEM0_BACKEND, "answerer"),
        (MEM0_BACKEND, "judge"),
    )
    assert rig.judge.gold_validation is not None
    gold = verified_gold_blind_execution_report(rig.judge.gold_validation)
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
    assert (
        report["commitments"]["dataset_sha256"] == hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    )
    assert report["commitments"]["selection_sha256"] == selected_case_fingerprint(
        (rig.public_case,)
    )
    canonical = json.dumps(
        _managed_corpus_record(rig.public_case),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert {receipt.source_sha256 for receipt in rig.runtime.ingest.receipts} == {
        hashlib.sha256(canonical).hexdigest()
    }
    for forbidden in (
        rig.public_case.case_id.encode(),
        rig.public_case.question.encode(),
        b'"_evaluator_ground_truth"',
        b'"expected_terms"',
        b'"evidence"',
        b"session_1",
        b"D1:1",
    ):
        assert forbidden not in canonical
    assert rig.state.clean_state is not None
    expected_scope = hashlib.sha256(SANDBOX_SCOPE.encode()).hexdigest()
    assert {item.scope_identity_sha256 for item in rig.state.clean_state.scopes} == {expected_scope}

    assert rig.trace.events == _expected_adapter_trace(case_alias)
    assert report["managed_run"]["trace"] == _expected_managed_trace(case_alias)
    assert rig.trace.events.index("canonical_source.seal") < rig.trace.events.index(
        f"retrieve:{INFINITY_BACKEND}:{case_alias}"
    )
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
    _assert_no_private_material_escaped(rig, report)
    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        _run(rig)


def test_dirty_prestate_never_reaches_a_public_verdict() -> None:
    rig = _rig("dirty")
    rig.state.seed_dirty()
    with pytest.raises(RuntimeError, match="dirty prestate"):
        _run(rig)
    assert "canonical_source.seal" not in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events


def test_candidate_source_mismatch_never_reaches_a_public_verdict() -> None:
    rig = _rig("candidate-mismatch", answer_text="black coffee")
    with pytest.raises(GoldBlindContractError, match="Trusted judge evaluator failed") as raised:
        _run(rig)
    assert not getattr(raised.value, "__notes__", ())
    assert "delete.seal" in rig.trace.events
    assert "canonical_source.seal" in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events


def test_nonzero_second_delete_pass_never_reaches_a_public_verdict() -> None:
    rig = _rig("pass2-nonzero")
    rig.state.repopulate_on_second_pass = True
    with pytest.raises(AssertionError):
        _run(rig)
    assert "canonical_source.seal" in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events


def test_wrong_scope_delete_cannot_remove_the_ingested_source() -> None:
    public_case = _fixture_case()
    corpus_id, _thread_id = _managed_corpus_identity(public_case)
    state = SandboxBackendState.create()
    state.ingest(INFINITY_BACKEND, corpus_id, _managed_corpus_record(public_case))
    observed = state.delete(
        INFINITY_BACKEND,
        "wrong-scope",
        corpus_id,
        1,
    )
    assert observed.deleted_count == 0
    assert state.source(INFINITY_BACKEND, corpus_id).text == ("Alice bought green tea after work.")
    assert (INFINITY_BACKEND, SANDBOX_SCOPE, corpus_id) in state.stores


@pytest.mark.parametrize(
    "bind_case_transform",
    (
        lambda case: replace(case, question="substituted private question"),
        lambda case: replace(
            case,
            expected_terms=("substituted gold",),
            metadata={
                **case.metadata,
                "_evaluator_ground_truth": "substituted gold",
                "answer_terms": ("substituted gold",),
            },
        ),
        lambda case: replace(
            case,
            metadata={
                **case.metadata,
                "evidence": ["D9:9"],
                "evidence_terms": ("D9:9",),
            },
        ),
    ),
    ids=("question", "gold", "evidence"),
)
def test_substituted_private_material_burns_admission_before_provider_or_verdict(
    bind_case_transform: Callable[[PublicBenchmarkCase], PublicBenchmarkCase],
) -> None:
    rig = _rig("substituted-authority", bind_case_transform=bind_case_transform)

    with pytest.raises(ManagedRunError, match="judge case material differs"):
        _run(rig)

    assert not rig.trace.events
    assert not rig.execution.provider_calls
    assert not rig.execution.observed_queries
    assert rig.state.clean_state is None
    assert not rig.state.stores
    with pytest.raises(ManagedRunError, match="unavailable or consumed"):
        _run(rig)


def test_hostile_answerer_observes_query_and_source_but_no_gold_or_private_ids() -> None:
    observed: list[tuple[str, str]] = []

    def hostile_answerer(question: str, source: str) -> str:
        observed.append((question, source))
        return locomo_answer_from_source(question, source)

    rig = _rig("hostile-answerer", answer_from_source=hostile_answerer)
    report = public_managed_run(_run(rig))

    assert len(observed) == 2
    observed_text = json.dumps(observed, sort_keys=True)
    for forbidden in (
        rig.public_case.case_id,
        "sandbox-locomo-1",
        "session_1",
        "D1:1",
        "_evaluator_ground_truth",
        "expected_terms",
        "evidence_terms",
    ):
        assert forbidden not in observed_text
    assert tuple(query.case_id for query in rig.execution.observed_queries) == (
        _case_alias(rig.public_case),
        _case_alias(rig.public_case),
    )
    _assert_no_private_material_escaped(rig, report)


def _rig(
    name: str,
    *,
    answer_text: str | None = None,
    answer_from_source: Callable[[str, str], str] | None = None,
    bind_case_transform: Callable[[PublicBenchmarkCase], PublicBenchmarkCase] | None = None,
) -> _Rig:
    assert answer_text is None or answer_from_source is None
    public_case = _fixture_case()
    dataset_bytes = _FIXTURE.read_bytes()
    run_id = f"managed-locomo-sandbox-{name}"
    corpus_id, _thread_id = _managed_corpus_identity(public_case)
    profile = resolve_full_comparison_profile(PROFILE_LOCOMO_TOP_50)
    assert profile is not None
    route = _provider_route(name)
    mem0_target = mem0_runtime_target_identity_sha256(
        f"https://mem0.example.test/managed-locomo-{name}"
    )
    runtime_probe_nonce_sha256 = hashlib.sha256(RUNTIME_NONCE.encode()).hexdigest()
    backend_targets = (
        FullComparisonBackendTarget(
            INFINITY_BACKEND,
            hashlib.sha256(name.encode()).hexdigest(),
        ),
        FullComparisonBackendTarget(MEM0_BACKEND, mem0_target),
    )
    admission = build_verified_managed_run_plan(
        run_id=run_id,
        run_nonce_commitment_sha256=hashlib.sha256(f"{name}:run-nonce".encode()).hexdigest(),
        runtime_probe_nonce_sha256=runtime_probe_nonce_sha256,
        profile=profile,
        dataset_bytes=dataset_bytes,
        backend_targets=backend_targets,
        provider_route=route,
        scope="canary",
        selected_case_ids=(public_case.case_id,),
    )
    assert repr(admission) == "VerifiedManagedRunPlan(<sealed>)"
    trace = SandboxTrace.create()
    state = SandboxBackendState.create()
    assert state.scenario.corpus_ids == (corpus_id,)
    runtime = build_runtime_ports(
        trace,
        state,
        run_id=run_id,
        probe_nonce_sha256=runtime_probe_nonce_sha256,
        target_identity_sha256=mem0_target,
    )
    judge = SandboxJudgePort(
        trace,
        state=state,
        provider_route=route,
        bind_case_transform=bind_case_transform,
        **(
            {"answer_from_source": answer_from_source or (lambda _question, _source: answer_text)}
            if answer_text is not None or answer_from_source is not None
            else {}
        ),
    )
    execution = SandboxExecutionPort(trace, candidate_channel=judge.candidate_channel)
    policy = SandboxPolicyPort(trace, state)
    assembler = ManagedFullComparisonAssembler(
        adapter_id="managed-locomo-sandbox-assembler",
        implementation_sha256=implementation_sha256("assembler"),
        reset_port=runtime.reset,
        attestation_port=runtime.attestation,
        ingest_port=runtime.ingest,
        clock=runtime.clock,
    )
    return _Rig(
        admission,
        public_case,
        trace,
        state,
        runtime,
        execution,
        judge,
        policy,
        assembler,
    )


def _run(rig: _Rig):
    return run_managed_comparison(
        rig.admission,
        reset_port=rig.runtime.reset,
        attestation_port=rig.runtime.attestation,
        ingest_port=rig.runtime.ingest,
        clock=rig.runtime.clock,
        execution_port=rig.execution,
        judge_port=rig.judge,
        policy_port=rig.policy,
        assembler=rig.assembler,
    )


def _fixture_case() -> PublicBenchmarkCase:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert type(payload) is list and len(payload) == 1 and type(payload[0]) is dict
    public_cases = _load_memory_comparison_cases(
        _FIXTURE,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )
    assert len(public_cases) == 1
    return public_cases[0]


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


def _case_alias(case: PublicBenchmarkCase) -> str:
    material = f"{case.benchmark}\0case\0{case.case_id}".encode()
    return f"{case.benchmark}-case-{hashlib.sha256(material).hexdigest()}"


def _assert_no_private_material_escaped(rig: _Rig, report: dict[str, object]) -> None:
    public_spy = json.dumps(
        {
            "report": report,
            "trace": rig.trace.events,
            "provider_calls": [
                [call.case_id, call.backend_role, call.stage]
                for call in rig.execution.provider_calls
            ],
            "ingest_receipts": [
                [receipt.corpus_id, receipt.source_sha256]
                for receipt in rig.runtime.ingest.receipts
            ],
            "retrieval_ids": rig.execution.retrieval_item_ids,
        },
        sort_keys=True,
    )
    for forbidden in (
        rig.public_case.case_id,
        "sandbox-locomo-1",
        rig.public_case.question,
        "session_1",
        "D1:1",
        "_evaluator_ground_truth",
        "green tea",
    ):
        assert forbidden not in public_spy


def _expected_adapter_trace(case_id: str) -> list[str]:
    return [
        "reset",
        "attest",
        f"ingest:{INFINITY_BACKEND}",
        f"ingest:{MEM0_BACKEND}",
        "canonical_source.issue",
        "canonical_source.seal",
        f"retrieve:{INFINITY_BACKEND}:{case_id}",
        f"answer:{INFINITY_BACKEND}:{case_id}",
        f"judge:{INFINITY_BACKEND}:{case_id}",
        f"retrieve:{MEM0_BACKEND}:{case_id}",
        f"answer:{MEM0_BACKEND}:{case_id}",
        f"judge:{MEM0_BACKEND}:{case_id}",
        "execution.seal",
        f"delete:{INFINITY_BACKEND}:1",
        f"delete:{MEM0_BACKEND}:1",
        f"delete:{INFINITY_BACKEND}:2",
        f"delete:{MEM0_BACKEND}:2",
        "delete.seal",
        "policy.aggregate",
    ]


def _expected_managed_trace(case_id: str) -> list[str]:
    corpus_id = _managed_corpus_identity(_fixture_case())[0]
    return [
        "bindings.create",
        "issuer.create",
        "reset.complete",
        "attestation.live",
        f"ingest:{INFINITY_BACKEND}:{corpus_id}",
        f"ingest:{MEM0_BACKEND}:{corpus_id}",
        "canonical_source.seal",
        f"retrieve:{INFINITY_BACKEND}:{case_id}",
        f"answer:{INFINITY_BACKEND}:{case_id}",
        f"judge:{INFINITY_BACKEND}:{case_id}",
        f"retrieve:{MEM0_BACKEND}:{case_id}",
        f"answer:{MEM0_BACKEND}:{case_id}",
        f"judge:{MEM0_BACKEND}:{case_id}",
        "execution.seal",
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
