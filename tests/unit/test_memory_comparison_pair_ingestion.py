from __future__ import annotations

import json
from dataclasses import replace

import httpx
from infinity_context_core.application.sensitive_text import contains_sensitive_text
from infinity_context_server.memory_comparison_case_identity import (
    case_corpus_fingerprint,
)
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
    Mem0HttpComparisonBackend,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)


def _credential_fixture() -> str:
    return "".join(("sk", "-", "fixture", "x" * 18))


def _conversation_case(secret: str) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="question-1",
        question="Where are the launch notes?",
        expected_terms=("blue binder",),
        memories=(BenchmarkMemoryInput(text="legacy memory must not be ingested"),),
        documents=(
            BenchmarkDocumentInput(
                title="legacy",
                text="legacy document must not be ingested",
            ),
        ),
        memory_scope_external_ref="longmemeval-question-1",
        thread_external_ref="longmemeval-question-1",
        conversations=(
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput(
                        role="user",
                        content=f"I saved the launch notes beside {secret}.",
                        source_external_id="pair-1:message:1",
                        timestamp=1_683_110_400,
                        metadata={"has_answer": True, "annotation": secret},
                    ),
                    BenchmarkMessageInput(
                        role="assistant",
                        content="I will remember the blue binder.",
                        source_external_id="pair-1:message:2",
                        timestamp=1_683_110_400,
                    ),
                ),
                source_external_id="pair-1",
                session_external_id="session-a",
                session_date="2023/05/03 (Wed) 00:00",
                timestamp=1_683_110_400,
                metadata={
                    "session_original_index": 0,
                    "pair_index": 0,
                    "has_answer": True,
                    "annotation": secret,
                },
            ),
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput(
                        role="user",
                        content="The binder is on the studio shelf.",
                        source_external_id="pair-2:message:1",
                        timestamp=1_683_110_400,
                    ),
                ),
                source_external_id="pair-2",
                session_external_id="session-a",
                session_date="2023/05/03 (Wed) 00:00",
                timestamp=1_683_110_400,
                metadata={"session_original_index": 0, "pair_index": 1},
            ),
        ),
    )


def test_infinity_ingests_one_canonical_document_per_pair_and_redacts_only_previews() -> None:
    secret = _credential_fixture()
    assert contains_sensitive_text(secret)
    requests: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, dict(request.headers), json.loads(request.content)))
        return httpx.Response(201, json={"data": {"id": "document-id"}})

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _conversation_case(secret),
            run_id="Run 42",
            corpus_key="corpus-a",
        )
    finally:
        backend.close()

    assert [path for path, _, _ in requests] == ["/v1/documents", "/v1/documents"]
    assert result.items_processed == 2
    assert result.metadata["conversation_documents_created"] == 2
    first_headers = requests[0][1]
    first = requests[0][2]
    second = requests[1][2]
    assert first_headers["idempotency-key"] == "pair-1"
    assert first["source_external_id"] == "pair-1"
    assert first["source_type"] == "benchmark_conversation_pair"
    assert first["text"].splitlines() == [
        "session-a date: 2023/05/03 (Wed) 00:00",
        f"user: I saved the launch notes beside {secret}.",
        "assistant: I will remember the blue binder.",
    ]
    assert second["text"].splitlines()[-1] == "user: The binder is on the studio shelf."
    assert secret in str(first["text"])
    assert all(secret not in str(ref.get("quote_preview")) for ref in first["source_refs"])
    assert any("[redacted]" in str(ref.get("quote_preview")) for ref in first["source_refs"])
    assert secret not in str(result.operations[0].memory)
    assert "legacy memory" not in str(requests)
    assert "legacy document" not in str(requests)


def test_mem0_ingests_one_messages_operation_per_pair_without_metadata_leakage() -> None:
    secret = _credential_fixture()
    requests: list[tuple[dict[str, str], dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((dict(request.headers), json.loads(request.content)))
        return httpx.Response(200, json={"results": [{"id": "memory-id"}]})

    backend = Mem0HttpComparisonBackend(
        base_url="http://mem0.test",
        reset_user_on_start=False,
        send_timestamps=True,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = backend.ingest(
            _conversation_case(secret),
            run_id="Run 42",
            corpus_key="corpus-a",
        )
    finally:
        backend.close()

    assert result.items_processed == 2
    assert result.total_memories_created == 2
    assert [headers["idempotency-key"] for headers, _ in requests] == [
        "pair-1",
        "pair-2",
    ]
    assert [payload["messages"] for _, payload in requests] == [
        [
            {
                "role": "user",
                "content": f"I saved the launch notes beside {secret}.",
            },
            {
                "role": "assistant",
                "content": "I will remember the blue binder.",
            },
        ],
        [{"role": "user", "content": "The binder is on the studio shelf."}],
    ]
    first_metadata = requests[0][1]["metadata"]
    assert first_metadata["source_id"] == "pair-1"
    assert first_metadata["session_id"] == "session-a"
    assert first_metadata["source_timestamp"] == 1_683_110_400
    assert "has_answer" not in first_metadata
    assert secret not in str(first_metadata)
    assert requests[0][1]["timestamp"] == 1_683_110_400
    assert secret not in str(result.operations[0].memory)
    assert "legacy memory" not in str(requests)
    assert "legacy document" not in str(requests)


def test_conversation_corpus_fingerprint_is_stable_and_content_sensitive() -> None:
    case = _conversation_case(_credential_fixture())
    first_pair = case.conversations[0]
    first_message = first_pair.messages[0]
    changed_case = replace(
        case,
        conversations=(
            replace(
                first_pair,
                messages=(
                    replace(
                        first_message,
                        content="I saved the launch notes in the red binder.",
                    ),
                    first_pair.messages[1],
                ),
            ),
            case.conversations[1],
        ),
    )

    fingerprint = case_corpus_fingerprint(case)
    assert fingerprint == case_corpus_fingerprint(case)
    assert fingerprint != case_corpus_fingerprint(changed_case)
