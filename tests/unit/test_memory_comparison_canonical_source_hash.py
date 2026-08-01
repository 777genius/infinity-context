from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from infinity_context_core.features.document_ingestion.public import content_hash_for_text
from infinity_context_server.memory_comparison_canonical_source_hash import (
    CanonicalSourceHashError,
    conversation_source_hashes,
    document_source_hash,
    memory_source_hash,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
)
from infinity_context_server.memory_comparison_http import (
    InfinityContextHttpComparisonBackend,
)
from infinity_context_server.memory_comparison_http_ingest_request import (
    case_message_groups,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)


def test_memory_hash_matches_raw_utf8_fact_content() -> None:
    text = "  Café\r\nraw fact\x1f  "
    identity = memory_source_hash(
        BenchmarkMemoryInput(text=text, source_external_id="memory-1")
    )

    assert identity.metadata() == {
        "source_id": "memory-1",
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    assert identity.source_sha256 != content_hash_for_text(text)


def test_document_hash_matches_infinity_normalized_content_hash() -> None:
    text = "  Document\r\ncontent\x1f  "
    identity = document_source_hash(
        BenchmarkDocumentInput(
            title="Document",
            text=text,
            source_external_id="document-1",
        )
    )

    assert identity.metadata() == {
        "source_id": "document-1",
        "source_sha256": content_hash_for_text(text),
    }
    assert identity.source_sha256 != hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_long_document_source_id_is_same_safe_160_projection_for_both_adapters() -> None:
    raw_source_id = "document-" + ("x" * 300)
    document = BenchmarkDocumentInput(
        title="Document",
        text="Shared source projection.",
        source_external_id=raw_source_id,
    )
    case = PublicBenchmarkCase(
        benchmark="fixture",
        case_id="long-source-id",
        question="q",
        expected_terms=(),
        documents=(document,),
    )
    infinity_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        infinity_payloads.append(json.loads(request.content))
        return httpx.Response(201, json={"data": {"id": "document-id"}})

    backend = InfinityContextHttpComparisonBackend(
        base_url="http://infinity.test",
        auth_token="unit-token",
        transport=httpx.MockTransport(handler),
    )
    try:
        backend.ingest(case, run_id="Run 42", corpus_key="corpus-a")
    finally:
        backend.close()

    identity = document_source_hash(document)
    mem0_metadata = case_message_groups(case)[0][2]
    infinity_source_id = infinity_payloads[0]["source_external_id"]

    assert len(identity.source_id) == 160
    assert raw_source_id not in identity.source_id
    assert infinity_source_id == mem0_metadata["source_id"] == identity.source_id
    assert mem0_metadata["source_sha256"] == identity.source_sha256


def test_conversation_hash_reuses_exact_infinity_document_rendering() -> None:
    case = _conversation_case()
    canonical_document = conversation_documents(case)[0]

    identities = conversation_source_hashes(case)
    groups = case_message_groups(case)

    assert len(identities) == len(groups) == 1
    assert identities[0].source_id == canonical_document.source_external_id
    assert identities[0].source_sha256 == content_hash_for_text(canonical_document.text)
    assert groups[0][2]["source_sha256"] == identities[0].source_sha256


def test_conversation_identity_alignment_skips_filtered_message_groups() -> None:
    valid = _conversation_case().conversations[0]
    invalid = BenchmarkConversationInput(
        messages=(BenchmarkMessageInput(role="user", content="  "),),
        source_external_id="filtered-pair",
    )
    case = replace(_conversation_case(), conversations=(invalid, valid, invalid))

    identities = conversation_source_hashes(case)
    groups = case_message_groups(case)

    assert len(identities) == len(groups) == 1
    assert identities[0].source_id == groups[0][2]["source_id"] == "pair-1"


def test_long_conversation_source_id_uses_safe_160_projection() -> None:
    conversation = replace(
        _conversation_case().conversations[0],
        source_external_id="pair-" + ("x" * 300),
    )
    case = replace(_conversation_case(), conversations=(conversation,))

    identity = conversation_source_hashes(case)[0]

    assert len(identity.source_id) == 160
    assert case_message_groups(case)[0][2]["source_id"] == identity.source_id


def test_source_hashes_do_not_depend_on_question_or_gold_fields() -> None:
    case = _conversation_case()
    changed_gold = replace(
        case,
        question="Different evaluator question",
        expected_terms=("private evaluator answer",),
        metadata={"answer": "private evaluator answer"},
    )

    assert conversation_source_hashes(case) == conversation_source_hashes(changed_gold)


@pytest.mark.parametrize(
    "case",
    [
        PublicBenchmarkCase(
            benchmark="fixture",
            case_id="missing-memory-id",
            question="q",
            expected_terms=(),
            memories=(BenchmarkMemoryInput(text="memory"),),
        ),
        PublicBenchmarkCase(
            benchmark="fixture",
            case_id="missing-document-id",
            question="q",
            expected_terms=(),
            documents=(BenchmarkDocumentInput(title="d", text="document"),),
        ),
    ],
)
def test_message_groups_fail_closed_on_missing_source_id(
    case: PublicBenchmarkCase,
) -> None:
    with pytest.raises(CanonicalSourceHashError, match="source_external_id is required"):
        case_message_groups(case)


def test_message_groups_fail_closed_on_ambiguous_source_id() -> None:
    case = PublicBenchmarkCase(
        benchmark="fixture",
        case_id="duplicate-source-id",
        question="q",
        expected_terms=(),
        memories=(
            BenchmarkMemoryInput(text="memory", source_external_id="same-source"),
        ),
        documents=(
            BenchmarkDocumentInput(
                title="d",
                text="document",
                source_external_id="same-source",
            ),
        ),
    )

    with pytest.raises(CanonicalSourceHashError, match="ambiguous benchmark source_id"):
        case_message_groups(case)


def test_conversation_groups_fail_closed_on_ambiguous_source_id() -> None:
    first = _conversation_case().conversations[0]
    duplicate = replace(
        first,
        messages=(BenchmarkMessageInput(role="user", content="Different content"),),
    )
    case = replace(_conversation_case(), conversations=(first, duplicate))

    with pytest.raises(CanonicalSourceHashError, match="ambiguous benchmark source_id"):
        case_message_groups(case)


def _conversation_case() -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="question-1",
        question="Where are the notes?",
        expected_terms=("binder",),
        conversations=(
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput(
                        role="user",
                        content="I put the notes in the binder.",
                        source_external_id="pair-1:message:1",
                    ),
                    BenchmarkMessageInput(
                        role="assistant",
                        content="I will remember that.",
                        source_external_id="pair-1:message:2",
                    ),
                ),
                source_external_id="pair-1",
                session_external_id="session-1",
                session_date="2026-07-31",
            ),
        ),
    )
