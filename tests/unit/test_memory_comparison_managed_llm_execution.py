from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderBudget,
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_full_execution_validation_slots import (
    FullExecutionCaseManifestEntry,
    execution_case_manifest_sha256,
)
from infinity_context_server.memory_comparison_full_methodology import (
    full_comparison_methodology_contract,
)
from infinity_context_server.memory_comparison_full_profiles import (
    PROFILE_LOCOMO_TOP_50,
    PROFILE_LONGMEMEVAL_TOP_50,
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    create_full_comparison_run_bindings,
)
from infinity_context_server.memory_comparison_full_scope import (
    FULL_COMPARISON_SCOPE_CANARY,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_identity,
    _managed_corpus_record,
    _managed_corpus_session_mapping,
    _managed_official_turn_count,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    MANAGED_HTTP_EXECUTION_ADAPTER_ID,
    ManagedComparisonHttpExecutionAdapter,
    managed_http_execution_implementation_sha256,
)
from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    ManagedComparisonHttpLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_http_runner_adapter import (
    ManagedHttpRunnerAdapter,
)
from infinity_context_server.memory_comparison_managed_live_admission import (
    MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    ManagedLiveExecutionLimits,
)
from infinity_context_server.memory_comparison_managed_llm_execution import (
    MANAGED_PRODUCTION_EXECUTION_PUBLISHABLE,
    MANAGED_PRODUCTION_METHODOLOGY_STATUS,
    MANAGED_RETRIEVAL_PROOF_STATUS,
    MANAGED_SUBSCRIPTION_EXECUTION_MODEL,
    ManagedLlmExecutionError,
    create_managed_comparison_execution_ports,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedDatasetMetadata,
    ManagedPreflightRequest,
    ManagedPreflightTimeouts,
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedCaseExecution,
    ManagedRunCase,
    _thaw_json,
)
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    issue_managed_runtime_credential_authority,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderCallProvenance,
    ProviderChatCompletion,
    ProviderRouteAttestation,
)
from infinity_context_server.memory_comparison_retrieval_policy import (
    NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_RUN = "managed-production-run"
_INFINITY_TARGET = managed_backend_target_identity_sha256(
    backend_role="infinity-context",
    base_url="https://infinity.test",
)
_MEM0_TARGET = managed_backend_target_identity_sha256(
    backend_role="mem0",
    base_url="https://mem0.test",
)
_PRIVATE_GOLD = "PRIVATE-GOLD-ONLY-JUDGE"
_MODEL = MANAGED_SUBSCRIPTION_EXECUTION_MODEL


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 1, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


class _Delegate:
    def __init__(self, route: ProviderRouteAttestation) -> None:
        self.route = route
        self.calls: list[dict[str, object]] = []
        self.mode = "ok"
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format=None,
    ) -> ProviderChatCompletion:
        ordinal = len(self.calls)
        self.calls.append(
            {
                "model": model,
                "system": system_prompt,
                "user": user_prompt,
                "max_output_tokens": max_output_tokens,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        if self.mode == "block":
            self.entered.set()
            self.release.wait(timeout=3)
        if self.mode == "raise":
            raise RuntimeError("provider-secret-must-be-sanitized")
        route = (
            replace(self.route, route_sha256="9" * 64) if self.mode == "wrong_route" else self.route
        )
        observed = "wrong-model" if self.mode == "wrong_model" else model
        return ProviderChatCompletion(
            text=(
                "Kyiv"
                if ordinal % 2 == 0
                else (
                    '{"reasoning":"matches","label":"CORRECT"}'
                    if response_format is not None
                    else "yes"
                )
            ),
            prompt_tokens=1,
            completion_tokens=1,
            token_usage_source="provider_observed",
            finish_reason="stop",
            finish_reason_source="provider_observed",
            provenance=ProviderCallProvenance(
                route,
                model,
                observed,
                f"response-{ordinal}",
                f"fingerprint-{ordinal}",
                hashlib.sha256(f"request-{ordinal}".encode()).hexdigest(),
            ),
        )

    def close(self) -> None:
        return None


@dataclass
class _Scenario:
    source: PublicBenchmarkCase
    managed_case: ManagedRunCase
    query: ManagedAnswerCase
    manifest: tuple[FullExecutionCaseManifestEntry, ...]
    bindings: object
    route: ProviderRouteAttestation
    limits: ManagedLiveExecutionLimits
    runner_binding: ManagedRunnerCompositionBinding
    runner: ManagedHttpRunnerAdapter
    lifecycle: ManagedComparisonHttpLifecycleAdapter
    http: ManagedComparisonHttpExecutionAdapter
    delegate: _Delegate
    provider: BoundedProviderChatCompletions
    ports: object
    http_wire: list[str]

    def bind(self):
        return self.ports.judge_port.bind_cases(
            bindings=self.bindings,
            cases=(self.source,),
            case_aliases=(self.managed_case.case_id,),
        )

    def prepare_lifecycle(self) -> None:
        self.lifecycle.reset(
            run_id=self.bindings.run_id,
            binding_commitment_sha256=self.bindings.binding_commitment_sha256,
            backend_targets=tuple(
                (item.backend_role, item.target_identity_sha256)
                for item in self.bindings.backend_targets
            ),
        )
        record = _thaw_json(self.managed_case.record)
        for target in self.bindings.backend_targets:
            self.lifecycle.ingest(
                run_id=self.bindings.run_id,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                record=record,
            )

    def run_all(self, material):
        executions = []
        for target in self.bindings.backend_targets:
            retrieved = self.ports.execution_port.retrieve(
                bindings=self.bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                case=self.managed_case,
                query=self.query,
            )
            answered = self.ports.execution_port.answer(
                bindings=self.bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                case=self.managed_case,
                query=self.query,
                retrieval_receipt=retrieved,
            )
            judged = self.ports.judge_port.judge(
                bindings=self.bindings,
                backend_role=target.backend_role,
                target_identity_sha256=target.target_identity_sha256,
                case=self.managed_case,
                answer_receipt=answered,
            )
            executions.append(
                ManagedCaseExecution(
                    target.backend_role,
                    target.target_identity_sha256,
                    self.managed_case.case_id,
                    retrieved,
                    answered,
                    judged,
                )
            )
        return tuple(executions)


def _scenario(
    *,
    deadline_monotonic: float | None = None,
    benchmark: str = "longmemeval",
) -> _Scenario:
    clock = _Clock()
    deadline = clock.value + timedelta(minutes=5)
    profile = resolve_full_comparison_profile(
        PROFILE_LOCOMO_TOP_50 if benchmark == "locomo" else PROFILE_LONGMEMEVAL_TOP_50
    )
    assert profile is not None
    source = PublicBenchmarkCase(
        benchmark=benchmark,
        case_id="private-source-case",
        question="Where did the user move?",
        expected_terms=("Kyiv",),
        forbidden_terms=("forbidden-private",),
        memory_scope_external_ref="private-corpus",
        thread_external_ref="private-thread",
        metadata={
            "_evaluator_ground_truth": _PRIVATE_GOLD,
            "question_type": "single-session-user",
            "question_date": "2026/08/01 11:00",
            **({"locomo_ingest_mode": "official-turns"} if benchmark == "locomo" else {}),
        },
        memories=(
            (
                BenchmarkMemoryInput(
                    text="I moved to Kyiv.",
                    kind="dialogue_turn",
                    source_external_id="memory-1",
                    metadata={
                        "role": "user",
                        "speaker": "user",
                        "session_key": "session-private",
                        "session_date": "12:00 am on 1 January, 2025",
                        "timestamp": 1_735_689_600,
                    },
                ),
            )
            if benchmark == "locomo"
            else ()
        ),
        conversations=(
            ()
            if benchmark == "locomo"
            else (
                BenchmarkConversationInput(
                    messages=(
                        BenchmarkMessageInput(role="user", content="I moved to Kyiv."),
                        BenchmarkMessageInput(role="assistant", content="Noted."),
                    ),
                    source_external_id="conversation-1",
                    session_external_id="session-private",
                ),
            )
        ),
    )
    alias = (
        f"{benchmark}-case-"
        + hashlib.sha256(f"{benchmark}\0case\0{source.case_id}".encode()).hexdigest()
    )
    corpus_id, thread_id = _managed_corpus_identity(source)
    record = _managed_corpus_record(source)
    managed = ManagedRunCase(alias, corpus_id, record)
    roles, aliases = _managed_corpus_session_mapping(record)
    manifest = (
        FullExecutionCaseManifestEntry(
            alias,
            corpus_id,
            thread_id,
            roles,
            aliases,
            _managed_official_turn_count(record),
        ),
    )
    targets = (
        FullComparisonBackendTarget("infinity-context", _INFINITY_TARGET),
        FullComparisonBackendTarget("mem0", _MEM0_TARGET),
    )
    bindings = create_full_comparison_run_bindings(
        run_id=_RUN,
        run_nonce_commitment_sha256="a" * 64,
        runtime_probe_nonce_sha256="b" * 64,
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset_sha256="c" * 64,
        selection_fingerprint_sha256="d" * 64,
        backend_targets=targets,
        scope=FULL_COMPARISON_SCOPE_CANARY,
    )
    route = ProviderRouteAttestation(
        "subscription_runtime",
        "codex://subscription",
        "/v1/chat/completions",
        "e" * 64,
        "typed_subscription_bridge",
        "sha256:" + "f" * 64,
        "POST",
        200,
    )
    wire: list[str] = []

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        wire.append(request.content.decode())
        if request.url.path == "/v1/spaces":
            slug = json.loads(request.content)["slug"]
            return httpx.Response(201, json={"data": {"slug": slug}})
        payload = json.loads(request.content)
        if "query" in payload:
            return httpx.Response(
                200,
                json={"data": {"items": [{"item_id": "i-1", "text": "Kyiv"}]}},
            )
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        wire.append(request.content.decode())
        if request.method == "DELETE":
            return httpx.Response(
                200,
                json={"deleted": True, "verified_absent": True},
            )
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={"results": [{"id": "m-1", "memory": "Kyiv"}]},
            )
        return httpx.Response(200, json={"results": [{"id": "memory-created"}]})

    authority = issue_managed_runtime_credential_authority(
        run_id=_RUN,
        infinity_origin="https://infinity.test",
        infinity_auth_token="token",
        mem0_origin="https://mem0.test",
        mem0_api_key="mem0-token",
        mem0_probe_token="mem0-probe-token",
        subscription_origin="http://127.0.0.1:8890",
        subscription_bearer_token="subscription-token",
        request_timeout_seconds=20,
        issued_at=clock.value,
        deadline=deadline,
    )
    preflight_material = authority.preflight_material()
    preflight_request = ManagedPreflightRequest(
        profile=profile,
        methodology=full_comparison_methodology_contract(profile),
        dataset=ManagedDatasetMetadata(
            profile.profile_id,
            profile.benchmark,
            profile.expected_dataset_hash,
            profile.expected_case_count,
            dict(profile.expected_distribution),
            profile.expected_corpus_count,
        ),
        provider_route=preflight_material.provider_route,
        answerer_model=_MODEL,
        judge_model=_MODEL,
        openai_credential=preflight_material.provider_credential,
        backend_endpoints=preflight_material.backend_endpoints,
        timeouts=ManagedPreflightTimeouts(
            1,
            20,
            (deadline - clock.value).total_seconds(),
        ),
        scope=FULL_COMPARISON_SCOPE_CANARY,
        provider_kind=MANAGED_PREFLIGHT_PROVIDER_SUBSCRIPTION_RUNTIME,
    )
    authority.bind_preflight_request(
        preflight_request,
        run_id=_RUN,
        deadline=deadline,
    )
    credential_material = authority.issue_backend_credential_material(
        expected_request=preflight_request,
        run_id=_RUN,
        infinity_origin="https://infinity.test",
        mem0_origin="https://mem0.test",
        deadline=deadline,
        now=clock.value,
        infinity_transport=httpx.MockTransport(infinity_handler),
        mem0_transport=httpx.MockTransport(mem0_handler),
        mem0_send_timestamps=benchmark == "locomo",
    )
    http = ManagedComparisonHttpExecutionAdapter(
        preflight_request=preflight_request,
        run_id=_RUN,
        deadline=deadline,
        credential_material=credential_material,
        retrieval_policy=NEUTRAL_COMPARISON_RETRIEVAL_POLICY,
        clock=clock,
    )
    lifecycle = ManagedComparisonHttpLifecycleAdapter(
        run_id=_RUN,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        admitted_targets=targets,
        cases=(managed,),
        deadline=deadline,
        execution=http,
        preflight_request=preflight_request,
        credential_material=credential_material,
        infinity_reset_transport=httpx.MockTransport(infinity_handler),
        mem0_reset_transport=httpx.MockTransport(mem0_handler),
        clock=clock,
    )
    limits = ManagedLiveExecutionLimits(
        MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        _MODEL,
        _MODEL,
        1,
        4,
        1,
        5,
        100_000,
        1,
        "estimated_by_subscription_runtime",
        100_001,
        False,
        1,
        clock.value,
        deadline,
    )
    delegate = _Delegate(route)
    provider = BoundedProviderChatCompletions(
        delegate=delegate,
        budget=BoundedProviderBudget(
            max_total_tokens=100_000,
            deadline_monotonic=(
                time.monotonic() + 120 if deadline_monotonic is None else deadline_monotonic
            ),
            max_calls=4,
            max_output_tokens_per_call=4096,
        ),
        input_token_estimator=lambda _text: 1,
    )
    runner_binding = ManagedRunnerCompositionBinding(
        run_id=_RUN,
        profile=profile,
        binding_commitment_sha256=bindings.binding_commitment_sha256,
        deadline=deadline,
        backend_targets=targets,
        retrieval_top_k=profile.retrieval_top_k,
        answer_cutoff=profile.answer_cutoff,
    )
    runner = ManagedHttpRunnerAdapter(
        composition_binding=runner_binding,
        http=http,
        lifecycle=lifecycle,
    )
    ports = create_managed_comparison_execution_ports(
        composition_binding=runner_binding,
        retrieval=runner,
        execution_evidence=runner,
        retrieval_adapter_id=MANAGED_HTTP_EXECUTION_ADAPTER_ID,
        retrieval_implementation_sha256=managed_http_execution_implementation_sha256(),
        provider=provider,
        limits=limits,
        provider_route=route,
    )
    query = ManagedAnswerCase(
        alias,
        source.question,
        {
            "question_type": source.metadata["question_type"],
            "question_date": source.metadata["question_date"],
        },
    )
    return _Scenario(
        source,
        managed,
        query,
        manifest,
        bindings,
        route,
        limits,
        runner_binding,
        runner,
        lifecycle,
        http,
        delegate,
        provider,
        ports,
        wire,
    )


def test_exact_two_backend_execution_is_gold_blind_and_seals_full_validation() -> None:
    scenario = _scenario()
    material = scenario.bind()
    scenario.prepare_lifecycle()

    executions = scenario.run_all(material)
    artifacts = scenario.ports.judge_port.seal_execution(
        bindings=scenario.bindings,
        case_manifest=scenario.manifest,
        executions=executions,
        case_manifest_sha256=execution_case_manifest_sha256(scenario.manifest),
        case_material_sha256=material,
    )

    assert artifacts.gold_blind_validation is not artifacts.execution_validation
    assert len(artifacts.quality_outcomes) == 2
    assert all(
        repr(item) == "ManagedSealedJudgeOutcome(<opaque>)"
        and not any(
            hasattr(item, field)
            for field in ("case_alias", "backend_role", "verdict", "score", "judge_result_sha256")
        )
        for item in artifacts.quality_outcomes
    )
    assert len(scenario.delegate.calls) == 4
    assert [item["model"] for item in scenario.delegate.calls] == [_MODEL] * 4
    assert all(item["max_output_tokens"] == 4096 for item in scenario.delegate.calls)
    assert all(item["temperature"] == 0 for item in scenario.delegate.calls)
    assert all(item["response_format"] is None for item in scenario.delegate.calls)
    assert all(_PRIVATE_GOLD not in scenario.delegate.calls[index]["user"] for index in (0, 2))
    assert all(_PRIVATE_GOLD in scenario.delegate.calls[index]["user"] for index in (1, 3))
    assert _PRIVATE_GOLD not in "".join(scenario.http_wire)
    assert scenario.ports.execution_port is not scenario.ports.judge_port
    assert MANAGED_PRODUCTION_EXECUTION_PUBLISHABLE is False
    assert "nonpublishable" in MANAGED_PRODUCTION_METHODOLOGY_STATUS
    assert "no_full_execution_artifact_slot" in MANAGED_RETRIEVAL_PROOF_STATUS


def test_locomo_judge_dispatches_exact_strict_schema_for_both_backends() -> None:
    scenario = _scenario(benchmark="locomo")
    material = scenario.bind()
    scenario.prepare_lifecycle()

    executions = scenario.run_all(material)

    assert len(executions) == 2
    assert scenario.delegate.calls[0]["response_format"] is None
    assert scenario.delegate.calls[2]["response_format"] is None
    assert scenario.delegate.calls[1]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "locomo_judge",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string"},
                    "label": {"type": "string", "enum": ["CORRECT", "WRONG"]},
                },
                "required": ["reasoning", "label"],
                "additionalProperties": False,
            },
        },
    }
    assert scenario.delegate.calls[3]["response_format"] == scenario.delegate.calls[1][
        "response_format"
    ]


def test_missing_lifecycle_evidence_fails_before_retrieval_or_provider() -> None:
    scenario = _scenario()
    scenario.bind()

    with pytest.raises(ManagedLlmExecutionError, match="retrieval_failed"):
        scenario.ports.execution_port.retrieve(
            bindings=scenario.bindings,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=scenario.managed_case,
            query=scenario.query,
        )

    assert scenario.delegate.calls == []
    assert scenario.http_wire == []


@pytest.mark.parametrize("kind", ("wrong_target", "wrong_question", "answer_before_retrieve"))
def test_wrong_target_question_or_order_is_terminal_before_paid_calls(kind: str) -> None:
    scenario = _scenario()
    scenario.bind()
    if kind != "answer_before_retrieve":
        scenario.prepare_lifecycle()

    with pytest.raises(ManagedLlmExecutionError, match="operation_rejected"):
        if kind == "answer_before_retrieve":
            scenario.ports.execution_port.answer(
                bindings=scenario.bindings,
                backend_role="infinity-context",
                target_identity_sha256=_INFINITY_TARGET,
                case=scenario.managed_case,
                query=scenario.query,
                retrieval_receipt=object(),
            )
        else:
            scenario.ports.execution_port.retrieve(
                bindings=scenario.bindings,
                backend_role="infinity-context",
                target_identity_sha256=(
                    _MEM0_TARGET if kind == "wrong_target" else _INFINITY_TARGET
                ),
                case=scenario.managed_case,
                query=(
                    ManagedAnswerCase(
                        scenario.query.case_id,
                        "wrong question",
                        dict(scenario.query.temporal_context),
                    )
                    if kind == "wrong_question"
                    else scenario.query
                ),
            )
    assert scenario.delegate.calls == []


@pytest.mark.parametrize("mode", ("raise", "wrong_model", "wrong_route"))
def test_provider_failure_model_and_route_are_one_shot_and_sanitized(mode: str) -> None:
    scenario = _scenario()
    scenario.bind()
    scenario.prepare_lifecycle()
    retrieved = scenario.ports.execution_port.retrieve(
        bindings=scenario.bindings,
        backend_role="infinity-context",
        target_identity_sha256=_INFINITY_TARGET,
        case=scenario.managed_case,
        query=scenario.query,
    )
    scenario.delegate.mode = mode

    with pytest.raises(ManagedLlmExecutionError) as caught:
        scenario.ports.execution_port.answer(
            bindings=scenario.bindings,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=scenario.managed_case,
            query=scenario.query,
            retrieval_receipt=retrieved,
        )

    assert len(scenario.delegate.calls) == 1
    assert "provider-secret" not in str(caught.value)
    with pytest.raises(ManagedLlmExecutionError, match="operation_rejected"):
        scenario.ports.execution_port.answer(
            bindings=scenario.bindings,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=scenario.managed_case,
            query=scenario.query,
            retrieval_receipt=retrieved,
        )
    assert len(scenario.delegate.calls) == 1


def test_expired_shared_provider_deadline_makes_no_delegate_call() -> None:
    scenario = _scenario(deadline_monotonic=1.0)
    scenario.bind()
    scenario.prepare_lifecycle()
    retrieved = scenario.ports.execution_port.retrieve(
        bindings=scenario.bindings,
        backend_role="infinity-context",
        target_identity_sha256=_INFINITY_TARGET,
        case=scenario.managed_case,
        query=scenario.query,
    )

    with pytest.raises(ManagedLlmExecutionError, match="answer_failed"):
        scenario.ports.execution_port.answer(
            bindings=scenario.bindings,
            backend_role="infinity-context",
            target_identity_sha256=_INFINITY_TARGET,
            case=scenario.managed_case,
            query=scenario.query,
            retrieval_receipt=retrieved,
        )
    assert scenario.delegate.calls == []


def test_concurrent_answer_attempts_fail_closed_with_at_most_one_provider_call() -> None:
    scenario = _scenario()
    scenario.bind()
    scenario.prepare_lifecycle()
    retrieved = scenario.ports.execution_port.retrieve(
        bindings=scenario.bindings,
        backend_role="infinity-context",
        target_identity_sha256=_INFINITY_TARGET,
        case=scenario.managed_case,
        query=scenario.query,
    )
    scenario.delegate.mode = "block"
    errors: list[BaseException] = []

    def answer() -> None:
        try:
            scenario.ports.execution_port.answer(
                bindings=scenario.bindings,
                backend_role="infinity-context",
                target_identity_sha256=_INFINITY_TARGET,
                case=scenario.managed_case,
                query=scenario.query,
                retrieval_receipt=retrieved,
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=answer)
    first.start()
    assert scenario.delegate.entered.wait(timeout=2)
    second = threading.Thread(target=answer)
    second.start()
    second.join(timeout=2)
    scenario.delegate.release.set()
    first.join(timeout=2)

    assert len(scenario.delegate.calls) == 1
    assert len(errors) == 2
    assert all(type(item) is ManagedLlmExecutionError for item in errors)


@pytest.mark.parametrize("failure", ("coverage", "tamper"))
def test_seal_rejects_missing_lane_coverage_and_retrieval_metadata_tamper(
    failure: str,
) -> None:
    scenario = _scenario()
    material = scenario.bind()
    scenario.prepare_lifecycle()
    executions = scenario.run_all(material)
    if failure == "tamper":
        coordinator = scenario.ports.execution_port._coordinator
        lane = coordinator._lanes[(scenario.managed_case.case_id, "infinity-context")]
        object.__setattr__(lane.retrieval_result, "metadata", {"adapter_id": "tampered"})
        supplied = executions
    else:
        supplied = executions[:-1]

    with pytest.raises(ManagedLlmExecutionError):
        scenario.ports.judge_port.seal_execution(
            bindings=scenario.bindings,
            case_manifest=scenario.manifest,
            executions=supplied,
            case_manifest_sha256=execution_case_manifest_sha256(scenario.manifest),
            case_material_sha256=material,
        )


def test_non_admitted_model_is_rejected_at_composition() -> None:
    scenario = _scenario()
    wrong_limits = replace(
        scenario.limits,
        answerer_model="gpt-5",
        judge_model="gpt-5",
    )
    with pytest.raises(ManagedLlmExecutionError, match="composition_invalid"):
        create_managed_comparison_execution_ports(
            composition_binding=scenario.runner_binding,
            retrieval=scenario.runner,
            execution_evidence=scenario.runner,
            retrieval_adapter_id=MANAGED_HTTP_EXECUTION_ADAPTER_ID,
            retrieval_implementation_sha256=managed_http_execution_implementation_sha256(),
            provider=scenario.provider,
            limits=wrong_limits,
            provider_route=scenario.route,
        )
