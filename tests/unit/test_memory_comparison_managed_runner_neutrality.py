from __future__ import annotations

import ast
from pathlib import Path

import infinity_context_server.memory_comparison_managed_llm_execution as execution_subject
import pytest
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    gold_blind_evidence_identity,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
)
from infinity_context_server.memory_comparison_managed_http_runner_adapter import (
    ManagedHttpRunnerAdapterError,
)
from infinity_context_server.memory_comparison_managed_llm_execution import (
    ManagedLlmExecutionError,
    create_managed_comparison_execution_ports,
)
from infinity_context_server.memory_comparison_managed_llm_execution_dispatch import (
    ManagedRetrievalDispatchPort,
)
from infinity_context_server.memory_comparison_managed_retrieval_port import (
    ManagedRetrievalAuthority,
    ManagedRetrievalResult,
    _issue_managed_retrieval_authority,
    _validate_managed_retrieval_authority,
)
from infinity_context_server.memory_comparison_managed_run_contract import _thaw_json
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from test_memory_comparison_managed_llm_execution import _scenario

_ADAPTER_ID = "provider-neutral-test-retrieval-v1"
_IMPLEMENTATION_SHA256 = "7" * 64


class _NeutralRetrieval:
    def __init__(self, binding: ManagedRunnerCompositionBinding) -> None:
        self.composition_binding = binding
        self.authority_calls = 0
        self.retrieve_calls = 0

    def authority_for(
        self, *, backend_role: str, target_identity_sha256: str
    ) -> ManagedRetrievalAuthority:
        self.authority_calls += 1
        return _issue_managed_retrieval_authority(
            self.composition_binding,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
        )

    def retrieve(self, *, authority, case, query) -> ManagedRetrievalResult:
        self.retrieve_calls += 1
        backend_role, target_identity = _validate_managed_retrieval_authority(
            authority,
            composition_binding=self.composition_binding,
        )
        assert case.case_id == query.case_id
        evidence = ()
        return ManagedRetrievalResult(
            evidence=evidence,
            retrieval_identity=gold_blind_evidence_identity(evidence),
            metadata={
                "adapter_id": _ADAPTER_ID,
                "backend_role": backend_role,
                "target_identity_sha256": target_identity,
                "retrieval_policy": NEUTRAL_COMPARISON_RETRIEVAL_POLICY.telemetry(),
                "gold_fields_forwarded": False,
                "retries": 0,
            },
        )


class _NeutralEvidence:
    def __init__(self, binding: ManagedRunnerCompositionBinding) -> None:
        self.composition_binding = binding
        self.consume_calls = 0
        self.seal_calls = 0

    def consume_ready_evidence(self, **values: object) -> None:
        assert values["composition_binding"] is self.composition_binding
        self.consume_calls += 1

    def seal_execution_validation(self, **_values: object) -> object:
        self.seal_calls += 1
        raise AssertionError("seal is outside this retrieval-only test")


def _clone_binding(binding: ManagedRunnerCompositionBinding) -> ManagedRunnerCompositionBinding:
    return ManagedRunnerCompositionBinding(
        run_id=binding.run_id,
        profile=binding.profile,
        binding_commitment_sha256=binding.binding_commitment_sha256,
        deadline=binding.deadline,
        backend_targets=binding.backend_targets,
        retrieval_top_k=binding.retrieval_top_k,
        answer_cutoff=binding.answer_cutoff,
    )


def test_high_level_execution_modules_have_no_http_or_mem0_v5_imports() -> None:
    module_root = Path(execution_subject.__file__).resolve().parent
    forbidden: list[tuple[str, str]] = []
    for path in sorted(module_root.glob("memory_comparison_managed_llm_execution*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.append(node.module)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        forbidden.extend(
            (path.name, module)
            for module in imports
            if "memory_comparison_managed_http" in module
            or "memory_comparison_managed_mem0_v5" in module
        )

    assert forbidden == []


def test_non_http_retrieval_authority_runs_through_execution_coordinator() -> None:
    scenario = _scenario()
    retrieval = _NeutralRetrieval(scenario.runner_binding)
    evidence = _NeutralEvidence(scenario.runner_binding)
    ports = create_managed_comparison_execution_ports(
        composition_binding=scenario.runner_binding,
        retrieval=retrieval,
        execution_evidence=evidence,
        retrieval_adapter_id=_ADAPTER_ID,
        retrieval_implementation_sha256=_IMPLEMENTATION_SHA256,
        provider=scenario.provider,
        limits=scenario.limits,
        provider_route=scenario.route,
    )
    ports.judge_port.bind_cases(
        bindings=scenario.bindings,
        cases=(scenario.source,),
        case_aliases=(scenario.managed_case.case_id,),
    )
    target = scenario.bindings.backend_targets[0]

    receipt = ports.execution_port.retrieve(
        bindings=scenario.bindings,
        backend_role=target.backend_role,
        target_identity_sha256=target.target_identity_sha256,
        case=scenario.managed_case,
        query=scenario.query,
    )

    assert repr(receipt) == "ManagedExecutionReceipt(<redacted>)"
    assert retrieval.authority_calls == retrieval.retrieve_calls == 1
    assert evidence.consume_calls == 1
    assert evidence.seal_calls == 0
    assert scenario.http_wire == []


def test_foreign_composition_binding_fails_before_retrieval_or_evidence_io() -> None:
    scenario = _scenario()
    foreign = _clone_binding(scenario.runner_binding)
    retrieval = _NeutralRetrieval(scenario.runner_binding)
    evidence = _NeutralEvidence(scenario.runner_binding)
    target = scenario.bindings.backend_targets[0]
    authority = retrieval.authority_for(
        backend_role=target.backend_role,
        target_identity_sha256=target.target_identity_sha256,
    )

    with pytest.raises(ManagedLlmExecutionError, match="managed_retrieval_dispatch_invalid"):
        ManagedRetrievalDispatchPort(
            composition_binding=foreign,
            retrieval=retrieval,
            authority=authority,
            run_id=scenario.bindings.run_id,
            backend_role=target.backend_role,
            case=scenario.managed_case,
            query=scenario.query,
            expected_case_id=f"{scenario.managed_case.case_id}:{target.backend_role}",
        )
    with pytest.raises(ManagedLlmExecutionError, match="managed_execution_composition_invalid"):
        create_managed_comparison_execution_ports(
            composition_binding=foreign,
            retrieval=retrieval,
            execution_evidence=evidence,
            retrieval_adapter_id=_ADAPTER_ID,
            retrieval_implementation_sha256=_IMPLEMENTATION_SHA256,
            provider=scenario.provider,
            limits=scenario.limits,
            provider_route=scenario.route,
        )

    assert retrieval.retrieve_calls == evidence.consume_calls == evidence.seal_calls == 0
    assert scenario.http_wire == []


def test_legacy_http_adapter_preserves_exact_neutral_result_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario()
    scenario.prepare_lifecycle()
    target = scenario.bindings.backend_targets[0]
    values = {
        "run_id": scenario.bindings.run_id,
        "backend_role": target.backend_role,
        "target_identity_sha256": target.target_identity_sha256,
        "case": scenario.managed_case,
        "query": scenario.query,
    }
    legacy = scenario.http.retrieve(**values)
    monkeypatch.setattr(
        ManagedComparisonHttpExecutionAdapter,
        "retrieve",
        lambda _self, **_values: legacy,
    )
    authority = scenario.runner.authority_for(
        backend_role=target.backend_role,
        target_identity_sha256=target.target_identity_sha256,
    )
    neutral = scenario.runner.retrieve(
        authority=authority,
        case=scenario.managed_case,
        query=scenario.query,
    )

    assert neutral.evidence == legacy.evidence
    assert neutral.retrieval_identity == legacy.retrieval_identity
    assert _thaw_json(neutral.metadata) == _thaw_json(legacy.metadata)


def test_evidence_consumption_and_execution_seal_are_one_shot() -> None:
    scenario = _scenario()
    material = scenario.bind()
    scenario.prepare_lifecycle()
    executions = scenario.run_all(material)
    values = {
        "bindings": scenario.bindings,
        "case_manifest": scenario.manifest,
        "executions": executions,
        "case_manifest_sha256": execution_case_manifest_sha256(scenario.manifest),
        "case_material_sha256": material,
    }

    scenario.ports.judge_port.seal_execution(**values)

    with pytest.raises(ManagedLlmExecutionError):
        scenario.ports.judge_port.seal_execution(**values)
    with pytest.raises(ManagedHttpRunnerAdapterError, match="evidence_invalid"):
        scenario.runner.consume_ready_evidence(
            composition_binding=scenario.runner_binding,
            bindings=scenario.bindings,
            cases=(scenario.managed_case,),
        )
