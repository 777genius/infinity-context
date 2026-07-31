from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

import pytest
from infinity_context_server import (
    memory_comparison_managed_composite_assembler as assembler_module,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonEvidenceIssuer,
    FullComparisonRunBindings,
    _component_state,
    create_full_comparison_evidence_issuer,
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
    FULL_COMPARISON_SCOPE_FULL,
)
from infinity_context_server.memory_comparison_gold_blind import (
    build_gold_blind_contract,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindExpectedDispatchCase,
    JudgeRunKey,
    VerifiedGoldBlindExecutionValidation,
    create_gold_blind_run_dispatch_ledger,
    create_trusted_gold_blind_evaluator,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    verify_gold_blind_execution,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    VerifiedManagedCompositionAttestation,
    public_managed_composition_attestation,
)
from infinity_context_server.memory_comparison_managed_composite_assembler import (
    ManagedCompositeAssemblerError,
    ManagedFullComparisonAssembler,
)
from infinity_context_server.memory_comparison_managed_run import _validate_ports
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedCompositeAssemblerPort,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from test_memory_comparison_full_binding_replay import (
    _Answerer,
    _gold_validation,
    _judge_callback,
    _Retriever,
)
from test_memory_comparison_full_execution_validation import (
    _identity as _execution_identity,
)
from test_memory_comparison_full_execution_validation import _inputs as _execution_inputs
from test_memory_comparison_full_execution_validation import _proof as _execution_proof
from test_memory_comparison_full_run_component_wiring import _policy_validation
from test_memory_comparison_managed_attestation import _bindings as _managed_bindings
from test_memory_comparison_managed_attestation import _issue as _managed_issue
from test_memory_comparison_managed_attestation import (
    _runtime_validation as _managed_runtime_validation,
)


class _AssemblerShape(Protocol):
    @property
    def adapter_id(self) -> str: ...
    @property
    def implementation_sha256(self) -> str: ...
    def assemble_components(self, **kwargs: object) -> tuple[object, ...]: ...
    def seal_verdict(self, **kwargs: object) -> object: ...
    def public_verdict(self, verdict: object) -> object: ...


@dataclass(frozen=True, slots=True)
class _Ready:
    assembler: ManagedFullComparisonAssembler
    bindings: FullComparisonRunBindings
    issuer: FullComparisonEvidenceIssuer
    managed: VerifiedManagedCompositionAttestation
    execution: object
    gold: VerifiedGoldBlindExecutionValidation
    policy: object
    case_manifest_sha256: str
    ports: tuple[object, ...]


def _inputs_for_scope(scope: str):
    inputs = _execution_inputs()
    old = inputs["bindings"]
    base = _managed_bindings(
        run_id=old.run_id,
        selection=old.selection_fingerprint_sha256,
    )
    profile = resolve_full_comparison_profile(base.profile_id)
    assert profile is not None
    bindings = create_full_comparison_run_bindings(
        run_id=base.run_id,
        run_nonce_commitment_sha256=base.run_nonce_commitment_sha256,
        runtime_probe_nonce_sha256=base.runtime_probe_nonce_sha256,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256=base.dataset_sha256,
        selection_fingerprint_sha256=base.selection_fingerprint_sha256,
        backend_targets=base.backend_targets,
        scope=scope,
    )
    inputs["bindings"] = bindings
    inputs["provider_calls"] = tuple(
        replace(call, comparison_commitment_sha256=bindings.binding_commitment_sha256)
        for call in inputs["provider_calls"]
    )
    runtime = _managed_runtime_validation(
        run_id=bindings.run_id,
        target=bindings.backend_targets[1].target_identity_sha256,
    )
    managed, _, _, _, ports = _managed_issue(
        bindings=bindings,
        validation=runtime,
        route=inputs["required_route"],
    )
    return inputs, managed, ports


def _gold_lanes(
    bindings: FullComparisonRunBindings,
    *,
    lane_count: int,
) -> VerifiedGoldBlindExecutionValidation:
    expected = tuple(
        GoldBlindExpectedDispatchCase(
            case_id=f"managed-lane-{index}",
            retrieval_backend_id=f"retrieval-{index}",
            answer_backend_id=f"answer-{index}",
            judge_backend_id=f"judge-{index}",
        )
        for index in range(lane_count)
    )
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=bindings.run_id,
        comparison_binding_commitment_sha256=bindings.binding_commitment_sha256,
        expected_cases=expected,
    )
    for lane in expected:
        case = PublicBenchmarkCase(
            benchmark="locomo",
            case_id=lane.case_id,
            question="What happened?",
            expected_terms=("private-answer",),
            metadata={
                "_evaluator_ground_truth": {"answer": "private-answer"},
                "reference_date": "2 January 2023",
            },
        )
        key = JudgeRunKey.issue(run_id=bindings.run_id, case_id=lane.case_id)
        contract = build_gold_blind_contract(
            case,
            run_id=bindings.run_id,
            judge_key=key,
            dispatch_ledger=ledger,
        )
        evidence = dispatch_retrieval(
            _Retriever(),
            contract.retrieval_request,
            backend_id=lane.retrieval_backend_id,
            dispatch_ledger=ledger,
            run_id=bindings.run_id,
            top_k=5,
        )
        dispatch_answer(
            _Answerer(),
            contract.answer_request(evidence),
            backend_id=lane.answer_backend_id,
            dispatch_ledger=ledger,
            run_id=bindings.run_id,
            case_id=lane.case_id,
        )
        dispatch_judge(
            create_trusted_gold_blind_evaluator(_judge_callback),
            contract.judge_channel,
            backend_id=lane.judge_backend_id,
            dispatch_ledger=ledger,
            key=key,
            run_id=bindings.run_id,
            case_id=lane.case_id,
        )
    return verify_gold_blind_execution(ledger)


def _ready(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scope: str = FULL_COMPARISON_SCOPE_FULL,
) -> _Ready:
    inputs, managed, ports = _inputs_for_scope(scope)
    bindings = inputs["bindings"]
    managed_report = public_managed_composition_attestation(
        managed,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    policy = _policy_validation(
        monkeypatch,
        bindings,
        str(managed_report["composition_attestation_sha256"]),
    )
    _, execution = _execution_proof(inputs)
    case_manifest_sha256 = _execution_identity(inputs)["case_manifest_sha256"]
    assembler = ManagedFullComparisonAssembler(
        adapter_id="managed-composite-assembler-v1",
        implementation_sha256="7" * 64,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    return _Ready(
        assembler,
        bindings,
        create_full_comparison_evidence_issuer(bindings),
        managed,
        execution,
        _gold_lanes(bindings, lane_count=2),
        policy,
        case_manifest_sha256,
        ports,
    )


def _assemble(ready: _Ready, *, gold: object | None = None):
    return ready.assembler.assemble_components(
        bindings=ready.bindings,
        issuer=ready.issuer,
        managed_attestation=ready.managed,
        execution_validation=ready.execution,
        gold_blind_validation=ready.gold if gold is None else gold,
        policy_validation=ready.policy,
        case_manifest_sha256=ready.case_manifest_sha256,
    )


def test_structural_managed_port_and_successful_nine_slot_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch)
    structural: _AssemblerShape = ready.assembler
    managed_port: ManagedCompositeAssemblerPort = ready.assembler
    assert structural is managed_port
    assert ready.assembler.adapter_id == "managed-composite-assembler-v1"
    assert ready.assembler.implementation_sha256 == "7" * 64
    _validate_ports(_ExecutionPortStub(), _PolicyPortStub(), ready.assembler)

    components = _assemble(ready)
    assert tuple(_component_state(item).component_kind for item in components) == (
        FULL_COMPARISON_COMPONENT_KINDS
    )
    verdict = ready.assembler.seal_verdict(
        bindings=ready.bindings,
        issuer=ready.issuer,
        components=components,
    )
    first = ready.assembler.public_verdict(verdict)
    second = ready.assembler.public_verdict(verdict)
    assert first == second
    assert first["publishable"] is True
    assert {item["status"] for item in first["components"]} == {"verified"}


def test_case_manifest_mismatch_is_preflight_only_and_correct_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch)
    with pytest.raises(ManagedCompositeAssemblerError, match="preflight"):
        ready.assembler.assemble_components(
            bindings=ready.bindings,
            issuer=ready.issuer,
            managed_attestation=ready.managed,
            execution_validation=ready.execution,
            gold_blind_validation=ready.gold,
            policy_validation=ready.policy,
            case_manifest_sha256="f" * 64,
        )
    assert len(_assemble(ready)) == 9


def test_gold_lane_count_mismatch_does_not_consume_any_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch)
    one_lane = _gold_validation(ready.bindings)
    with pytest.raises(ManagedCompositeAssemblerError, match="preflight"):
        _assemble(ready, gold=one_lane)
    assert len(_assemble(ready)) == 9


def test_public_mapping_is_never_admitted_and_real_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch)
    with pytest.raises(ManagedCompositeAssemblerError, match="preflight"):
        ready.assembler.assemble_components(
            bindings=ready.bindings,
            issuer=ready.issuer,
            managed_attestation=ready.managed,
            execution_validation={"component_only": True},
            gold_blind_validation=ready.gold,
            policy_validation=ready.policy,
            case_manifest_sha256=ready.case_manifest_sha256,
        )
    assert len(_assemble(ready)) == 9


def test_assembly_and_verdict_are_one_shot_and_exact_tuple_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch)
    components = _assemble(ready)
    with pytest.raises(ManagedCompositeAssemblerError, match="already reserved"):
        _assemble(ready)
    copied = tuple(list(components))
    with pytest.raises(ManagedCompositeAssemblerError, match="not sealable"):
        ready.assembler.seal_verdict(
            bindings=ready.bindings,
            issuer=ready.issuer,
            components=copied,
        )
    verdict = ready.assembler.seal_verdict(
        bindings=ready.bindings,
        issuer=ready.issuer,
        components=components,
    )
    with pytest.raises(ManagedCompositeAssemblerError, match="not sealable"):
        ready.assembler.seal_verdict(
            bindings=ready.bindings,
            issuer=ready.issuer,
            components=components,
        )
    assert ready.assembler.public_verdict(verdict)["publishable"] is True


def test_post_consume_failure_is_terminal_without_recovery_fabrication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch)
    original = assembler_module.issue_execution_component_evidence_set

    def fail_execution(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected post-runtime failure")

    monkeypatch.setattr(
        assembler_module,
        "issue_execution_component_evidence_set",
        fail_execution,
    )
    with pytest.raises(ManagedCompositeAssemblerError, match="assembly failed"):
        _assemble(ready)
    monkeypatch.setattr(
        assembler_module,
        "issue_execution_component_evidence_set",
        original,
    )
    with pytest.raises(ManagedCompositeAssemblerError, match="already reserved"):
        _assemble(ready)


def test_canary_verdict_is_verified_but_never_publishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready(monkeypatch, scope=FULL_COMPARISON_SCOPE_CANARY)
    components = _assemble(ready)
    verdict = ready.assembler.seal_verdict(
        bindings=ready.bindings,
        issuer=ready.issuer,
        components=components,
    )
    report = ready.assembler.public_verdict(verdict)
    assert report["claim_scope"] == "diagnostic_canary"
    assert report["eligible"] is True
    assert report["publishable"] is False


class _ExecutionPortStub:
    adapter_id = "execution-stub"
    implementation_sha256 = "8" * 64

    def retrieve(self): ...
    def answer(self): ...
    def judge(self): ...
    def seal_execution(self): ...


class _PolicyPortStub:
    adapter_id = "policy-stub"
    implementation_sha256 = "9" * 64

    def seal_canonical_source(self): ...
    def terminal_delete(self): ...
    def seal_terminal_delete(self): ...
    def aggregate_policy(self): ...
