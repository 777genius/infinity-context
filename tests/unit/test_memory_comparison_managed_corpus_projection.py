from __future__ import annotations

import copy
import json

import httpx
import pytest
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_record,
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_http_observation import (
    expected_official_locomo_turn_for_group,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_SESSION_DATE = "1:56 pm on 8 May, 2023"
_TIMESTAMP = 1_683_554_160


def _locomo_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id="raw-sample-a:qa:7",
        question="secret question?",
        expected_terms=("secret gold",),
        forbidden_terms=("forbidden evaluator term",),
        memories=(
            BenchmarkMemoryInput(
                f"session_1 date: {_SESSION_DATE}\n"
                "D1:1 Caroline: The checklist is in the blue notebook.",
                source_external_id="locomo:raw-sample-a:session_1:D1:1:turn",
                metadata={
                    "role": "user",
                    "timestamp": _TIMESTAMP,
                    "session_key": "session_1",
                    "session_date": _SESSION_DATE,
                    "dia_id": "D1:1",
                    "speaker": "Caroline",
                },
            ),
            BenchmarkMemoryInput(
                f"session_1 date: {_SESSION_DATE}\nD1:2 Melanie: I will bring it tomorrow.",
                source_external_id="locomo:raw-sample-a:session_1:D1:2:turn",
                metadata={
                    "role": "assistant",
                    "timestamp": _TIMESTAMP,
                    "session_key": "session_1",
                    "session_date": _SESSION_DATE,
                    "dia_id": "D1:2",
                    "speaker": "Melanie",
                },
            ),
        ),
        memory_scope_external_ref="raw-sample-a",
        thread_external_ref="raw-thread-a",
        metadata={
            "locomo_ingest_mode": "official-turns",
            "_evaluator_ground_truth": "secret gold",
            "evidence": ["D1:1"],
        },
    )


def _longmemeval_case() -> PublicBenchmarkCase:
    messages = (
        BenchmarkMessageInput(
            "user",
            "I moved to Oslo.",
            source_external_id="raw-message-1",
            timestamp=1_700_000_000,
        ),
        BenchmarkMessageInput(
            "assistant",
            "I will remember that.",
            source_external_id="raw-message-2",
            timestamp=1_700_000_000,
        ),
    )
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="raw-long-id",
        question="secret long question?",
        expected_terms=("Oslo",),
        conversations=(
            BenchmarkConversationInput(
                messages=messages,
                source_external_id="raw-pair-1",
                session_external_id="raw-session-1",
                session_date="2023-11-14",
                timestamp=1_700_000_000,
            ),
            BenchmarkConversationInput(
                messages=messages,
                source_external_id="raw-pair-2",
                session_external_id="raw-session-1",
                session_date="2023-11-14",
                timestamp=1_700_000_000,
            ),
        ),
        memory_scope_external_ref="raw-corpus-id",
        thread_external_ref="raw-thread-id",
        metadata={"_evaluator_ground_truth": "Oslo"},
    )


def test_locomo_roundtrip_is_gold_blind_and_official_transport_compatible() -> None:
    record = _managed_corpus_record(_locomo_case())
    rendered = json.dumps(record, sort_keys=True)
    for forbidden in (
        "raw-sample-a",
        "raw-thread-a",
        "secret question",
        "secret gold",
        "forbidden evaluator term",
        "_evaluator_ground_truth",
        "evidence",
        "session_1",
        "D1:1",
        "D1:2",
    ):
        assert forbidden not in rendered

    answer = ManagedAnswerCase(
        "locomo-case-" + "a" * 64,
        "When will Melanie bring the checklist?",
        {"question_type": "temporal"},
    )
    rebuilt = _reconstruct_managed_corpus_case(record, answer)

    assert type(rebuilt) is PublicBenchmarkCase
    assert rebuilt.expected_terms == ()
    assert rebuilt.forbidden_terms == ()
    assert rebuilt.question == answer.question
    assert rebuilt.metadata == {
        "question_type": "temporal",
        "locomo_ingest_mode": "official-turns",
        "public_trigger_case_id": answer.case_id,
    }
    assert tuple(memory.metadata["role"] for memory in rebuilt.memories) == (
        "user",
        "assistant",
    )
    assert tuple(memory.metadata["speaker"] for memory in rebuilt.memories) == (
        "Caroline",
        "Melanie",
    )
    assert tuple(memory.metadata["session_date"] for memory in rebuilt.memories) == (
        _SESSION_DATE,
        _SESSION_DATE,
    )
    assert tuple(memory.metadata["timestamp"] for memory in rebuilt.memories) == (
        _TIMESTAMP,
        _TIMESTAMP,
    )
    assert rebuilt.memories[0].metadata["session_key"] == "session_900001"
    assert rebuilt.memories[0].metadata["dia_id"] == "D900001:1"
    assert rebuilt.memories[1].metadata["dia_id"] == "D900001:2"
    assert "The checklist is in the blue notebook." in rebuilt.memories[0].text
    assert "I will bring it tomorrow." in rebuilt.memories[1].text

    expected = expected_official_locomo_turn_for_group(
        rebuilt,
        group_index=1,
        run_id="managed-run-1",
        corpus_key=record["corpus_id"],
    )
    assert expected is not None
    assert rebuilt.case_id.split(":qa:", 1)[0] in rebuilt.memories[0].source_external_id


def test_reconstruction_accepts_exact_frozen_managed_run_record() -> None:
    record = _managed_corpus_record(_longmemeval_case())
    managed = ManagedRunCase(
        "longmemeval-case-" + "e" * 64,
        record["corpus_id"],
        record,
    )

    rebuilt = _reconstruct_managed_corpus_case(
        managed.record,
        ManagedAnswerCase(managed.case_id, "Where did I move?", {}),
    )

    assert rebuilt.case_id == managed.case_id
    assert rebuilt.conversations[0].messages[0].content == "I moved to Oslo."


def test_longmemeval_roundtrip_preserves_provider_relevant_corpus_semantics() -> None:
    record = _managed_corpus_record(_longmemeval_case())
    rendered = json.dumps(record, sort_keys=True)
    for forbidden in (
        "raw-long-id",
        "raw-message-1",
        "raw-message-2",
        "raw-pair-1",
        "raw-pair-2",
        "raw-session-1",
        "raw-corpus-id",
        "raw-thread-id",
        "secret long question",
        "_evaluator_ground_truth",
    ):
        assert forbidden not in rendered

    rebuilt = _reconstruct_managed_corpus_case(
        record,
        case_id="longmemeval-case-" + "b" * 64,
        question="Where did I move?",
        temporal_context={"reference_date": "2024-01-01"},
    )

    assert rebuilt.case_id == "longmemeval-case-" + "b" * 64
    assert rebuilt.expected_terms == ()
    assert rebuilt.documents == ()
    assert len(rebuilt.conversations) == 2
    assert tuple(message.content for message in rebuilt.conversations[0].messages) == (
        "I moved to Oslo.",
        "I will remember that.",
    )
    assert tuple(message.role for message in rebuilt.conversations[0].messages) == (
        "user",
        "assistant",
    )
    assert rebuilt.conversations[0].session_external_id == (
        rebuilt.conversations[1].session_external_id
    )
    assert rebuilt.conversations[0].metadata == {
        "session_original_index": 0,
        "pair_index": 0,
    }
    assert rebuilt.conversations[1].metadata == {
        "session_original_index": 0,
        "pair_index": 1,
    }
    assert rebuilt.memory_scope_external_ref == record["corpus_id"]
    assert rebuilt.thread_external_ref == record["thread_id"]
    assert rebuilt.metadata == {"reference_date": "2024-01-01"}


def test_longmemeval_roundtrip_preserves_whitespace_significant_message_bytes() -> None:
    record = _managed_corpus_record(_longmemeval_case())
    content = "  leading\nbody\t\ntrailing  "
    record["conversations"][0]["messages"][0]["content"] = content

    rebuilt = _reconstruct_managed_corpus_case(
        record,
        case_id="longmemeval-case-" + "c" * 64,
        question="Where did I move?",
        temporal_context={},
    )

    actual = rebuilt.conversations[0].messages[0].content
    assert actual == content
    assert actual.encode("utf-8") == content.encode("utf-8")


@pytest.mark.parametrize("content", (" \n\t ", "é" * 524_289))
def test_longmemeval_message_content_remains_nonempty_and_byte_bounded(
    content: str,
) -> None:
    record = _managed_corpus_record(_longmemeval_case())
    record["conversations"][0]["messages"][0]["content"] = content

    with pytest.raises(ManagedRunError, match="message content is invalid"):
        _reconstruct_managed_corpus_case(
            record,
            case_id="longmemeval-case-" + "d" * 64,
            question="Where did I move?",
            temporal_context={},
        )


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("extra",), "unexpected"),
        (("memories", 0, "extra"), "unexpected"),
        (("memories", 0, "source_alias"), "memory-999999"),
        (("memories", 0, "session_alias"), "session-0002"),
        (("memories", 0, "timestamp"), True),
    ),
)
def test_reconstruction_rejects_unknown_malformed_and_tampered_projection(
    path: tuple[object, ...],
    replacement: object,
) -> None:
    record = copy.deepcopy(_managed_corpus_record(_locomo_case()))
    cursor: object = record
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    cursor[path[-1]] = replacement  # type: ignore[index]

    with pytest.raises(ManagedRunError):
        _reconstruct_managed_corpus_case(
            record,
            case_id="locomo-case-" + "c" * 64,
            question="Question?",
            temporal_context={},
        )


def test_answer_material_modes_are_exact_and_mutually_exclusive() -> None:
    record = _managed_corpus_record(_locomo_case())
    answer = ManagedAnswerCase(
        "locomo-case-" + "d" * 64,
        "Question?",
        {},
    )

    with pytest.raises(ManagedRunError, match="mutually exclusive"):
        _reconstruct_managed_corpus_case(record, answer, question="different")
    with pytest.raises(ManagedRunError, match="exact dict"):
        _reconstruct_managed_corpus_case(
            record,
            case_id=answer.case_id,
            question=answer.question,
            temporal_context=None,
        )


@pytest.mark.parametrize(
    "temporal_context",
    (
        {"_evaluator_ground_truth": "secret"},
        {"evidence": ["gold-bearing-session"]},
        {"question_type": True},
    ),
)
def test_typed_answer_material_rejects_non_temporal_or_non_scalar_metadata(
    temporal_context: dict[str, object],
) -> None:
    record = _managed_corpus_record(_longmemeval_case())
    answer = ManagedAnswerCase(
        "longmemeval-case-" + "f" * 64,
        "Where did I move?",
        temporal_context,
    )

    with pytest.raises(ManagedRunError, match="exact scalar JSON values"):
        _reconstruct_managed_corpus_case(record, answer)


def test_mixed_longmemeval_projection_fails_before_any_http_io() -> None:
    record = _managed_corpus_record(_longmemeval_case())
    record["documents"] = [
        {
            "classification": "internal",
            "source_alias": "document-000001",
            "source_type": "profile",
            "text": "This source would otherwise be silently skipped.",
            "title": "Profile",
        }
    ]
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={})

    with pytest.raises(ManagedRunError, match="only nonempty pair conversations"):
        rebuilt = _reconstruct_managed_corpus_case(
            record,
            case_id="longmemeval-case-" + "1" * 64,
            question="Where did I move?",
            temporal_context={},
        )
        backend = Mem0HttpComparisonBackend(
            base_url="http://mem0.test",
            reset_user_on_start=False,
            transport=httpx.MockTransport(handler),
        )
        try:
            backend.ingest(rebuilt, run_id="managed-run", corpus_key=str(record["corpus_id"]))
        finally:
            backend.close()

    assert request_count == 0


def test_longmemeval_roundtrip_http_payloads_equal_committed_conversations() -> None:
    record = _managed_corpus_record(_longmemeval_case())
    rebuilt = _reconstruct_managed_corpus_case(
        record,
        case_id="longmemeval-case-" + "2" * 64,
        question="Where did I move?",
        temporal_context={},
    )
    mem0_payloads: list[dict[str, object]] = []
    infinity_payloads: list[dict[str, object]] = []

    def mem0_handler(request: httpx.Request) -> httpx.Response:
        mem0_payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"id": "memory-1"}]})

    def infinity_handler(request: httpx.Request) -> httpx.Response:
        infinity_payloads.append(json.loads(request.content))
        return httpx.Response(201, json={"data": {"id": "document-1"}})

    mem0 = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        transport=httpx.MockTransport(mem0_handler),
    )
    infinity = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="test-token",
        transport=httpx.MockTransport(infinity_handler),
    )
    try:
        mem0_result = mem0.ingest(
            rebuilt,
            run_id="managed-run",
            corpus_key=str(record["corpus_id"]),
        )
        infinity_result = infinity.ingest(
            rebuilt,
            run_id="managed-run",
            corpus_key=str(record["corpus_id"]),
        )
    finally:
        mem0.close()
        infinity.close()

    committed = record["conversations"]
    assert type(committed) is list
    assert mem0_result.items_processed == infinity_result.items_processed == len(committed)
    assert [payload["messages"] for payload in mem0_payloads] == [
        [
            {"role": message["role"], "content": message["content"]}
            for message in conversation["messages"]
        ]
        for conversation in committed
    ]
    assert [payload["text"].splitlines()[1:] for payload in infinity_payloads] == [
        [f"{message['role']}: {message['content']}" for message in conversation["messages"]]
        for conversation in committed
    ]
    assert all("secret long question" not in json.dumps(payload) for payload in mem0_payloads)
    assert all("secret long question" not in json.dumps(payload) for payload in infinity_payloads)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("speaker", " "),
        ("session_date", " bad "),
        ("role", "User"),
        ("role", None),
        ("timestamp", True),
    ),
)
def test_projection_rejects_malformed_turn_semantics_without_coercion(
    field: str,
    value: object,
) -> None:
    case = _locomo_case()
    memory = case.memories[0]
    malformed = PublicBenchmarkCase(
        **{
            **case.__dict__,
            "memories": (
                BenchmarkMemoryInput(
                    memory.text,
                    source_external_id=memory.source_external_id,
                    metadata={**memory.metadata, field: value},
                ),
                *case.memories[1:],
            ),
        }
    )

    with pytest.raises(ManagedRunError, match=field):
        _managed_corpus_record(malformed)
