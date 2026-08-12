"""Exact common-condition request rendering for the fresh-chain canary."""

from __future__ import annotations

import hashlib
from typing import Protocol, final

from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    canonical_openai_request_body,
)
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    Mem0OfficialPrompt,
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult, RetrievedMemory
from infinity_context_server.memory_comparison_response_format_policy import (
    locomo_judge_response_format,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase
from infinity_context_server.publishable_durable_scheduler.runner_official_request_renderer import (
    SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
    SCHEDULER_OFFICIAL_REQUEST_MODEL,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_ANSWER_CUTOFF,
)

from .authority import fresh_chain_static_authority_payload
from .contracts import (
    FRESH_CHAIN_CASE_ID,
    FreshChainCallResult,
    FreshChainCanaryError,
    FreshChainRetrievalHandoff,
    FreshChainStage,
    canonical_sha256,
)


class FreshChainInfinityRetrievalPort(Protocol):
    """Read the existing canonical Infinity evidence for the fixed case once."""

    def retrieve(self) -> tuple[RetrievedMemory, ...]: ...


class FreshChainMem0MemoryPort(Protocol):
    """Expose only HMAC-authenticated memories captured from the fresh lane."""

    @property
    def retrieved_memories(self) -> tuple[RetrievedMemory, ...]: ...


@final
class FreshChainOfficialRequestRenderer:
    """Reuse the pinned official prompts and common OpenAI request condition."""

    __slots__ = (
        "_case",
        "_common_condition_policy_sha256",
        "_extraction_body",
        "_infinity",
        "_infinity_memories",
        "_mem0",
        "_namespace_commitment_sha256",
        "_source_commitment_sha256",
    )

    def __init__(
        self,
        *,
        case: PublicBenchmarkCase,
        extraction_request_body: bytes,
        infinity_retrieval: FreshChainInfinityRetrievalPort,
        mem0_memories: FreshChainMem0MemoryPort,
        namespace_commitment_sha256: str,
        source_commitment_sha256: str,
    ) -> None:
        static = fresh_chain_static_authority_payload()
        evaluation = static.get("evaluation")
        common = evaluation.get("common_condition") if type(evaluation) is dict else None
        if (
            type(case) is not PublicBenchmarkCase
            or case.benchmark != "locomo"
            or case.case_id != FRESH_CHAIN_CASE_ID
            or type(extraction_request_body) is not bytes
            or not extraction_request_body
            or not callable(getattr(infinity_retrieval, "retrieve", None))
            or not hasattr(type(mem0_memories), "retrieved_memories")
            or not _sha(namespace_commitment_sha256)
            or not _sha(source_commitment_sha256)
            or type(common) is not dict
        ):
            _fail("fresh_chain_request_renderer_composition_invalid")
        self._case = case
        self._extraction_body = extraction_request_body
        self._infinity = infinity_retrieval
        self._mem0 = mem0_memories
        self._namespace_commitment_sha256 = namespace_commitment_sha256
        self._source_commitment_sha256 = source_commitment_sha256
        self._common_condition_policy_sha256 = canonical_sha256(common)
        self._infinity_memories: tuple[RetrievedMemory, ...] | None = None

    @property
    def common_condition_policy_sha256(self) -> str:
        return self._common_condition_policy_sha256

    def render(
        self,
        *,
        stage: FreshChainStage,
        prior_results: tuple[FreshChainCallResult, ...],
        retrieval_handoff: FreshChainRetrievalHandoff | None,
    ) -> bytes:
        if stage == "mem0_extraction":
            if prior_results or retrieval_handoff is not None:
                _fail("fresh_chain_request_render_order_invalid")
            return self._extraction_body
        if stage == "infinity_answer":
            memories = self._infinity_evidence()
            prompt = render_mem0_official_answer_prompt(self._case, memories)
            authority = _memory_authority(memories, role="infinity-context")
        elif stage == "infinity_judge":
            prompt = self._judge_prompt(prior_results, answer_ordinal=1)
            authority = prior_results[1].result_sha256
        elif stage == "mem0_answer":
            if type(retrieval_handoff) is not FreshChainRetrievalHandoff:
                _fail("fresh_chain_request_retrieval_missing")
            memories = self._mem0.retrieved_memories
            if (
                type(memories) is not tuple
                or not memories
                or len(memories) > SCHEDULER_OFFICIAL_ANSWER_CUTOFF
                or any(type(item) is not RetrievedMemory for item in memories)
            ):
                _fail("fresh_chain_request_retrieval_empty")
            prompt = render_mem0_official_answer_prompt(self._case, memories)
            authority = retrieval_handoff.retrieval_authority_sha256
        elif stage == "mem0_judge":
            prompt = self._judge_prompt(prior_results, answer_ordinal=3)
            authority = prior_results[3].result_sha256
        else:
            _fail("fresh_chain_request_stage_unknown")
        return _canonical_request(
            prompt,
            stage=stage,
            identity_nonce=canonical_sha256(
                {
                    "case_id": FRESH_CHAIN_CASE_ID,
                    "input_authority_sha256": authority,
                    "namespace_commitment_sha256": (self._namespace_commitment_sha256),
                    "prior_result_sha256": [item.result_sha256 for item in prior_results],
                    "schema_version": "memory-comparison-fresh-chain-request-nonce.v1",
                    "source_commitment_sha256": self._source_commitment_sha256,
                    "stage": stage,
                }
            ),
        )

    def _infinity_evidence(self) -> tuple[RetrievedMemory, ...]:
        if self._infinity_memories is None:
            try:
                observed = self._infinity.retrieve()
            except Exception:
                _fail("fresh_chain_infinity_retrieval_failed")
            if (
                type(observed) is not tuple
                or not observed
                or any(type(item) is not RetrievedMemory for item in observed)
                or len(observed) > SCHEDULER_OFFICIAL_ANSWER_CUTOFF
            ):
                _fail("fresh_chain_infinity_retrieval_invalid")
            self._infinity_memories = observed
        return self._infinity_memories

    def _judge_prompt(
        self,
        prior_results: tuple[FreshChainCallResult, ...],
        *,
        answer_ordinal: int,
    ) -> Mem0OfficialPrompt:
        if (
            len(prior_results) <= answer_ordinal
            or prior_results[answer_ordinal].ordinal != answer_ordinal
            or not prior_results[answer_ordinal].output_text
        ):
            _fail("fresh_chain_judge_dependency_invalid")
        try:
            return render_mem0_official_judge_prompt(
                self._case,
                AnswerResult(
                    answer=prior_results[answer_ordinal].output_text,
                    model=SCHEDULER_OFFICIAL_REQUEST_MODEL,
                ),
            )
        except Exception:
            _fail("fresh_chain_judge_prompt_render_failed")


def _canonical_request(
    prompt: Mem0OfficialPrompt,
    *,
    stage: FreshChainStage,
    identity_nonce: str,
) -> bytes:
    if type(prompt) is not Mem0OfficialPrompt or not prompt.user or not _sha(identity_nonce):
        _fail("fresh_chain_official_prompt_invalid")
    payload: dict[str, object] = {
        "max_tokens": SCHEDULER_OFFICIAL_REQUEST_MAX_OUTPUT_TOKENS,
        "messages": [
            {"content": prompt.system, "role": "system"},
            {"content": prompt.user, "role": "user"},
        ],
        "model": SCHEDULER_OFFICIAL_REQUEST_MODEL,
        "temperature": 0,
        "user": identity_nonce,
    }
    if stage in {"infinity_judge", "mem0_judge"}:
        payload["response_format"] = locomo_judge_response_format()
    try:
        encoded = canonical_openai_request_body(payload)
    except Exception:
        _fail("fresh_chain_official_request_invalid")
    if not encoded or len(encoded) > 4 * 1024 * 1024:
        _fail("fresh_chain_official_request_invalid")
    return encoded


def _memory_authority(
    memories: tuple[RetrievedMemory, ...],
    *,
    role: str,
) -> str:
    return canonical_sha256(
        {
            "memories": [
                {
                    "created_at": item.created_at,
                    "item_id": item.item_id,
                    "rank": item.rank,
                    "score": item.score,
                    "source_refs": list(item.source_refs),
                    "text_sha256": hashlib.sha256(item.text.encode()).hexdigest(),
                }
                for item in memories
            ],
            "role": role,
        }
    )


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "FreshChainInfinityRetrievalPort",
    "FreshChainOfficialRequestRenderer",
)
