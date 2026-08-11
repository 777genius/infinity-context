from __future__ import annotations

import gc
import hashlib
import json
import pickle
import weakref
from dataclasses import FrozenInstanceError, replace

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeAuthority,
    BridgeCallBinding,
    BridgePoolAuthority,
    canonical_openai_request_body,
)
from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    derive_bridge_intent,
)
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult, RetrievedMemory
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerBackendAuthority,
    SchedulerBenchmark,
    SchedulerBridgeBootAuthority,
    SchedulerCallStage,
    SchedulerContractError,
    SchedulerDeadlineTokenAuthority,
    SchedulerRunBinding,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerCaseAuthority,
    SchedulerLogicalCall,
    build_scheduler_manifest,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerPrivateAnswerReadCapability,
    SchedulerRequestContext,
    SchedulerRunnerError,
)
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
    SCHEDULER_OFFICIAL_REQUEST_MODEL,
    SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT,
    SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER,
    PublishableOfficialRequestRenderer,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SCHEDULER_OFFICIAL_CASE_BYTES_CAP,
    SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
    SCHEDULER_RETRIEVAL_EVIDENCE_BYTES_CAP,
    SchedulerAuthenticatedOfficialCase,
    SchedulerAuthenticatedRetrievalEvidence,
    SchedulerDecryptedPrivateAnswer,
    SchedulerOfficialRendererComposition,
    SchedulerRetrievalEvidenceKey,
    official_case_material_sha256,
    retrieval_evidence_material_sha256,
)
from official_runtime_parser_test_support import (
    compiled_runtime_parse as _compiled_runtime_parse,
)
from official_runtime_parser_test_support import (
    requires_compiled_runtime as _requires_compiled_runtime,
)

_CASE_ROOT = hashlib.sha256(b"official-case-root").hexdigest()
_RETRIEVAL_ROOT = hashlib.sha256(b"exact-retrieval-root").hexdigest()
_DECRYPT_POLICY = hashlib.sha256(b"authenticated-private-output-decrypt").hexdigest()
_REQUEST_SHA256 = {
    ("locomo", 0, "answer"): "ba8a1d02f67e595828bb0431fb3544d0798edb459b9b3796b6688da92e31faed",
    ("locomo", 0, "judge"): "97e77216798db8022e14a8e3634df9fddcb34805ba68f72774630e4641f335bf",
    ("locomo", 1, "answer"): "3fc242449aa82d2dd6cba479576c8d5d332c2b80c41eca7ee8ea0b0d00298d4d",
    ("locomo", 1, "judge"): "427f4621592e03d47d85e592d72b1082ba38875b5735a88753825a1d2a541240",
    (
        "longmemeval",
        0,
        "answer",
    ): "43a0930151238c6535f35b26a42efbcb20387477a4d653eb498b8bfdc43ac337",
    (
        "longmemeval",
        0,
        "judge",
    ): "0d70a84c1b2394a9961342ec6e3859580405ae7a4da0287674a57c495858eeab",
    (
        "longmemeval",
        1,
        "answer",
    ): "fac6bcd74b44cc1e4d74c7864f1514f23b9b76f30806cb68df83b124f62ac0cf",
    (
        "longmemeval",
        1,
        "judge",
    ): "af53c32638f02ad5f916a4bf90433eee90a23a5474c2c2553802607c9a55fc13",
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _runtime_bridge_pool() -> BridgePoolAuthority:
    return BridgePoolAuthority(
        pool_id="official-renderer-runtime-pool",
        bridges=(
            BridgeAuthority(
                bridge_id="official-renderer-runtime",
                origin="http://127.0.0.1:43100",
                account_binding_hmac_sha256=_sha("runtime-account"),
                public_model=SCHEDULER_OFFICIAL_REQUEST_MODEL,
                base_instructions_sha256=_sha("runtime-base-instructions"),
            ),
        ),
    )


def _profile_payload() -> dict[str, object]:
    profile = publishable_priority_comparison_profile_v4()
    return public_publishable_comparison_profile(profile)


def _case_authorities(benchmark: str, count: int) -> tuple[SchedulerCaseAuthority, ...]:
    return tuple(
        SchedulerCaseAuthority(
            case_id=f"{benchmark}-case-{index}",
            case_alias=f"{benchmark}-{index}",
        )
        for index in range(count)
    )


def _suite(*, manifests: tuple[str, str] | None = None) -> SchedulerSuiteAuthority:
    profile = _profile_payload()
    case_manifests = manifests or (_sha("locomo-manifest"), _sha("longmemeval-manifest"))
    backends = (
        SchedulerBackendAuthority("infinity-context", _sha("infinity-target")),
        SchedulerBackendAuthority("mem0", _sha("mem0-target")),
    )

    def binding(index: int) -> SchedulerRunBinding:
        scheduler_profile = (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)[index]
        benchmark = scheduler_profile.benchmark.value
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=1_000,
            dispatch_deadline_unix_ms=100_000,
            answer_max_output_tokens=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
            judge_max_output_tokens=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
            run_token_ceiling=(
                scheduler_profile.case_count * 4 * SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            ),
        )
        benchmark_spec = profile["benchmarks"][benchmark]
        return SchedulerRunBinding(
            run_id=f"{benchmark}-official-run",
            profile=scheduler_profile,
            binding_commitment_sha256=_sha(f"{benchmark}-run-binding"),
            dataset_sha256=benchmark_spec["dataset_sha256"],
            case_manifest_sha256=case_manifests[index],
            backends=backends,
            limits=limits,
        )

    bridge = SchedulerBridgeBootAuthority(
        bridge_id="reviewed-priority-bridge",
        implementation_sha256=_sha("bridge-implementation"),
        runtime_authority_sha256=_sha("priority-runtime"),
        boot_nonce_sha256=_sha("bridge-boot-nonce"),
        receipt_verifier_policy_sha256=_sha("receipt-verifier"),
    )
    return SchedulerSuiteAuthority(
        suite_id="official-priority-suite",
        publication_bundle_sha256=_sha("publication-bundle"),
        methodology_sha256=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
        source_commit_sha256=_sha("source-commit"),
        bridge_boot=bridge,
        ordered_runs=(binding(0), binding(1)),
    )


def _call(
    suite: SchedulerSuiteAuthority,
    *,
    benchmark: SchedulerBenchmark,
    backend_index: int,
    stage: SchedulerCallStage,
    case_index: int = 0,
):
    run_index = 0 if benchmark is SchedulerBenchmark.LOCOMO else 1
    run = run_authority_from_suite(suite, run_index=run_index)
    prefix = benchmark.value
    ordinal = case_index * 4 + backend_index * 2
    backend = run.binding.backends[backend_index]
    answer = SchedulerLogicalCall(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_id=run.binding.run_id,
        case_index=case_index,
        case_id=f"{prefix}-case-{case_index}",
        case_alias=f"{prefix}-{case_index}",
        backend_index=backend_index,
        backend_role=backend.backend_role,
        target_identity_sha256=backend.target_identity_sha256,
        stage=SchedulerCallStage.ANSWER,
        ordinal=ordinal,
        shard_index=ordinal // 256,
        token_ceiling=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
        depends_on_logical_call_id=None,
    )
    if stage is SchedulerCallStage.ANSWER:
        return run, answer
    judge = SchedulerLogicalCall(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_id=run.binding.run_id,
        case_index=case_index,
        case_id=answer.case_id,
        case_alias=answer.case_alias,
        backend_index=backend_index,
        backend_role=backend.backend_role,
        target_identity_sha256=backend.target_identity_sha256,
        stage=SchedulerCallStage.JUDGE,
        ordinal=ordinal + 1,
        shard_index=(ordinal + 1) // 256,
        token_ceiling=SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
        depends_on_logical_call_id=answer.logical_call_id,
    )
    return run, judge


def _official_case(key) -> PublicBenchmarkCase:
    if key.benchmark is SchedulerBenchmark.LOCOMO:
        return PublicBenchmarkCase(
            benchmark="locomo",
            case_id=key.case_id,
            question="Which database did Alex choose?",
            expected_terms=("GOLD-ONLY-CANARY",),
            forbidden_terms=("FORBIDDEN-GOLD-CANARY",),
            metadata={
                "category": 3,
                "_evaluator_ground_truth": "Postgres; because it is reliable",
                "answer_preview": "GOLD-ONLY-CANARY",
                "reference_date": "January 04, 2024",
            },
        )
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id=key.case_id,
        question="Which database do I use now?",
        expected_terms=("GOLD-ONLY-CANARY",),
        forbidden_terms=("FORBIDDEN-GOLD-CANARY",),
        metadata={
            "question_type": "knowledge-update",
            "question_date": "2024/01/04 (Thu) 09:30",
            "_evaluator_ground_truth": "Postgres",
            "answer_preview": "GOLD-ONLY-CANARY",
        },
    )


def _memories(key) -> tuple[RetrievedMemory, ...]:
    current = (
        "Alex chose Postgres via Infinity."
        if key.backend_role == "infinity-context"
        else "Alex chose Postgres via Mem0."
    )
    return (
        RetrievedMemory(
            text=current,
            rank=1,
            score=0.9,
            item_id=f"private-{key.backend_role}",
            created_at="2024-01-03T10:00:00Z",
            metadata={"backend": key.backend_role},
        ),
        RetrievedMemory(
            text="Alex previously tested SQLite.",
            rank=2,
            score=0.8,
            created_at="2023-01-02T10:00:00Z",
            metadata={},
        ),
    )


class _CaseReader:
    authority_root_sha256 = _CASE_ROOT

    def __init__(self, *, mode: str = "exact") -> None:
        self.mode = mode
        self.calls = 0
        self.last_key = None
        self.last_case_ref = None
        self.max_prior_live = 0

    def read_exact(self, *, key):
        self.calls += 1
        if self.last_case_ref is not None and self.last_case_ref() is not None:
            self.max_prior_live += 1
        self.last_key = key
        result_key = key
        case = _official_case(key)
        if self.mode == "wrong_case":
            result_key = replace(key, case_id="foreign-case")
            case = replace(case, case_id="foreign-case")
        elif self.mode == "wrong_run":
            result_key = replace(key, run_authority_sha256=_sha("foreign-run"))
        self.last_case_ref = weakref.ref(case)
        return SchedulerAuthenticatedOfficialCase(
            key=result_key,
            material_sha256=official_case_material_sha256(result_key, case),
            case=case,
        )


class _RetrievalReader:
    authority_root_sha256 = _RETRIEVAL_ROOT

    def __init__(self, *, mode: str = "exact") -> None:
        self.mode = mode
        self.calls = 0
        self.last_key = None

    def read_exact(self, *, key):
        self.calls += 1
        self.last_key = key
        result_key = replace(key)
        memories = _memories(key)
        result = SchedulerAuthenticatedRetrievalEvidence(
            key=result_key,
            material_sha256=retrieval_evidence_material_sha256(result_key, memories),
            memories=memories,
        )
        if self.mode == "wrong_backend":
            role = "mem0" if key.backend_role == "infinity-context" else "infinity-context"
            result_key = replace(key, backend_role=role)
            return SchedulerAuthenticatedRetrievalEvidence(
                key=result_key,
                material_sha256=retrieval_evidence_material_sha256(result_key, memories),
                memories=memories,
            )
        if self.mode == "wrong_case":
            wrong_case_key = replace(key.case_key, case_id="foreign-case")
            result_key = replace(key, case_key=wrong_case_key)
            return SchedulerAuthenticatedRetrievalEvidence(
                key=result_key,
                material_sha256=retrieval_evidence_material_sha256(result_key, memories),
                memories=memories,
            )
        if self.mode == "wrong_cutoff":
            object.__setattr__(result_key, "cutoff", 49)
        return result


class _Decryptor:
    policy_sha256 = _DECRYPT_POLICY

    def __init__(self, *, mode: str = "exact") -> None:
        self.mode = mode
        self.calls = 0
        self.last_ciphertext = None
        self.last_context = None

    def decrypt_exact(self, ciphertext, *, context):
        self.calls += 1
        self.last_ciphertext = ciphertext
        self.last_context = context
        result_context = context
        if self.mode == "substituted_ciphertext":
            result_context = replace(context, ciphertext_sha256=_sha("substituted"))
        elif self.mode == "cross_run":
            case_key = replace(context.case_key, run_authority_sha256=_sha("foreign-run"))
            result_context = replace(context, case_key=case_key)
        elif self.mode == "cross_backend":
            role = "mem0" if context.backend_role == "infinity-context" else "infinity-context"
            result_context = replace(context, backend_role=role)
        elif self.mode == "cross_case":
            case_key = replace(context.case_key, case_id="foreign-case")
            result_context = replace(context, case_key=case_key)
        elif self.mode == "ignored":
            return object()
        answer = (
            "Reasoning\nANSWER: Postgres"
            if context.backend_role == "infinity-context"
            else "ANSWER: SQLite"
        )
        return SchedulerDecryptedPrivateAnswer(context=result_context, answer=answer)


def _renderer(
    suite: SchedulerSuiteAuthority,
    *,
    case_mode: str = "exact",
    retrieval_mode: str = "exact",
    decrypt_mode: str = "exact",
):
    case_reader = _CaseReader(mode=case_mode)
    retrieval_reader = _RetrievalReader(mode=retrieval_mode)
    decryptor = _Decryptor(mode=decrypt_mode)
    composition = SchedulerOfficialRendererComposition(
        case_reader=case_reader,
        retrieval_reader=retrieval_reader,
        private_output_decryptor=decryptor,
        case_authority_root_sha256=_CASE_ROOT,
        retrieval_authority_root_sha256=_RETRIEVAL_ROOT,
        private_output_decrypt_policy_sha256=_DECRYPT_POLICY,
    )
    renderer = PublishableOfficialRequestRenderer(suite=suite, composition=composition)
    return renderer, case_reader, retrieval_reader, decryptor


def _context(
    suite: SchedulerSuiteAuthority,
    *,
    benchmark: SchedulerBenchmark,
    backend_index: int,
    stage: SchedulerCallStage,
):
    run, call = _call(
        suite,
        benchmark=benchmark,
        backend_index=backend_index,
        stage=stage,
    )
    capability = None
    ciphertext = None
    if stage is SchedulerCallStage.JUDGE:
        ciphertext = f"ciphertext:{call.depends_on_logical_call_id}".encode()
        capability = SchedulerPrivateAnswerReadCapability(ciphertext)
    context = SchedulerRequestContext(
        suite=suite,
        run=run,
        call=call,
        dependency_answer_capability=capability,
    )
    return context, ciphertext, capability


@pytest.mark.parametrize("benchmark", tuple(SchedulerBenchmark))
@pytest.mark.parametrize("backend_index", (0, 1))
@pytest.mark.parametrize("stage", tuple(SchedulerCallStage))
def test_exact_official_answer_and_judge_request_bytes(
    benchmark: SchedulerBenchmark,
    backend_index: int,
    stage: SchedulerCallStage,
) -> None:
    suite = _suite()
    renderer, case_reader, retrieval_reader, decryptor = _renderer(suite)
    context, ciphertext, capability = _context(
        suite,
        benchmark=benchmark,
        backend_index=backend_index,
        stage=stage,
    )

    rendered = renderer.render(context)
    payload = json.loads(rendered.payload)
    case = _official_case(case_reader.last_key)
    if stage is SchedulerCallStage.ANSWER:
        prompt = render_mem0_official_answer_prompt(case, _memories(retrieval_reader.last_key))
    else:
        answer = "Reasoning\nANSWER: Postgres" if backend_index == 0 else "ANSWER: SQLite"
        prompt = render_mem0_official_judge_prompt(case, AnswerResult(answer=answer))
    expected = {
        "max_tokens": 4096,
        "messages": [
            {"content": prompt.system, "role": "system"},
            {"content": prompt.user, "role": "user"},
        ],
        "model": "gpt-5.6-sol",
        "temperature": 0,
        "user": payload["user"],
    }
    if stage is SchedulerCallStage.JUDGE and benchmark is SchedulerBenchmark.LOCOMO:
        expected["response_format"] = locomo_judge_response_format()

    assert rendered.payload == canonical_openai_request_body(expected)
    assert isinstance(payload["user"], str)
    assert len(payload["user"]) == 64
    assert all(character in "0123456789abcdef" for character in payload["user"])
    assert rendered.payload_sha256 == _REQUEST_SHA256[(benchmark.value, backend_index, stage.value)]
    assert canonical_openai_request_body(payload) == rendered.payload
    assert "reasoning_effort" not in payload
    assert "service_tier" not in payload
    pool = _runtime_bridge_pool()
    selected, intent = derive_bridge_intent(
        pool=pool,
        binding=BridgeCallBinding(
            intent_id=f"official-{benchmark.value}-{backend_index}-{stage.value}",
            logical_operation=stage.value,
            logical_call_id=f"call-{benchmark.value}-{backend_index}-{stage.value}",
        ),
        request_body=rendered.payload,
        maximum_request_bytes=4 * 1024 * 1024,
    )
    assert selected == pool.bridges[0]
    assert intent.request_body_sha256 == rendered.payload_sha256
    assert intent.request_identity_nonce == payload["user"]
    assert intent.output_token_limit == SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
    assert rendered.renderer_policy_sha256 == renderer.renderer_policy_sha256
    assert rendered.private_answer_policy_sha256 == renderer.private_answer_policy_sha256
    assert case_reader.calls == 1
    assert retrieval_reader.calls == (1 if stage is SchedulerCallStage.ANSWER else 0)
    assert decryptor.calls == (1 if stage is SchedulerCallStage.JUDGE else 0)
    if stage is SchedulerCallStage.ANSWER:
        assert rendered.dependency_answer_ciphertext_sha256 is None
        assert "GOLD-ONLY-CANARY" not in rendered.payload.decode()
        assert "FORBIDDEN-GOLD-CANARY" not in rendered.payload.decode()
    else:
        assert capability is not None and capability.was_read
        assert decryptor.last_ciphertext == ciphertext
        assert (
            rendered.dependency_answer_ciphertext_sha256
            == hashlib.sha256(ciphertext or b"").hexdigest()
        )


@_requires_compiled_runtime
@pytest.mark.parametrize("benchmark", tuple(SchedulerBenchmark))
@pytest.mark.parametrize("backend_index", (0, 1))
@pytest.mark.parametrize("stage", tuple(SchedulerCallStage))
def test_all_official_request_variants_pass_pinned_compiled_runtime_parser(
    benchmark: SchedulerBenchmark,
    backend_index: int,
    stage: SchedulerCallStage,
) -> None:
    suite = _suite()
    renderer, _, _, _ = _renderer(suite)
    context, _, _ = _context(
        suite,
        benchmark=benchmark,
        backend_index=backend_index,
        stage=stage,
    )

    rendered = renderer.render(context)
    parsed = _compiled_runtime_parse(rendered.payload)

    expected_keys = {"messages", "model", "requestedOutputTokenLimit", "temperature"}
    if stage is SchedulerCallStage.JUDGE and benchmark is SchedulerBenchmark.LOCOMO:
        expected_keys.add("response_format")
        assert parsed["response_format"] == locomo_judge_response_format()
    assert set(parsed) == expected_keys
    assert parsed["model"] == SCHEDULER_OFFICIAL_REQUEST_MODEL
    assert parsed["requestedOutputTokenLimit"] == (SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS)
    assert parsed["temperature"] == 0


@_requires_compiled_runtime
@pytest.mark.parametrize(
    ("case", "field", "value", "runtime_recognizes", "local_error"),
    [
        ("old_reasoning", "reasoning_effort", "high", False, "schema_invalid"),
        ("wrong_reasoning", "reasoning_effort", "low", False, "schema_invalid"),
        ("old_tier", "service_tier", "priority", False, "schema_invalid"),
        ("wrong_tier", "service_tier", "default", False, "schema_invalid"),
        ("unknown", "future_runtime_selector", "ignored", False, "schema_invalid"),
        ("wrong_model", "model", "gpt-wrong", True, "public_model_invalid"),
    ],
)
def test_pinned_parser_differential_for_request_and_boot_fields(
    case: str,
    field: str,
    value: str,
    runtime_recognizes: bool,
    local_error: str,
) -> None:
    request = {
        "max_tokens": SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
        "messages": [{"content": "private prompt", "role": "user"}],
        "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
        "temperature": 0,
    }
    request[field] = value
    request_body = canonical_openai_request_body(request)

    parsed = _compiled_runtime_parse(request_body)

    if runtime_recognizes:
        assert parsed[field] == value
    else:
        assert field not in parsed
    with pytest.raises(ValueError, match=local_error):
        derive_bridge_intent(
            pool=_runtime_bridge_pool(),
            binding=BridgeCallBinding(
                intent_id=f"differential-{case}",
                logical_operation="answer",
                logical_call_id=f"call-{case}",
            ),
            request_body=request_body,
            maximum_request_bytes=4 * 1024 * 1024,
        )


def test_policy_and_repeated_render_are_immutable_and_deterministic() -> None:
    suite = _suite()
    renderer, _, _, _ = _renderer(suite)
    first_context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.JUDGE,
    )
    second_context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.JUDGE,
    )

    first = renderer.render(first_context)
    second = renderer.render(second_context)
    policy = renderer.policy
    material = policy.material()

    assert first.payload == second.payload
    assert first.payload_sha256 == second.payload_sha256
    assert material["profile"] == {
        "commitment_sha256": PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        "profile_id": PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    }
    assert material["methodology"]["commitment_sha256"] == (
        PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
    )
    assert material["request"]["model"] == SCHEDULER_OFFICIAL_REQUEST_MODEL
    assert "reasoning_effort" not in material["request"]
    assert "service_tier" not in material["request"]
    assert material["runtime_boot"] == {
        "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
        "reasoning_effort": SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT,
        "service_tier": SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER,
    }
    assert material["request"]["max_output_tokens"] == 4096
    assert material["authorities"]["case_authority_root_sha256"] == _CASE_ROOT
    assert material["authorities"]["retrieval_authority_root_sha256"] == _RETRIEVAL_ROOT
    with pytest.raises(FrozenInstanceError):
        policy.suite_authority_sha256 = _sha("mutated")


@pytest.mark.parametrize(
    ("port_name", "binding_attribute"),
    (
        ("case", "authority_root_sha256"),
        ("retrieval", "authority_root_sha256"),
        ("decryptor", "policy_sha256"),
    ),
)
def test_private_composition_bindings_are_revalidated_before_every_render(
    port_name: str,
    binding_attribute: str,
) -> None:
    suite = _suite()
    renderer, case_reader, retrieval_reader, decryptor = _renderer(suite)
    ports = {
        "case": case_reader,
        "retrieval": retrieval_reader,
        "decryptor": decryptor,
    }
    setattr(ports[port_name], binding_attribute, _sha(f"drifted-{port_name}"))
    context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.ANSWER,
    )

    with pytest.raises(SchedulerRunnerError, match="renderer_composition_invalid"):
        renderer.render(context)

    assert case_reader.calls == 0
    assert retrieval_reader.calls == 0
    assert decryptor.calls == 0


@pytest.mark.parametrize("mutation", ("methodology", "profile", "dataset", "backend"))
def test_wrong_suite_profile_and_methodology_commitments_fail_closed(mutation: str) -> None:
    suite = _suite()
    if mutation == "methodology":
        suite = replace(suite, methodology_sha256=_sha("wrong-methodology"))
    else:
        binding = suite.ordered_runs[0]
        if mutation == "profile":
            binding = replace(binding, profile=replace(LOCOMO_PROFILE, profile_id="wrong-profile"))
        elif mutation == "dataset":
            binding = replace(binding, dataset_sha256=_sha("wrong-dataset"))
        else:
            wrong_backend = replace(binding.backends[0], backend_role="wrong-backend")
            with pytest.raises(SchedulerContractError, match="scheduler_run_binding_invalid"):
                replace(binding, backends=(wrong_backend, binding.backends[1]))
            return
        suite = replace(suite, ordered_runs=(binding, suite.ordered_runs[1]))

    with pytest.raises(SchedulerRunnerError, match="profile_invalid"):
        _renderer(suite)


@pytest.mark.parametrize(
    ("case_mode", "retrieval_mode", "match"),
    (
        ("wrong_case", "exact", "case_binding_invalid"),
        ("wrong_run", "exact", "case_binding_invalid"),
        ("exact", "wrong_case", "retrieval_evidence_binding_invalid"),
        ("exact", "wrong_backend", "retrieval_evidence_binding_invalid"),
        ("exact", "wrong_cutoff", "retrieval_evidence_binding_invalid"),
    ),
)
def test_wrong_case_retrieval_backend_and_cutoff_fail_closed(
    case_mode: str,
    retrieval_mode: str,
    match: str,
) -> None:
    suite = _suite()
    renderer, _, _, _ = _renderer(
        suite,
        case_mode=case_mode,
        retrieval_mode=retrieval_mode,
    )
    context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.ANSWER,
    )

    with pytest.raises(SchedulerRunnerError, match=match):
        renderer.render(context)


def test_cross_run_wrong_backend_and_dependency_calls_fail_closed() -> None:
    suite = _suite()
    renderer, _, _, _ = _renderer(suite)
    context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.JUDGE,
    )
    long_run = run_authority_from_suite(suite, run_index=1)
    cross_run = replace(context, run=long_run)
    wrong_backend = replace(context, call=replace(context.call, backend_role="mem0"))
    wrong_dependency = replace(
        context,
        call=replace(context.call, depends_on_logical_call_id=_sha("wrong-dependency")),
    )

    for bad_context in (cross_run, wrong_backend, wrong_dependency):
        with pytest.raises(SchedulerRunnerError):
            renderer.render(bad_context)


@pytest.mark.parametrize(
    "mode",
    ("ignored", "substituted_ciphertext", "cross_run", "cross_backend", "cross_case"),
)
def test_ignored_substituted_and_foreign_private_answers_fail_closed(mode: str) -> None:
    suite = _suite()
    renderer, _, _, decryptor = _renderer(suite, decrypt_mode=mode)
    context, ciphertext, capability = _context(
        suite,
        benchmark=SchedulerBenchmark.LONGMEMEVAL,
        backend_index=1,
        stage=SchedulerCallStage.JUDGE,
    )

    with pytest.raises(SchedulerRunnerError, match="private_answer_binding_invalid"):
        renderer.render(context)
    assert capability is not None and capability.was_read
    assert decryptor.last_ciphertext == ciphertext


def test_oversized_dependency_ciphertext_fails_before_decrypt() -> None:
    suite = _suite()
    renderer, _, _, decryptor = _renderer(suite)
    context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.JUDGE,
    )
    capability = SchedulerPrivateAnswerReadCapability(
        b"x" * (SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP + 1)
    )
    context = replace(context, dependency_answer_capability=capability)

    with pytest.raises(SchedulerRunnerError, match="private_answer_dependency_invalid"):
        renderer.render(context)
    assert capability.was_read
    assert decryptor.calls == 0


def test_private_material_is_absent_from_repr() -> None:
    suite = _suite()
    renderer, case_reader, retrieval_reader, decryptor = _renderer(suite)
    answer_context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.ANSWER,
    )
    rendered = renderer.render(answer_context)
    case_result = case_reader.read_exact(key=case_reader.last_key)
    retrieval_result = retrieval_reader.read_exact(key=retrieval_reader.last_key)
    judge_context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.JUDGE,
    )
    renderer.render(judge_context)
    private_answer = SchedulerDecryptedPrivateAnswer(
        context=decryptor.last_context,
        answer="SECRET-ANSWER-CANARY",
    )

    representations = "\n".join(
        repr(item)
        for item in (
            renderer,
            rendered,
            answer_context,
            case_result,
            retrieval_result,
            private_answer,
        )
    )
    for forbidden in (
        "GOLD-ONLY-CANARY",
        "SECRET-ANSWER-CANARY",
        "Alex chose Postgres via Infinity.",
        "Which database did Alex choose?",
    ):
        assert forbidden not in representations
    for private_dto in (case_result, retrieval_result, private_answer):
        with pytest.raises(TypeError, match="private material"):
            pickle.dumps(private_dto)


@pytest.mark.parametrize(
    "material",
    ("oversized_case", "noncanonical_case", "oversized_rag", "nan"),
)
def test_oversized_and_noncanonical_private_material_fails_closed(material: str) -> None:
    suite = _suite()
    renderer, case_reader, _, _ = _renderer(suite)
    context, _, _ = _context(
        suite,
        benchmark=SchedulerBenchmark.LOCOMO,
        backend_index=0,
        stage=SchedulerCallStage.ANSWER,
    )
    case_key = renderer._case_key(context.run, context.call)
    if material in {"oversized_case", "noncanonical_case"}:
        case = _official_case(case_key)
        if material == "oversized_case":
            case = replace(case, question="x" * (SCHEDULER_OFFICIAL_CASE_BYTES_CAP + 1))
        else:
            case = replace(case, metadata={"noncanonical": object()})
        with pytest.raises(SchedulerRunnerError):
            official_case_material_sha256(case_key, case)
        return
    case_read = case_reader.read_exact(key=case_key)
    retrieval_key = SchedulerRetrievalEvidenceKey(
        case_key=case_key,
        case_material_sha256=case_read.material_sha256,
        backend_index=0,
        backend_role="infinity-context",
        target_identity_sha256=context.call.target_identity_sha256,
        cutoff=SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
        authority_root_sha256=_RETRIEVAL_ROOT,
    )
    memories = (
        RetrievedMemory(
            text=(
                "x" * (SCHEDULER_RETRIEVAL_EVIDENCE_BYTES_CAP + 1)
                if material == "oversized_rag"
                else "valid"
            ),
            rank=1,
            score=float("nan") if material == "nan" else 1.0,
            metadata={},
        ),
    )
    with pytest.raises(SchedulerRunnerError):
        retrieval_evidence_material_sha256(retrieval_key, memories)


def test_fake_2040_case_manifest_traversal_keeps_reads_one_case_bounded() -> None:
    locomo_cases = _case_authorities("locomo", LOCOMO_PROFILE.case_count)
    longmemeval_cases = _case_authorities("longmemeval", LONGMEMEVAL_PROFILE.case_count)
    suite = _suite(
        manifests=(
            case_manifest_sha256(locomo_cases),
            case_manifest_sha256(longmemeval_cases),
        )
    )
    runs_and_cases = tuple(
        (run_authority_from_suite(suite, run_index=index), cases)
        for index, cases in enumerate((locomo_cases, longmemeval_cases))
    )
    manifests = tuple(
        build_scheduler_manifest(run, suite=suite, ordered_cases=cases)
        for run, cases in runs_and_cases
    )
    renderer, case_reader, retrieval_reader, decryptor = _renderer(suite)

    rendered_count = 0
    for (run, _), manifest in zip(runs_and_cases, manifests, strict=True):
        for shard in manifest.shards:
            assert len(shard.calls) <= 256
            for call in shard.calls:
                if call.stage is SchedulerCallStage.ANSWER and call.backend_index == 0:
                    renderer.render(
                        SchedulerRequestContext(
                            suite=suite,
                            run=run,
                            call=call,
                            dependency_answer_capability=None,
                        )
                    )
                    rendered_count += 1
    gc.collect()

    assert rendered_count == 2_040
    assert case_reader.calls == 2_040
    assert retrieval_reader.calls == 2_040
    assert decryptor.calls == 0
    assert case_reader.max_prior_live == 0
    assert not hasattr(renderer, "cases")
    assert not hasattr(renderer, "case_cache")
