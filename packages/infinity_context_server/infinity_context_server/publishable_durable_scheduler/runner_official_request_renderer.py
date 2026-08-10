"""Provider-free official answer/judge request renderer for scheduler v4."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    canonical_openai_request_body,
)
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    MEM0_BENCHMARK_UPSTREAM_COMMIT,
    MEM0_OFFICIAL_PROMPT_FILE_SHA256,
    MEM0_OFFICIAL_PROMPT_POLICY,
    Mem0OfficialPrompt,
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
    PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
    publishable_priority_methodology_v4,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_COMPARISON_BACKENDS,
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format,
    locomo_judge_response_format_policy_sha256,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerBenchmark,
    SchedulerCallStage,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    canonical_json,
    commitment,
    require_run_authority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    RUNNER_REQUEST_BYTES_CAP,
    SchedulerRenderedRequest,
    SchedulerRequestContext,
    SchedulerRunnerError,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
    SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
    SchedulerAuthenticatedOfficialCase,
    SchedulerAuthenticatedRetrievalEvidence,
    SchedulerDecryptedPrivateAnswer,
    SchedulerOfficialCaseKey,
    SchedulerOfficialRendererComposition,
    SchedulerPrivateAnswerDecryptContext,
    SchedulerRetrievalEvidenceKey,
    official_case_material_sha256,
    retrieval_evidence_material_sha256,
)

SCHEDULER_OFFICIAL_REQUEST_RENDERER_SCHEMA_VERSION = (
    "memory-comparison-publishable-official-request-renderer.v2"
)
SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_CONTRACT = (
    "provider-free-mem0-official-answer-judge-openai-chat.v2"
)
SCHEDULER_OFFICIAL_REQUEST_MODEL = "gpt-5.6-sol"
SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT = "high"
SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER = "priority"
SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS = 4096
SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP = 4 * 1024 * 1024

_IMPLEMENTATION_CONTRACT_MATERIAL = {
    "answer_inputs": "exact_authenticated_case_and_backend_retrieval_only",
    "canonical_json": "utf8-unescaped-sort-keys-no-whitespace-no-nan",
    "dependency": "exact_runner_ciphertext_sha256_and_authenticated_decrypt",
    "empty_system_message": "preserved",
    "gold_blind_answer": True,
    "judge_evidence": False,
    "one_case_read_per_render": True,
    "provider_io": False,
    "runtime_boot_fields_omitted_from_request": [
        "reasoning_effort",
        "service_tier",
    ],
    "runtime_selection_proof": "signed-runtime-attestation-v2",
    "schema_version": SCHEDULER_OFFICIAL_REQUEST_RENDERER_SCHEMA_VERSION,
}
SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_SHA256 = commitment(
    "official-request-renderer-implementation",
    _IMPLEMENTATION_CONTRACT_MATERIAL,
)


@final
@dataclass(frozen=True, slots=True)
class SchedulerOfficialRequestPolicy:
    """Immutable reviewed policy bound by the resumable runner and receipts."""

    suite_authority_sha256: str
    ordered_run_authority_sha256: tuple[str, str]
    case_authority_root_sha256: str
    retrieval_authority_root_sha256: str
    decrypt_policy_sha256: str
    renderer_policy_sha256: str = field(init=False)
    private_answer_policy_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.ordered_run_authority_sha256) is not tuple
            or len(self.ordered_run_authority_sha256) != 2
        ):
            _fail("scheduler_official_request_policy_invalid")
        values = (
            self.suite_authority_sha256,
            *self.ordered_run_authority_sha256,
            self.case_authority_root_sha256,
            self.retrieval_authority_root_sha256,
            self.decrypt_policy_sha256,
        )
        if any(not _is_sha256(value) for value in values):
            _fail("scheduler_official_request_policy_invalid")
        material = self.material()
        object.__setattr__(
            self,
            "renderer_policy_sha256",
            commitment("official-request-renderer-policy", material),
        )
        object.__setattr__(
            self,
            "private_answer_policy_sha256",
            commitment(
                "official-private-answer-policy",
                {
                    "binding": "suite-run-case-backend-dependency-ciphertext-sha256",
                    "ciphertext_bytes_cap": SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
                    "decrypt_policy_sha256": self.decrypt_policy_sha256,
                    "implementation_contract_sha256": (
                        SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_SHA256
                    ),
                    "publishable_profile_sha256": (
                        PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
                    ),
                    "schema_version": SCHEDULER_OFFICIAL_REQUEST_RENDERER_SCHEMA_VERSION,
                    "suite_authority_sha256": self.suite_authority_sha256,
                },
            ),
        )

    def material(self) -> dict[str, object]:
        return {
            "authorities": {
                "case_authority_root_sha256": self.case_authority_root_sha256,
                "decrypt_policy_sha256": self.decrypt_policy_sha256,
                "ordered_run_authority_sha256": list(self.ordered_run_authority_sha256),
                "retrieval_authority_root_sha256": self.retrieval_authority_root_sha256,
                "suite_authority_sha256": self.suite_authority_sha256,
            },
            "implementation": {
                "contract": SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_CONTRACT,
                "contract_material": dict(_IMPLEMENTATION_CONTRACT_MATERIAL),
                "contract_sha256": SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_SHA256,
            },
            "methodology": {
                "commitment_sha256": (PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256),
                "methodology_id": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
            },
            "profile": {
                "commitment_sha256": PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
                "profile_id": PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            },
            "prompt_renderer": {
                "file_sha256": {
                    "locomo": MEM0_OFFICIAL_PROMPT_FILE_SHA256["locomo"],
                    "longmemeval": MEM0_OFFICIAL_PROMPT_FILE_SHA256["longmemeval"],
                },
                "policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
                "upstream_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
            },
            "request": {
                "answer_cutoff": SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
                "max_output_tokens": SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
                "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
                "response_format": {
                    "answer": None,
                    "judge": {
                        "locomo": locomo_judge_response_format(),
                        "longmemeval": None,
                    },
                    "locomo_normalization_policy_sha256": (
                        locomo_judge_response_format_policy_sha256()
                    ),
                },
                "temperature": 0,
            },
            "runtime_boot": {
                "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
                "reasoning_effort": SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT,
                "service_tier": SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER,
            },
            "schema_version": SCHEDULER_OFFICIAL_REQUEST_RENDERER_SCHEMA_VERSION,
        }


@final
class PublishableOfficialRequestRenderer:
    """Render exact official answer/judge requests without provider I/O."""

    __slots__ = ("_composition", "_policy", "_suite", "_suite_snapshot")

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        composition: SchedulerOfficialRendererComposition,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(composition) is not SchedulerOfficialRendererComposition
        ):
            _fail("scheduler_official_renderer_initialization_invalid")
        composition.validate_current()
        runs = _validate_bound_suite(suite)
        self._suite = suite
        self._suite_snapshot = canonical_json(suite.material())
        self._composition = composition
        self._policy = SchedulerOfficialRequestPolicy(
            suite_authority_sha256=suite.commitment_sha256,
            ordered_run_authority_sha256=tuple(item.commitment_sha256 for item in runs),
            case_authority_root_sha256=composition.case_authority_root_sha256,
            retrieval_authority_root_sha256=composition.retrieval_authority_root_sha256,
            decrypt_policy_sha256=composition.private_output_decrypt_policy_sha256,
        )

    @property
    def policy(self) -> SchedulerOfficialRequestPolicy:
        return self._policy

    @property
    def renderer_policy_sha256(self) -> str:
        return self._policy.renderer_policy_sha256

    @property
    def private_answer_policy_sha256(self) -> str:
        return self._policy.private_answer_policy_sha256

    def __repr__(self) -> str:
        return (
            "PublishableOfficialRequestRenderer("
            f"renderer_policy_sha256={self.renderer_policy_sha256!r}, "
            f"private_answer_policy_sha256={self.private_answer_policy_sha256!r}, "
            "private_ports=<bound>)"
        )

    def render(self, context: SchedulerRequestContext) -> SchedulerRenderedRequest:
        self._composition.validate_current()
        run, call = self._validate_context(context)
        case_key = self._case_key(run, call)
        case_read = self._read_case(case_key)
        dependency_sha256: str | None = None
        retrieval_read: SchedulerAuthenticatedRetrievalEvidence | None = None
        if call.stage is SchedulerCallStage.ANSWER:
            retrieval_read = self._read_retrieval(run, call, case_read)
            prompt = _render_answer(case_read, retrieval_read)
        else:
            answer, dependency_sha256 = self._decrypt_answer(context, case_key, call)
            prompt = _render_judge(case_read, answer)
        payload = _request_payload(prompt, benchmark=case_key.benchmark, stage=call.stage)
        encoded = _canonical_request_bytes(payload)
        self._revalidate_private_reads(case_read, retrieval_read)
        return SchedulerRenderedRequest(
            renderer_policy_sha256=self.renderer_policy_sha256,
            private_answer_policy_sha256=self.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=dependency_sha256,
            payload=encoded,
        )

    def _validate_context(
        self,
        context: SchedulerRequestContext,
    ) -> tuple[SchedulerRunAuthority, SchedulerLogicalCall]:
        if type(context) is not SchedulerRequestContext:
            _fail("scheduler_official_request_context_invalid")
        context.__post_init__()
        if (
            context.suite != self._suite
            or canonical_json(context.suite.material()) != self._suite_snapshot
            or context.suite.commitment_sha256 != self._policy.suite_authority_sha256
        ):
            _fail("scheduler_official_request_suite_binding_invalid")
        try:
            run = require_run_authority(context.suite, context.run)
        except Exception:
            _fail("scheduler_official_request_run_binding_invalid")
        if run.commitment_sha256 != self._policy.ordered_run_authority_sha256[run.run_index]:
            _fail("scheduler_official_request_run_binding_invalid")
        call = context.call
        if type(call) is not SchedulerLogicalCall:
            _fail("scheduler_official_request_call_binding_invalid")
        expected_backend = run.binding.backends[call.backend_index]
        expected_profile = (
            LOCOMO_PROFILE
            if run.binding.profile.benchmark is SchedulerBenchmark.LOCOMO
            else LONGMEMEVAL_PROFILE
        )
        if (
            call.suite_authority_sha256 != context.suite.commitment_sha256
            or call.run_authority_sha256 != run.commitment_sha256
            or call.run_id != run.binding.run_id
            or call.case_index >= run.binding.profile.case_count
            or call.backend_role != expected_backend.backend_role
            or call.target_identity_sha256 != expected_backend.target_identity_sha256
            or call.token_ceiling != SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            or run.binding.profile != expected_profile
            or call.logical_call_id != commitment("logical-call", call.identity_material())
        ):
            _fail("scheduler_official_request_call_binding_invalid")
        _validate_dependency_call(run, call)
        return run, call

    def _case_key(
        self,
        run: SchedulerRunAuthority,
        call: SchedulerLogicalCall,
    ) -> SchedulerOfficialCaseKey:
        return SchedulerOfficialCaseKey(
            suite_authority_sha256=self._suite.commitment_sha256,
            run_authority_sha256=run.commitment_sha256,
            run_binding_commitment_sha256=run.binding.binding_commitment_sha256,
            run_id=run.binding.run_id,
            benchmark=run.binding.profile.benchmark,
            scheduler_profile_id=run.binding.profile.profile_id,
            publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
            publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
            methodology_sha256=PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
            dataset_sha256=run.binding.dataset_sha256,
            case_manifest_sha256=run.binding.case_manifest_sha256,
            case_index=call.case_index,
            case_id=call.case_id,
            case_alias=call.case_alias,
            authority_root_sha256=self._policy.case_authority_root_sha256,
        )

    def _read_case(
        self,
        key: SchedulerOfficialCaseKey,
    ) -> SchedulerAuthenticatedOfficialCase:
        try:
            result = self._composition.case_reader.read_exact(key=key)
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_official_case_read_failed")
        if type(result) is not SchedulerAuthenticatedOfficialCase or result.key != key:
            _fail("scheduler_official_case_binding_invalid")
        result.__post_init__()
        return result

    def _read_retrieval(
        self,
        run: SchedulerRunAuthority,
        call: SchedulerLogicalCall,
        case_read: SchedulerAuthenticatedOfficialCase,
    ) -> SchedulerAuthenticatedRetrievalEvidence:
        key = SchedulerRetrievalEvidenceKey(
            case_key=case_read.key,
            case_material_sha256=case_read.material_sha256,
            backend_index=call.backend_index,
            backend_role=call.backend_role,
            target_identity_sha256=run.binding.backends[call.backend_index].target_identity_sha256,
            cutoff=SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
            authority_root_sha256=self._policy.retrieval_authority_root_sha256,
        )
        try:
            result = self._composition.retrieval_reader.read_exact(key=key)
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_retrieval_evidence_read_failed")
        if type(result) is not SchedulerAuthenticatedRetrievalEvidence or result.key != key:
            _fail("scheduler_retrieval_evidence_binding_invalid")
        result.__post_init__()
        return result

    def _decrypt_answer(
        self,
        context: SchedulerRequestContext,
        case_key: SchedulerOfficialCaseKey,
        call: SchedulerLogicalCall,
    ) -> tuple[SchedulerDecryptedPrivateAnswer, str]:
        expected_sha256 = context.dependency_answer_ciphertext_sha256
        if not _is_sha256(expected_sha256):
            _fail("scheduler_private_answer_dependency_invalid")
        ciphertext = context.dependency_answer_ciphertext
        if (
            type(ciphertext) is not bytes
            or not ciphertext
            or len(ciphertext) > SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP
            or hashlib.sha256(ciphertext).hexdigest() != expected_sha256
            or call.depends_on_logical_call_id is None
        ):
            _fail("scheduler_private_answer_dependency_invalid")
        decrypt_context = SchedulerPrivateAnswerDecryptContext(
            case_key=case_key,
            backend_index=call.backend_index,
            backend_role=call.backend_role,
            target_identity_sha256=call.target_identity_sha256,
            answer_logical_call_id=call.depends_on_logical_call_id,
            judge_logical_call_id=call.logical_call_id,
            ciphertext_sha256=expected_sha256,
            decrypt_policy_sha256=self._policy.decrypt_policy_sha256,
        )
        try:
            result = self._composition.private_output_decryptor.decrypt_exact(
                ciphertext,
                context=decrypt_context,
            )
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_private_answer_decrypt_failed")
        if type(result) is not SchedulerDecryptedPrivateAnswer or result.context != decrypt_context:
            _fail("scheduler_private_answer_binding_invalid")
        result.__post_init__()
        return result, expected_sha256

    @staticmethod
    def _revalidate_private_reads(
        case_read: SchedulerAuthenticatedOfficialCase,
        retrieval_read: SchedulerAuthenticatedRetrievalEvidence | None,
    ) -> None:
        if (
            official_case_material_sha256(case_read.key, case_read.case)
            != case_read.material_sha256
        ):
            _fail("scheduler_official_case_material_changed")
        if retrieval_read is not None and (
            retrieval_evidence_material_sha256(retrieval_read.key, retrieval_read.memories)
            != retrieval_read.material_sha256
        ):
            _fail("scheduler_retrieval_evidence_material_changed")


def _validate_bound_suite(
    suite: SchedulerSuiteAuthority,
) -> tuple[SchedulerRunAuthority, SchedulerRunAuthority]:
    if type(suite) is not SchedulerSuiteAuthority:
        _fail("scheduler_official_request_suite_binding_invalid")
    try:
        profile = publishable_priority_comparison_profile_v4()
        methodology = publishable_priority_methodology_v4()
        public_profile = public_publishable_comparison_profile(profile)
        expected_profiles = (LOCOMO_PROFILE, LONGMEMEVAL_PROFILE)
        runs = (
            run_authority_from_suite(suite, run_index=0),
            run_authority_from_suite(suite, run_index=1),
        )
    except Exception:
        _fail("scheduler_official_request_profile_invalid")
    if (
        profile.profile_id != PUBLISHABLE_PRIORITY_PROFILE_V4_ID
        or profile.commitment_sha256 != PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
        or methodology.profile_id != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID
        or methodology.commitment_sha256 != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        or methodology["required_model"] != SCHEDULER_OFFICIAL_REQUEST_MODEL
        or methodology["required_reasoning_effort"] != SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT
        or methodology["required_service_tier"] != SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER
        or methodology["generation"]["answer"]["requested_max_output_tokens"]
        != SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
        or methodology["generation"]["judge"]["requested_max_output_tokens"]
        != SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
        or PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS != SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
        or suite.methodology_sha256 != PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256
        or canonical_json(suite.material()) == b""
        or suite.commitment_sha256 != commitment("suite", suite.material())
    ):
        _fail("scheduler_official_request_profile_invalid")
    for binding, expected_profile in zip(
        suite.ordered_runs,
        expected_profiles,
        strict=True,
    ):
        benchmark = expected_profile.benchmark.value
        spec = public_profile["benchmarks"][benchmark]
        limits = binding.limits
        if (
            binding.profile != expected_profile
            or binding.dataset_sha256 != spec["dataset_sha256"]
            or tuple(item.backend_role for item in binding.backends)
            != PUBLISHABLE_COMPARISON_BACKENDS
            or limits.answer_max_output_tokens != SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            or limits.judge_max_output_tokens != SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
            or limits.run_token_ceiling
            != expected_profile.case_count * 4 * SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS
        ):
            _fail("scheduler_official_request_profile_invalid")
    return runs


def _validate_dependency_call(
    run: SchedulerRunAuthority,
    call: SchedulerLogicalCall,
) -> None:
    if call.stage is SchedulerCallStage.ANSWER:
        if call.depends_on_logical_call_id is not None:
            _fail("scheduler_official_request_dependency_binding_invalid")
        return
    answer = SchedulerLogicalCall(
        suite_authority_sha256=call.suite_authority_sha256,
        run_authority_sha256=call.run_authority_sha256,
        run_id=call.run_id,
        case_index=call.case_index,
        case_id=call.case_id,
        case_alias=call.case_alias,
        backend_index=call.backend_index,
        backend_role=call.backend_role,
        target_identity_sha256=call.target_identity_sha256,
        stage=SchedulerCallStage.ANSWER,
        ordinal=call.ordinal - 1,
        shard_index=(call.ordinal - 1) // 256,
        token_ceiling=run.binding.limits.answer_max_output_tokens,
        depends_on_logical_call_id=None,
    )
    if call.depends_on_logical_call_id != answer.logical_call_id:
        _fail("scheduler_official_request_dependency_binding_invalid")


def _render_answer(
    case_read: SchedulerAuthenticatedOfficialCase,
    retrieval_read: SchedulerAuthenticatedRetrievalEvidence,
) -> Mem0OfficialPrompt:
    try:
        prompt = render_mem0_official_answer_prompt(
            case_read.case,
            retrieval_read.memories,
        )
    except Exception:
        _fail("scheduler_official_answer_prompt_render_failed")
    return _validate_prompt(prompt, stage=SchedulerCallStage.ANSWER)


def _render_judge(
    case_read: SchedulerAuthenticatedOfficialCase,
    answer: SchedulerDecryptedPrivateAnswer,
) -> Mem0OfficialPrompt:
    try:
        prompt = render_mem0_official_judge_prompt(
            case_read.case,
            AnswerResult(answer=answer.answer, model=SCHEDULER_OFFICIAL_REQUEST_MODEL),
        )
    except Exception:
        _fail("scheduler_official_judge_prompt_render_failed")
    return _validate_prompt(prompt, stage=SchedulerCallStage.JUDGE)


def _validate_prompt(
    prompt: object,
    *,
    stage: SchedulerCallStage,
) -> Mem0OfficialPrompt:
    if (
        type(prompt) is not Mem0OfficialPrompt
        or prompt.policy_id != MEM0_OFFICIAL_PROMPT_POLICY
        or prompt.upstream_commit != MEM0_BENCHMARK_UPSTREAM_COMMIT
        or prompt.stage != stage.value
        or type(prompt.system) is not str
        or type(prompt.user) is not str
        or not prompt.user
    ):
        _fail("scheduler_official_prompt_policy_invalid")
    return prompt


def _request_payload(
    prompt: Mem0OfficialPrompt,
    *,
    benchmark: SchedulerBenchmark,
    stage: SchedulerCallStage,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "max_tokens": PUBLISHABLE_REQUESTED_MAX_OUTPUT_TOKENS,
        "messages": [
            {"content": prompt.system, "role": "system"},
            {"content": prompt.user, "role": "user"},
        ],
        "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
        "temperature": 0,
    }
    if stage is SchedulerCallStage.JUDGE and benchmark is SchedulerBenchmark.LOCOMO:
        payload["response_format"] = locomo_judge_response_format()
    return payload


def _canonical_request_bytes(payload: dict[str, object]) -> bytes:
    try:
        encoded = canonical_openai_request_body(payload)
        decoded = json.loads(
            encoded,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        _fail("scheduler_official_request_noncanonical")
    if (
        not encoded
        or len(encoded) > SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP
        or len(encoded) > RUNNER_REQUEST_BYTES_CAP
        or type(decoded) is not dict
        or canonical_openai_request_body(decoded) != encoded
    ):
        _fail("scheduler_official_request_too_large_or_noncanonical")
    return encoded


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON number")


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256",
    "PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID",
    "PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256",
    "PUBLISHABLE_PRIORITY_PROFILE_V4_ID",
    "PublishableOfficialRequestRenderer",
    "SCHEDULER_OFFICIAL_REQUEST_BYTES_CAP",
    "SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_CONTRACT",
    "SCHEDULER_OFFICIAL_REQUEST_IMPLEMENTATION_SHA256",
    "SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS",
    "SCHEDULER_OFFICIAL_REQUEST_MODEL",
    "SCHEDULER_OFFICIAL_REQUEST_REASONING_EFFORT",
    "SCHEDULER_OFFICIAL_REQUEST_RENDERER_SCHEMA_VERSION",
    "SCHEDULER_OFFICIAL_REQUEST_SERVICE_TIER",
    "SchedulerOfficialRequestPolicy",
)
