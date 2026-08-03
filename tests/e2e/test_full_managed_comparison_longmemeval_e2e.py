from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_case_loader import (
    load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    public_full_execution_validation_report,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LONGMEMEVAL_TOP_50,
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
    LOCOMO_INGEST_RICH_DOCUMENTS,
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
    SandboxBackendState,
    SandboxScenario,
    SandboxTrace,
    implementation_sha256,
)
from managed_comparison_sandbox_execution import (
    AnswerFromSource,
    SandboxExecutionPort,
    SandboxJudgePort,
)
from managed_comparison_sandbox_policy import SandboxPolicyPort
from managed_comparison_sandbox_runtime import SandboxRuntimePorts, build_runtime_ports

_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "memory_comparison"
    / "managed-longmemeval-sandbox.json"
)


@dataclass(frozen=True, slots=True)
class _Rig:
    admission: VerifiedManagedRunPlan
    public_cases: tuple[PublicBenchmarkCase, ...]
    trace: SandboxTrace
    state: SandboxBackendState
    runtime: SandboxRuntimePorts
    execution: SandboxExecutionPort
    judge: SandboxJudgePort
    policy: SandboxPolicyPort
    assembler: ManagedFullComparisonAssembler


def test_managed_longmemeval_canary_verifies_all_nine_slots_for_two_cases() -> None:
    rig = _rig("success")
    outcome = _run(rig)
    report = public_managed_run(outcome)

    assert report["scope"] == "canary"
    assert report["publishable"] is False
    assert [item["component_kind"] for item in report["components"]] == list(
        FULL_COMPARISON_COMPONENT_KINDS
    )
    assert {item["status"] for item in report["components"]} == {"verified"}
    assert report["managed_run"]["case_count"] == 2
    assert report["managed_run"]["component_count"] == 9
    assert report["managed_run"]["terminal_delete_complete"] is True
    assert (
        report["commitments"]["dataset_sha256"] == hashlib.sha256(_FIXTURE.read_bytes()).hexdigest()
    )
    assert report["commitments"]["selection_sha256"] == selected_case_fingerprint(rig.public_cases)

    assert rig.judge.case_manifest is not None
    assert all(item.official_turn_count == 0 for item in rig.judge.case_manifest)
    assert tuple(item.case_id for item in rig.judge.case_manifest) == tuple(
        _case_alias(case) for case in rig.public_cases
    )
    assert tuple(item.session_roles for item in rig.judge.case_manifest) == tuple(
        tuple(f"memory-{index:04d}" for index in range(1, len(case.conversations) + 1))
        for case in rig.public_cases
    )
    assert tuple(item.session_aliases for item in rig.judge.case_manifest) == tuple(
        tuple(f"session-{index:04d}" for index in range(1, len(case.conversations) + 1))
        for case in rig.public_cases
    )
    assert tuple(
        (call.case_id, call.backend_role, call.stage) for call in rig.execution.provider_calls
    ) == tuple(
        (_case_alias(case), backend, stage)
        for case in rig.public_cases
        for backend in (INFINITY_BACKEND, MEM0_BACKEND)
        for stage in ("answerer", "judge")
    )
    assert len(rig.execution.retrieval_item_ids) == 4
    assert all(
        re.fullmatch(r"evidence-[0-9a-f]{64}", item_id)
        for item_id in rig.execution.retrieval_item_ids
    )
    assert all(
        case.case_id not in item_id
        for item_id in rig.execution.retrieval_item_ids
        for case in rig.public_cases
    )
    gold = verified_gold_blind_execution_report(rig.judge.gold_validation)
    assert gold["expected_case_count"] == 4
    assert gold["retrieval_dispatch_count"] == 4
    assert gold["answer_dispatch_count"] == 4
    assert gold["judge_dispatch_count"] == 4

    execution = public_full_execution_validation_report(rig.judge.execution_validation)
    transport = execution["official_transport_coverage"]
    assert transport == {
        "required": False,
        "required_turn_count": 0,
        "verified_turn_count": 0,
        "corpus_count": 0,
        "live_verifier": False,
        "evidence_commitment_sha256": hashlib.sha256(b"[]").hexdigest(),
    }
    assert execution["clean_state_coverage"]["required_scope_count"] == 4
    assert execution["clean_state_coverage"]["verified_scope_count"] == 4
    assert rig.state.clean_state is not None
    assert {item.scope_identity_sha256 for item in rig.state.clean_state.scopes} == {
        hashlib.sha256(rig.state.scenario.scope_id.encode()).hexdigest()
    }
    assert tuple(
        (
            item.backend_role,
            item.corpus_identity_sha256,
            item.scope_identity_sha256,
        )
        for item in rig.state.clean_state.scopes
    ) == tuple(
        (
            backend,
            hashlib.sha256(corpus_id.encode()).hexdigest(),
            hashlib.sha256(rig.state.scenario.corpus_scope(corpus_id).encode()).hexdigest(),
        )
        for backend in (INFINITY_BACKEND, MEM0_BACKEND)
        for corpus_id in rig.state.scenario.corpus_ids
    )

    first, second = rig.public_cases
    assert {case.metadata["question_type"] for case in rig.public_cases} == {
        "multi-session",
        "single-session-user",
    }
    assert [item.session_external_id for item in first.conversations] == [
        "session-0002",
        "session-0004",
        "session-0001",
        "session-0003",
    ]
    assert first.metadata["answer_session_aliases"] == [
        "session-0001",
        "session-0003",
    ]
    assert [item.session_external_id for item in second.conversations] == [
        "session-0003",
        "session-0001",
        "session-0002",
    ]
    assert second.metadata["answer_session_aliases"] == ["session-0002"]

    receipt_hashes = {
        (item.backend_role, item.corpus_id): item.source_sha256
        for item in rig.runtime.ingest.receipts
    }
    for raw, case in zip(_fixture_rows(), rig.public_cases, strict=True):
        corpus_id, _thread_id = _managed_corpus_identity(case)
        private_ids = raw["haystack_session_ids"]
        assert isinstance(private_ids, list)
        canonical = _ingested_canonical_bytes(case)
        canonical_payload = json.loads(canonical)
        assert set(canonical_payload) == {
            "schema_version",
            "benchmark",
            "corpus_id",
            "thread_id",
            "memories",
            "documents",
            "conversations",
        }
        assert canonical_payload["corpus_id"] == corpus_id
        assert all(str(item).encode() not in canonical for item in private_ids)
        assert case.case_id.encode() not in canonical
        for forbidden in (
            b'"question"',
            b'"question_id"',
            b'"answer"',
            b'"answer_session_ids"',
            b'"haystack_session_ids"',
        ):
            assert forbidden not in canonical
        expected_hash = hashlib.sha256(canonical).hexdigest()
        assert receipt_hashes[(INFINITY_BACKEND, corpus_id)] == expected_hash
        assert receipt_hashes[(MEM0_BACKEND, corpus_id)] == expected_hash

    assert not rig.state.stores
    assert tuple(item.deleted_count for item in rig.state.delete_observations.values()) == (
        2,
        2,
        0,
        0,
    )
    _assert_no_private_material_escaped(rig, report)


def test_scope_delete_never_counts_or_removes_foreign_scope_data() -> None:
    _fixture_rows()
    public_cases = load_memory_comparison_cases(
        _FIXTURE,
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )
    corpus_ids = tuple(_managed_corpus_identity(case)[0] for case in public_cases)
    scenario = SandboxScenario(
        "managed-longmemeval-sandbox",
        "longmemeval",
        "managed-longmemeval-sandbox-scope",
        corpus_ids,
    )
    state = SandboxBackendState.create(scenario)
    corpus_id = corpus_ids[0]
    source = state.ingest(
        INFINITY_BACKEND,
        corpus_id,
        _managed_corpus_record(public_cases[0]),
    )
    foreign_key = (INFINITY_BACKEND, "foreign-scope", corpus_id)
    state.stores[foreign_key] = source

    first = state.delete_scope(INFINITY_BACKEND, scenario.scope_id, 1)
    second = state.delete_scope(INFINITY_BACKEND, scenario.scope_id, 2)

    assert (first.deleted_count, first.remaining_count) == (1, 0)
    assert (second.deleted_count, second.remaining_count) == (0, 0)
    assert foreign_key in state.stores
    assert (INFINITY_BACKEND, scenario.scope_id, corpus_id) not in state.stores


def test_adversarial_answer_failure_never_reaches_a_public_verdict() -> None:
    rig = _rig(
        "wrong-answer",
        answer_from_source=lambda _question, _source: "purple locker",
    )

    with pytest.raises(
        GoldBlindContractError,
        match="Trusted judge evaluator failed",
    ) as exc_info:
        _run(rig)

    assert not getattr(exc_info.value, "__notes__", ())
    assert "delete.seal" in rig.trace.events
    assert rig.judge.gold_validation is None
    assert rig.judge.execution_validation is None
    assert "execution.seal" not in rig.trace.events
    assert "canonical_source.seal" in rig.trace.events
    assert "policy.aggregate" not in rig.trace.events
    assert "components.issue" not in rig.trace.events
    assert "verdict.seal" not in rig.trace.events
    assert "verdict.public" not in rig.trace.events
    assert not rig.state.stores
    assert tuple(item.deleted_count for item in rig.state.delete_observations.values()) == (
        2,
        2,
        0,
        0,
    )


def _rig(
    name: str,
    *,
    answer_from_source: AnswerFromSource | None = None,
) -> _Rig:
    rows = _fixture_rows()
    dataset_bytes = _FIXTURE.read_bytes()
    public_cases = load_memory_comparison_cases(
        _FIXTURE,
        locomo_ingest_mode=LOCOMO_INGEST_RICH_DOCUMENTS,
    )
    assert len(rows) == len(public_cases) == 2
    corpus_ids = tuple(_managed_corpus_identity(case)[0] for case in public_cases)
    scenario = SandboxScenario(
        "managed-longmemeval-sandbox",
        "longmemeval",
        "managed-longmemeval-sandbox-scope",
        corpus_ids,
    )
    run_id = f"{scenario.scenario_id}-{name}"
    assert len(rows) == len(corpus_ids)
    profile = resolve_full_comparison_profile(PROFILE_LONGMEMEVAL_TOP_50)
    assert profile is not None
    route = _provider_route(name)
    mem0_target = mem0_runtime_target_identity_sha256(
        f"https://mem0.example.test/{scenario.scenario_id}-{name}"
    )
    runtime_probe_nonce_sha256 = hashlib.sha256(scenario.runtime_nonce.encode()).hexdigest()
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
        selected_case_ids=tuple(case.case_id for case in public_cases),
    )
    assert repr(admission) == "VerifiedManagedRunPlan(<sealed>)"
    trace = SandboxTrace.create()
    state = SandboxBackendState.create(scenario)
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
        answer_from_source=answer_from_source or _answer_from_source,
    )
    execution = SandboxExecutionPort(trace, candidate_channel=judge.candidate_channel)
    policy = SandboxPolicyPort(trace, state)
    assembler = ManagedFullComparisonAssembler(
        adapter_id=f"{scenario.scenario_id}-assembler",
        implementation_sha256=implementation_sha256(
            "assembler",
            scenario_id=scenario.scenario_id,
        ),
        reset_port=runtime.reset,
        attestation_port=runtime.attestation,
        ingest_port=runtime.ingest,
        clock=runtime.clock,
    )
    return _Rig(
        admission,
        public_cases,
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


def _fixture_rows() -> tuple[dict[str, object], ...]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert type(payload) is list and all(type(item) is dict for item in payload)
    return tuple(payload)


def _session_aliases(case: PublicBenchmarkCase) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.session_external_id for item in case.conversations))


def _case_alias(case: PublicBenchmarkCase) -> str:
    material = f"{case.benchmark}\0case\0{case.case_id}".encode()
    return f"{case.benchmark}-case-{hashlib.sha256(material).hexdigest()}"


def _assert_no_private_material_escaped(rig: _Rig, report: dict[str, object]) -> None:
    public_spy = json.dumps(
        {
            "report": report,
            "trace": report["managed_run"]["trace"],
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
    for raw, case in zip(_fixture_rows(), rig.public_cases, strict=True):
        private_values = (
            case.case_id,
            case.question,
            str(raw["question_id"]),
            str(raw["answer"]),
            *(str(item) for item in raw["haystack_session_ids"]),
            *(str(item) for item in raw["answer_session_ids"]),
        )
        assert all(value not in public_spy for value in private_values)


def _answer_from_source(question: str, source: str) -> str:
    if "maintenance tasks" in question:
        certificate = re.search(r"the ([^.]+) still needs renewal", source)
        api_key = re.search(r"the ([^.]+) still needs rotation", source)
        if certificate is not None and api_key is not None:
            return f"renew the {certificate.group(1)} and rotate the {api_key.group(1)}"
    if "saffron envelope" in question:
        match = re.search(r"placed the saffron envelope in the ([^.]+)", source)
        if match is not None:
            return match.group(1)
    raise AssertionError("sandbox evidence does not answer the question")


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


def _ingested_canonical_bytes(case: PublicBenchmarkCase) -> bytes:
    # Terminal deletion completed; ingest receipts retain only the canonical source hashes.
    return json.dumps(
        _managed_corpus_record(case),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
