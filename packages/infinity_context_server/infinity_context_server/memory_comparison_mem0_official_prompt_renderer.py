"""Provider-neutral rendering for pinned official mem0 benchmark prompts.

The prompt text is vendored from mem0ai/memory-benchmarks commit
4b61c5d31b9c668a12b4f5e78064248a02c82d2b under Apache-2.0. This adapter
preserves the upstream answer and judge call semantics while exposing no
provider transport dependency.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from infinity_context_server.memory_comparison_mem0_locomo_prompts import (
    ANSWERER_MEMORY_LIMIT as LOCOMO_ANSWERER_MEMORY_LIMIT,
)
from infinity_context_server.memory_comparison_mem0_locomo_prompts import (
    JUDGE_SYSTEM_PROMPT as LOCOMO_JUDGE_SYSTEM_PROMPT,
)
from infinity_context_server.memory_comparison_mem0_locomo_prompts import (
    get_answer_generation_prompt as _locomo_answer_prompt,
)
from infinity_context_server.memory_comparison_mem0_locomo_prompts import (
    get_judge_prompt as _locomo_judge_prompt,
)
from infinity_context_server.memory_comparison_mem0_locomo_prompts import (
    preprocess_answer as _preprocess_locomo_answer,
)
from infinity_context_server.memory_comparison_mem0_longmemeval_prompts import (
    get_answer_generation_prompt as _longmemeval_answer_prompt,
)
from infinity_context_server.memory_comparison_mem0_longmemeval_prompts import (
    get_judge_prompt as _longmemeval_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult, RetrievedMemory
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_LOCOMO = "locomo"
_LONGMEMEVAL = "longmemeval"
MEM0_BENCHMARK_UPSTREAM_COMMIT = "4b61c5d31b9c668a12b4f5e78064248a02c82d2b"
MEM0_OFFICIAL_PROMPT_POLICY = "mem0-official-qa-v1"
MEM0_OFFICIAL_MODEL = "gpt-5"
MEM0_OFFICIAL_PROMPT_FILE_SHA256 = {
    _LOCOMO: "8ebac1ef60e9ab5caf99079fdaac038b85472e81491ed35e2d2655f3927c76c2",
    _LONGMEMEVAL: "ba8cf60d26f1390ecbef0f07b3e950556fe3bc5a37ba4b5343f28217f18c144f",
}
_MEM_THINKING_RE = re.compile(
    r"[<\[]mem_thinking[>\]].*?[<\[]/mem_thinking[>\]]",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Mem0OfficialPrompt:
    """One provider-neutral chat request under the pinned prompt policy."""

    policy_id: str
    upstream_commit: str
    stage: str
    system: str
    user: str


@dataclass(frozen=True, slots=True)
class Mem0OfficialJudgeDecision:
    """Normalized official binary judgment."""

    correct: bool
    verdict: str


def render_mem0_official_answer_prompt(
    case: PublicBenchmarkCase,
    memories: Sequence[RetrievedMemory],
) -> Mem0OfficialPrompt:
    """Render the official answer request using raw memory text and timestamps only."""

    benchmark = _benchmark(case)
    raw_memories = _raw_memories(memories)
    if benchmark == _LOCOMO:
        user = _locomo_answer_prompt(
            case.question,
            raw_memories[:LOCOMO_ANSWERER_MEMORY_LIMIT],
            reference_date=_locomo_reference_date(case),
        )
    else:
        chronological = sorted(raw_memories, key=lambda item: item.get("created_at") or "")
        user = _longmemeval_answer_prompt(
            question=case.question,
            search_results=chronological,
            question_date=_longmemeval_question_date(case),
        )
    return _prompt(stage="answer", system="", user=user)


def normalize_mem0_official_answer(
    case: PublicBenchmarkCase,
    result: AnswerResult,
) -> AnswerResult:
    """Apply the exact upstream visible-answer cleanup before judging."""

    benchmark = _benchmark(case)
    answer = result.answer
    if benchmark == _LONGMEMEVAL:
        answer = _MEM_THINKING_RE.sub("", answer).strip()
    if "ANSWER:" in answer:
        answer = answer.rsplit("ANSWER:", 1)[-1].strip()
    return replace(
        result,
        answer=answer,
        metadata={
            **result.metadata,
            "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
            "prompt_upstream_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
        },
    )


def render_mem0_official_judge_prompt(
    case: PublicBenchmarkCase,
    answer_result: AnswerResult,
) -> Mem0OfficialPrompt:
    """Render the official no-evidence judge request for a normalized answer."""

    benchmark = _benchmark(case)
    response = normalize_mem0_official_answer(case, answer_result).answer
    ground_truth = _judge_ground_truth(case, benchmark=benchmark)
    if benchmark == _LOCOMO:
        category = _locomo_category(case)
        user = _locomo_judge_prompt(
            category,
            case.question,
            _preprocess_locomo_answer(category, ground_truth),
            response,
        )
        system = LOCOMO_JUDGE_SYSTEM_PROMPT
    else:
        user = _longmemeval_judge_prompt(
            question_type=_metadata_text(case, "question_type"),
            question_id=case.case_id,
            question=case.question,
            answer=ground_truth,
            response=response,
            question_date=_longmemeval_question_date(case),
        )
        system = ""
    return _prompt(stage="judge", system=system, user=user)


def parse_mem0_official_judge_response(
    case: PublicBenchmarkCase,
    raw: object,
) -> Mem0OfficialJudgeDecision:
    """Parse the official LoCoMo JSON or LongMemEval yes/no verdict semantics."""

    if _benchmark(case) == _LOCOMO:
        value = _json_mapping(raw)
        label = str(value.get("label") or "").upper() if value is not None else ""
        correct = label == "CORRECT"
        return Mem0OfficialJudgeDecision(
            correct=correct,
            verdict="CORRECT" if correct else "WRONG",
        )
    correct = _parse_longmemeval_yes_no(str(raw) if raw is not None else "")
    return Mem0OfficialJudgeDecision(
        correct=correct,
        verdict="PASS" if correct else "FAIL",
    )


def _prompt(*, stage: str, system: str, user: str) -> Mem0OfficialPrompt:
    return Mem0OfficialPrompt(
        policy_id=MEM0_OFFICIAL_PROMPT_POLICY,
        upstream_commit=MEM0_BENCHMARK_UPSTREAM_COMMIT,
        stage=stage,
        system=system,
        user=user,
    )


def _benchmark(case: PublicBenchmarkCase) -> str:
    benchmark = case.benchmark.strip().casefold()
    if benchmark not in {_LOCOMO, _LONGMEMEVAL}:
        raise ValueError(f"Unsupported official mem0 prompt benchmark: {case.benchmark}")
    return benchmark


def _raw_memories(memories: Sequence[RetrievedMemory]) -> list[dict[str, str]]:
    return [
        {
            "memory": memory.text,
            "created_at": memory.created_at or "",
        }
        for memory in memories
    ]


def _judge_ground_truth(case: PublicBenchmarkCase, *, benchmark: str) -> str:
    evaluator_value = case.metadata.get("_evaluator_ground_truth")
    if evaluator_value is not None and str(evaluator_value).strip():
        return str(evaluator_value)
    if benchmark == _LOCOMO:
        raise ValueError(
            "official LoCoMo judge requires exact _evaluator_ground_truth metadata"
        )
    for key in ("ground_truth_answer", "answer"):
        value = case.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    preview = case.metadata.get("answer_preview")
    if isinstance(preview, str) and preview.strip():
        return preview
    return " | ".join(case.expected_terms)


def _locomo_category(case: PublicBenchmarkCase) -> int:
    value = case.metadata.get("category", case.metadata.get("locomo_category", 0))
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _locomo_reference_date(case: PublicBenchmarkCase) -> str:
    for key in ("reference_date_human", "reference_date"):
        value = _metadata_text(case, key)
        if value:
            return value
    dated_sessions: list[tuple[datetime, str]] = []
    for memory in case.memories:
        raw = str(memory.metadata.get("session_date") or "").strip()
        for date_format in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
            try:
                parsed = datetime.strptime(raw, date_format)
            except (TypeError, ValueError):
                continue
            dated_sessions.append((parsed, raw))
            break
    if dated_sessions:
        return max(dated_sessions, key=lambda item: item[0])[1]
    return "2023"


def _longmemeval_question_date(case: PublicBenchmarkCase) -> str:
    raw = _metadata_text(case, "question_date")
    if not raw:
        return ""
    try:
        cleaned = re.sub(r"\s*\([A-Za-z]+\)\s*", " ", raw).strip()
        parsed = datetime.strptime(cleaned, "%Y/%m/%d %H:%M")
    except (TypeError, ValueError):
        return raw
    return parsed.strftime("%A, %B %d, %Y")


def _metadata_text(case: PublicBenchmarkCase, key: str) -> str:
    value = case.metadata.get(key)
    return str(value).strip() if value is not None else ""


def _json_mapping(raw: object) -> Mapping[str, object] | None:
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _parse_longmemeval_yes_no(raw: str) -> bool:
    text = raw.strip()
    if not text:
        return False
    after_cot = re.split(r"</judge_thinking>|</thinking>", text, flags=re.IGNORECASE)
    verdict_region = after_cot[-1].strip() if after_cot else text
    verdict_lines = [line.strip().lower() for line in verdict_region.splitlines() if line.strip()]
    for line in reversed(verdict_lines):
        if line == "yes":
            return True
        if line == "no":
            return False
    token_matches = re.findall(r"\b(yes|no)\b", verdict_region.lower())
    if token_matches:
        return token_matches[-1] == "yes"
    return text.lower().startswith("yes")


__all__ = (
    "MEM0_BENCHMARK_UPSTREAM_COMMIT",
    "MEM0_OFFICIAL_MODEL",
    "MEM0_OFFICIAL_PROMPT_FILE_SHA256",
    "MEM0_OFFICIAL_PROMPT_POLICY",
    "Mem0OfficialJudgeDecision",
    "Mem0OfficialPrompt",
    "normalize_mem0_official_answer",
    "parse_mem0_official_judge_response",
    "render_mem0_official_answer_prompt",
    "render_mem0_official_judge_prompt",
)
