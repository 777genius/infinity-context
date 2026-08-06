"""Prompt rendering and provider-dispatch helpers for managed execution."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import replace
from typing import final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    GoldBlindEvidence,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindJudgeResult,
)
from infinity_context_server.memory_comparison_managed_http_execution import (
    ManagedComparisonHttpExecutionAdapter,
    ManagedHttpRetrievalResult,
)
from infinity_context_server.memory_comparison_managed_provider_calls import (
    ManagedProviderCallOutcome,
    ManagedProviderLaneTransport,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
)
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    normalize_mem0_official_answer,
    parse_mem0_official_judge_response,
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult, RetrievedMemory
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_MAX_OUTPUT_TOKENS = 4096


class ManagedLlmExecutionError(RuntimeError):
    """Fixed-code failure that never contains prompts, gold, or provider text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedRetrievalDispatchPort:
    __slots__ = (
        "_backend_role",
        "_case",
        "_expected_case_id",
        "_http",
        "_query",
        "_result",
        "_run_id",
        "_target",
    )

    def __init__(
        self,
        *,
        http: ManagedComparisonHttpExecutionAdapter,
        run_id: str,
        backend_role: str,
        target: str,
        case: ManagedRunCase,
        query: ManagedAnswerCase,
        expected_case_id: str,
    ) -> None:
        self._http = http
        self._run_id = run_id
        self._backend_role = backend_role
        self._target = target
        self._case = case
        self._query = query
        self._expected_case_id = expected_case_id
        self._result: ManagedHttpRetrievalResult | None = None

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        if (
            type(request) is not dict
            or request.get("case_id") != self._expected_case_id
            or request.get("question") != self._query.question
            or run_id != self._run_id
            or top_k != self._http.retrieval_top_k
            or self._result is not None
        ):
            raise ManagedLlmExecutionError("managed_retrieval_dispatch_invalid")
        result = self._http.retrieve(
            run_id=run_id,
            backend_role=self._backend_role,
            target_identity_sha256=self._target,
            case=self._case,
            query=self._query,
        )
        if type(result) is not ManagedHttpRetrievalResult:
            raise ManagedLlmExecutionError("managed_retrieval_result_invalid")
        self._result = result
        return result.evidence

    def take_result(self) -> ManagedHttpRetrievalResult:
        result = self._result
        self._result = None
        if type(result) is not ManagedHttpRetrievalResult:
            raise ManagedLlmExecutionError("managed_retrieval_result_missing")
        return result


@final
class ManagedAnswerDispatchPort:
    __slots__ = ("_case", "_evidence", "_lane", "_outcome")

    def __init__(
        self,
        *,
        case: PublicBenchmarkCase,
        evidence: tuple[GoldBlindEvidence, ...],
        lane: ManagedProviderLaneTransport,
    ) -> None:
        self._case = case
        self._evidence = evidence
        self._lane = lane
        self._outcome: ManagedProviderCallOutcome | None = None

    def answer(self, request: Mapping[str, object]) -> object:
        if (
            type(request) is not dict
            or request.get("question") != self._case.question
            or self._outcome is not None
        ):
            raise ManagedLlmExecutionError("managed_answer_dispatch_invalid")
        memories = tuple(
            RetrievedMemory(
                text=item.text,
                rank=item.rank,
                item_id=item.item_id,
                created_at=item.created_at,
            )
            for item in self._evidence
        )
        prompt = render_mem0_official_answer_prompt(self._case, memories)
        outcome = self._lane.complete(
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0,
            retries=0,
        )
        normalized = normalize_mem0_official_answer(
            self._case,
            AnswerResult(answer=outcome.completion.text, model=outcome.binding.model),
        )
        self._outcome = outcome
        return {"answer": normalized.answer}

    def take_outcome(self) -> ManagedProviderCallOutcome:
        outcome = self._outcome
        self._outcome = None
        if type(outcome) is not ManagedProviderCallOutcome:
            raise ManagedLlmExecutionError("managed_answer_outcome_missing")
        return outcome


@final
class ManagedStatefulJudge:
    __slots__ = ("_case", "_lane", "_lock", "_outcome", "_phase", "_result")

    def __init__(
        self,
        *,
        case: PublicBenchmarkCase,
        lane: ManagedProviderLaneTransport,
    ) -> None:
        self._case = case
        self._lane = lane
        self._lock = threading.Lock()
        self._outcome: ManagedProviderCallOutcome | None = None
        self._result: GoldBlindJudgeResult | None = None
        self._phase = "issued"

    def invoke(
        self,
        candidate_answer: object,
        ground_truth: object,
        expected_terms: tuple[str, ...],
        forbidden_terms: tuple[str, ...],
    ) -> GoldBlindJudgeResult:
        with self._lock:
            if self._phase != "issued":
                raise ManagedLlmExecutionError("managed_judge_state_terminal")
            self._phase = "active"
        if not isinstance(candidate_answer, Mapping):
            raise ManagedLlmExecutionError("managed_judge_candidate_invalid")
        answer = candidate_answer.get("answer")
        if type(answer) is not str:
            raise ManagedLlmExecutionError("managed_judge_candidate_invalid")
        judge_case = replace(
            self._case,
            expected_terms=expected_terms,
            forbidden_terms=forbidden_terms,
            metadata={
                **dict(self._case.metadata),
                "_evaluator_ground_truth": ground_truth,
            },
        )
        prompt = render_mem0_official_judge_prompt(
            judge_case,
            AnswerResult(answer=answer, model=self._lane.binding.model),
        )
        outcome = self._lane.complete(
            system_prompt=prompt.system,
            user_prompt=prompt.user,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
            temperature=0,
            response_format=(
                locomo_judge_response_format()
                if judge_case.benchmark == "locomo"
                else None
            ),
            retries=0,
        )
        decision = parse_mem0_official_judge_response(judge_case, outcome.completion.text)
        result = GoldBlindJudgeResult(
            verdict="correct" if decision.correct else "incorrect",
            score=1.0 if decision.correct else 0.0,
        )
        with self._lock:
            self._outcome = outcome
            self._result = result
            self._phase = "complete"
        return result

    def take(self) -> tuple[ManagedProviderCallOutcome, GoldBlindJudgeResult]:
        with self._lock:
            outcome, result = self._outcome, self._result
            self._outcome = None
            self._result = None
            self._phase = "consumed"
        if (
            type(outcome) is not ManagedProviderCallOutcome
            or type(result) is not GoldBlindJudgeResult
        ):
            raise ManagedLlmExecutionError("managed_judge_outcome_missing")
        return outcome, result


def invoke_managed_stateful_judge(
    state: object,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    """Closure-free invoker; the capability validator forbids global loads."""

    return state.invoke(candidate_answer, ground_truth, expected_terms, forbidden_terms)


__all__ = (
    "ManagedAnswerDispatchPort",
    "ManagedLlmExecutionError",
    "ManagedRetrievalDispatchPort",
    "ManagedStatefulJudge",
    "invoke_managed_stateful_judge",
)
