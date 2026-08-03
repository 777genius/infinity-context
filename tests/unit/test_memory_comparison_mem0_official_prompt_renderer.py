from __future__ import annotations

from hashlib import sha256

import pytest
from infinity_context_server.memory_comparison_mem0_official_prompt_renderer import (
    MEM0_BENCHMARK_UPSTREAM_COMMIT,
    MEM0_OFFICIAL_PROMPT_POLICY,
    normalize_mem0_official_answer,
    parse_mem0_official_judge_response,
    render_mem0_official_answer_prompt,
    render_mem0_official_judge_prompt,
)
from infinity_context_server.memory_comparison_models import AnswerResult, RetrievedMemory
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)

_LOCOMO_ANSWER_SHA256 = "90d2bfa485531ca298b6827143416d8364dd62039ba5a22aaf4c8970e1f8cb97"
_LOCOMO_JUDGE_SHA256 = "117c44312b443c8ff6604c7ae059b0a306df20737678826862ae7ac6a2665d2f"
_LONGMEMEVAL_ANSWER_SHA256 = "a7704f5c276ec238c9e751bd00f085079cfae83aa7b8854ee1462c82f532c56f"
_LONGMEMEVAL_JUDGE_SHA256 = "68a083fb4f337358a7394d7b8773c4b429a6c1d704f070435c8fb0c4beea2bd0"


def test_locomo_official_answer_and_no_evidence_judge_snapshots() -> None:
    case = _locomo_case()
    memories = (
        RetrievedMemory(
            text="Alex chose Postgres.",
            rank=1,
            score=0.9,
            item_id="private-new",
            created_at="2024-01-03T10:00:00",
        ),
        RetrievedMemory(
            text="Alex first tested SQLite.",
            rank=2,
            score=0.8,
            item_id="private-old",
            created_at="2023-01-02T10:00:00",
        ),
    )

    answer_prompt = render_mem0_official_answer_prompt(case, memories)
    judge_prompt = render_mem0_official_judge_prompt(
        case,
        AnswerResult(answer="Reasoning\nANSWER: Postgres"),
    )

    assert answer_prompt.policy_id == MEM0_OFFICIAL_PROMPT_POLICY
    assert answer_prompt.upstream_commit == MEM0_BENCHMARK_UPSTREAM_COMMIT
    assert answer_prompt.stage == "answer"
    assert answer_prompt.system == ""
    assert _hash(answer_prompt.user) == _LOCOMO_ANSWER_SHA256
    assert answer_prompt.user.index("Alex first tested SQLite.") < answer_prompt.user.index(
        "Alex chose Postgres."
    )
    assert "private-new" not in answer_prompt.user
    assert "0.9" not in answer_prompt.user

    assert judge_prompt.stage == "judge"
    assert (
        judge_prompt.system == "You are evaluating conversational AI memory recall. "
        "Return JSON only with the format requested."
    )
    assert _hash(judge_prompt.user) == _LOCOMO_JUDGE_SHA256
    assert "Gold answer: Postgres\n" in judge_prompt.user
    assert "because it is reliable" not in judge_prompt.user
    assert "## Evidence" not in judge_prompt.user
    assert "EVIDENCE SUPPORTS ANSWER" not in judge_prompt.user


def test_longmemeval_official_answer_and_judge_snapshots() -> None:
    case = _longmemeval_case()
    memories = (
        RetrievedMemory(
            text="I now use Postgres.",
            rank=1,
            created_at="2024-01-03T21:00:00-07:00",
        ),
        RetrievedMemory(
            text="I previously used SQLite.",
            rank=2,
            created_at="2023-12-01T12:00:00Z",
        ),
    )

    answer_prompt = render_mem0_official_answer_prompt(case, memories)
    judge_prompt = render_mem0_official_judge_prompt(
        case,
        AnswerResult(answer="<mem_thinking>private reasoning</mem_thinking>\nANSWER: Postgres"),
    )

    assert answer_prompt.system == ""
    assert _hash(answer_prompt.user) == _LONGMEMEVAL_ANSWER_SHA256
    assert "Today's date is Thursday, January 04, 2024." in answer_prompt.user
    assert answer_prompt.user.index("I previously used SQLite.") < answer_prompt.user.index(
        "I now use Postgres."
    )
    assert "--- Friday, December 01, 2023 ---" in answer_prompt.user
    assert "--- Thursday, January 04, 2024 ---" in answer_prompt.user

    assert judge_prompt.system == ""
    assert _hash(judge_prompt.user) == _LONGMEMEVAL_JUDGE_SHA256
    assert "Model Response: Postgres" in judge_prompt.user
    assert "private reasoning" not in judge_prompt.user


@pytest.mark.parametrize(
    ("benchmark", "raw", "expected_answer"),
    (
        ("locomo", "analysis\nANSWER: final answer", "final answer"),
        (
            "longmemeval",
            "<mem_thinking>hidden</mem_thinking>\nVisible answer",
            "Visible answer",
        ),
        (
            "longmemeval",
            "[mem_thinking]hidden[/mem_thinking]\nANSWER: visible",
            "visible",
        ),
        ("longmemeval", "first ANSWER: stale ANSWER: newest", "newest"),
    ),
)
def test_answer_cleanup_matches_upstream_visible_answer(
    benchmark: str,
    raw: str,
    expected_answer: str,
) -> None:
    case = _case(benchmark=benchmark)
    original = AnswerResult(
        answer=raw,
        model="answer-model",
        latency_ms=12.5,
        metadata={"transport": "test"},
    )

    normalized = normalize_mem0_official_answer(case, original)

    assert normalized.answer == expected_answer
    assert normalized.model == original.model
    assert normalized.latency_ms == original.latency_ms
    assert normalized.metadata == {
        "transport": "test",
        "prompt_policy_id": MEM0_OFFICIAL_PROMPT_POLICY,
        "prompt_upstream_commit": MEM0_BENCHMARK_UPSTREAM_COMMIT,
    }


@pytest.mark.parametrize(
    ("raw", "correct"),
    (
        ("<judge_thinking>yes is mentioned</judge_thinking>\nno", False),
        ("<judge_thinking>consider no</judge_thinking>\nyes", True),
        ("analysis says yes, final no", False),
        ("yes, definitely", True),
        ("", False),
    ),
)
def test_longmemeval_yes_no_parsing_matches_upstream(raw: str, correct: bool) -> None:
    decision = parse_mem0_official_judge_response(_longmemeval_case(), raw)

    assert decision.correct is correct
    assert decision.verdict == ("PASS" if correct else "FAIL")


@pytest.mark.parametrize(
    ("raw", "correct"),
    (
        ({"label": "CORRECT"}, True),
        ({"label": "wrong"}, False),
        ('{"label":"CORRECT"}', True),
        ({"reasoning": "missing label"}, False),
        ("not-json", False),
    ),
)
def test_locomo_structured_judge_parsing(raw: object, correct: bool) -> None:
    decision = parse_mem0_official_judge_response(_locomo_case(), raw)

    assert decision.correct is correct
    assert decision.verdict == ("CORRECT" if correct else "WRONG")


def test_raw_memory_contract_ignores_retrieval_metadata() -> None:
    case = _locomo_case()
    memory = RetrievedMemory(
        text="Alex chose Postgres.",
        rank=197,
        score=0.123456,
        item_id="private-item-id",
        created_at=None,
        source_refs=("private-source",),
        metadata={"private": "metadata"},
    )

    prompt = render_mem0_official_answer_prompt(case, (memory,)).user

    assert "(unknown date) Alex chose Postgres." in prompt
    for forbidden in ("private-item-id", "private-source", "metadata", "0.123456", "197"):
        assert forbidden not in prompt


def test_answer_prompt_is_gold_blind_while_judge_receives_ground_truth() -> None:
    gold_canary = "GOLD-ONLY-CANARY-82f4"
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="gold-blind",
        question="Which database?",
        expected_terms=(gold_canary,),
        forbidden_terms=("FORBIDDEN-GOLD-CANARY",),
        metadata={
            "category": 4,
            "_evaluator_ground_truth": gold_canary,
            "answer_preview": gold_canary,
            "evidence_previews": [gold_canary],
        },
    )

    answer_prompt = render_mem0_official_answer_prompt(
        case,
        (RetrievedMemory(text="Evidence says Postgres.", rank=1),),
    ).user
    judge_prompt = render_mem0_official_judge_prompt(
        case,
        AnswerResult(answer="Postgres"),
    ).user

    assert gold_canary not in answer_prompt
    assert "FORBIDDEN-GOLD-CANARY" not in answer_prompt
    assert "Postgres" in answer_prompt
    assert f"Gold answer: {gold_canary}" in judge_prompt


def test_empty_memory_format_and_invalid_date_fallback_are_upstream_compatible() -> None:
    locomo_prompt = render_mem0_official_answer_prompt(_locomo_case(), ()).user
    long_case = _longmemeval_case(question_date="not-a-date")
    long_prompt = render_mem0_official_answer_prompt(long_case, ()).user

    assert "(No relevant memories found)" in locomo_prompt
    assert "(No relevant memories found)" in long_prompt
    assert "Today's date is not-a-date." in long_prompt


def test_locomo_reference_date_comes_from_latest_case_session() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="l-date",
        question="What happened?",
        expected_terms=("event",),
        memories=(
            BenchmarkMemoryInput(
                text="older",
                metadata={"session_date": "1:00 pm on 8 May, 2023"},
            ),
            BenchmarkMemoryInput(
                text="newer",
                metadata={"session_date": "9:15 pm on 9 May, 2023"},
            ),
        ),
    )

    prompt = render_mem0_official_answer_prompt(case, ()).user

    assert "conversations took place around 9:15 pm on 9 May, 2023." in prompt


def test_evaluator_ground_truth_precedes_bounded_preview() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="l-ground-truth",
        question="What database?",
        expected_terms=("session-id",),
        metadata={
            "category": 3,
            "_evaluator_ground_truth": "Postgres; full explanation",
            "answer_preview": "truncated preview",
        },
    )

    prompt = render_mem0_official_judge_prompt(
        case,
        AnswerResult(answer="ANSWER: Postgres"),
    ).user

    assert "Gold answer: Postgres\n" in prompt
    assert "full explanation" not in prompt
    assert "truncated preview" not in prompt


def test_locomo_judge_uses_exact_300_character_evaluator_gold() -> None:
    exact_gold = "G" * 300
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="l-exact-gold",
        question="What happened?",
        expected_terms=("redacted-preview",),
        metadata={
            "category": 4,
            "_evaluator_ground_truth": exact_gold,
            "answer_preview": "redacted-preview",
        },
    )

    prompt = render_mem0_official_judge_prompt(
        case,
        AnswerResult(answer="generated"),
    ).user

    assert f"Gold answer: {exact_gold}\n" in prompt
    assert "redacted-preview" not in prompt


def test_locomo_judge_fails_closed_without_exact_evaluator_gold() -> None:
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id="l-missing-exact-gold",
        question="What happened?",
        expected_terms=("expected-fallback",),
        metadata={
            "category": 4,
            "ground_truth_answer": "legacy-full-answer",
            "answer_preview": "redacted-preview",
        },
    )

    answer_prompt = render_mem0_official_answer_prompt(case, ()).user
    assert "legacy-full-answer" not in answer_prompt
    assert "redacted-preview" not in answer_prompt
    assert "expected-fallback" not in answer_prompt
    with pytest.raises(ValueError, match="requires exact _evaluator_ground_truth"):
        render_mem0_official_judge_prompt(case, AnswerResult(answer="generated"))


def test_unsupported_benchmark_fails_closed() -> None:
    case = _case(benchmark="beam")

    with pytest.raises(ValueError, match="Unsupported official mem0 prompt benchmark"):
        render_mem0_official_answer_prompt(case, ())


def _locomo_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="l-1",
        question="What database did Alex choose?",
        expected_terms=("Postgres",),
        metadata={
            "category": 3,
            "_evaluator_ground_truth": "Postgres; because it is reliable",
            "answer_preview": "Postgres; because it is reliable",
            "reference_date": "January 04, 2024",
        },
    )


def _longmemeval_case(
    *,
    question_date: str = "2024/01/04 (Thu) 09:30",
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="m-1",
        question="Which database do I use now?",
        expected_terms=("Postgres",),
        metadata={
            "question_type": "knowledge-update",
            "question_date": question_date,
            "answer_preview": "Postgres",
        },
    )


def _case(*, benchmark: str) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id="case-1",
        question="Question?",
        expected_terms=("answer",),
    )


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()
