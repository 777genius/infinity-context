from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from types import MappingProxyType
from typing import cast

import pytest
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)
from infinity_context_server.ranked_evidence_retrieval_request import (
    ranked_evidence_retrieval_request,
)
from infinity_context_server.ranked_evidence_seed_case import ranked_evidence_seed_case

_GOLD = "evaluator-only-gold"


def _case(
    *,
    memory_scope_external_ref: str | None = None,
    thread_external_ref: str | None = None,
    memories: tuple[BenchmarkMemoryInput, ...] = (),
    documents: tuple[BenchmarkDocumentInput, ...] = (),
    conversations: tuple[BenchmarkConversationInput, ...] = (),
) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="bench",
        case_id="case-7",
        question="What was remembered?",
        expected_terms=(_GOLD,),
        forbidden_terms=("forbidden-gold",),
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        memories=memories,
        documents=documents,
        conversations=conversations,
        metadata={
            "expected_refs": ("gold:D1:1",),
            "ground_truth": _GOLD,
        },
    )


def test_retrieval_request_has_only_question_side_fields_and_fallback_refs() -> None:
    request = ranked_evidence_retrieval_request(_case())
    seed = ranked_evidence_seed_case(_case())

    assert tuple(field.name for field in fields(request)) == (
        "question",
        "memory_scope_external_ref",
        "thread_external_ref",
    )
    assert request.question == "What was remembered?"
    assert (
        request.memory_scope_external_ref,
        request.thread_external_ref,
        seed.memory_scope_external_ref,
        seed.thread_external_ref,
    ) == ("bench-case-7",) * 4
    assert not hasattr(request, "expected_terms")
    assert not hasattr(request, "forbidden_terms")
    assert not hasattr(request, "metadata")
    assert not hasattr(request, "documents")


def test_explicit_retrieval_and_seed_refs_are_preserved() -> None:
    case = _case(
        memory_scope_external_ref="scope-ref",
        thread_external_ref="thread-ref",
    )

    request = ranked_evidence_retrieval_request(case)
    seed = ranked_evidence_seed_case(case)

    assert (
        request.memory_scope_external_ref,
        request.thread_external_ref,
        seed.memory_scope_external_ref,
        seed.thread_external_ref,
    ) == ("scope-ref", "thread-ref", "scope-ref", "thread-ref")


def test_seed_projection_copies_only_allowed_source_fields_as_immutable_mappings() -> (
    None
):
    memory_metadata: dict[str, object] = {
        "role": "user",
        "ground_truth": _GOLD,
    }
    source_ref: dict[str, object] = {
        "source_type": "document",
        "source_id": "doc-1",
    }
    conversation_metadata: dict[str, object] = {
        "session_original_index": 3,
        "pair_index": 1,
        "expected_refs": ("gold:D1:1",),
    }
    seed = ranked_evidence_seed_case(
        _case(
            memories=(
                BenchmarkMemoryInput(
                    text="source memory",
                    kind="fact",
                    source_external_id="memory-1",
                    metadata=memory_metadata,
                ),
            ),
            documents=(
                BenchmarkDocumentInput(
                    title="Source document",
                    text="source document body",
                    source_type="benchmark",
                    classification="internal",
                    source_external_id="document-1",
                    source_refs=(source_ref,),
                ),
            ),
            conversations=(
                BenchmarkConversationInput(
                    messages=(
                        BenchmarkMessageInput(
                            role="user",
                            content="source message",
                            source_external_id="message-1",
                            timestamp=17,
                            metadata={"ground_truth": _GOLD},
                        ),
                    ),
                    source_external_id="conversation-1",
                    session_external_id="session-1",
                    session_date="2025-01-02",
                    timestamp=16,
                    metadata=conversation_metadata,
                ),
            ),
        )
    )

    assert tuple(field.name for field in fields(seed)) == (
        "benchmark",
        "case_id",
        "memories",
        "documents",
        "memory_scope_external_ref",
        "thread_external_ref",
        "conversations",
    )
    assert not hasattr(seed, "question")
    assert not hasattr(seed, "expected_terms")
    assert not hasattr(seed, "forbidden_terms")
    assert not hasattr(seed, "metadata")
    assert seed.memories[0].metadata == {"role": "user"}
    assert seed.documents[0].source_refs == (source_ref,)
    assert seed.conversations[0].metadata == {
        "session_original_index": 3,
        "pair_index": 1,
    }
    assert seed.conversations[0].messages[0].metadata == {}
    memory = seed.memories[0]
    document = seed.documents[0]
    conversation = seed.conversations[0]
    message = conversation.messages[0]
    assert (memory.text, memory.kind, memory.source_external_id) == (
        "source memory",
        "fact",
        "memory-1",
    )
    assert (
        document.title,
        document.text,
        document.source_type,
        document.classification,
        document.source_external_id,
    ) == (
        "Source document",
        "source document body",
        "benchmark",
        "internal",
        "document-1",
    )
    assert (
        conversation.source_external_id,
        conversation.session_external_id,
        conversation.session_date,
        conversation.timestamp,
    ) == ("conversation-1", "session-1", "2025-01-02", 16)
    assert (
        message.role,
        message.content,
        message.source_external_id,
        message.timestamp,
    ) == ("user", "source message", "message-1", 17)
    assert all(
        isinstance(mapping, MappingProxyType)
        for mapping in (
            seed.memories[0].metadata,
            seed.documents[0].source_refs[0],
            seed.conversations[0].metadata,
            seed.conversations[0].messages[0].metadata,
        )
    )

    memory_metadata["role"] = "assistant"
    source_ref["source_id"] = "changed"
    conversation_metadata["pair_index"] = 99
    assert seed.memories[0].metadata == {"role": "user"}
    assert seed.documents[0].source_refs[0]["source_id"] == "doc-1"
    assert seed.conversations[0].metadata["pair_index"] == 1
    with pytest.raises(TypeError):
        seed.memories[0].metadata["role"] = "assistant"  # type: ignore[index]


def test_malformed_conversation_indexes_are_rejected_from_projection() -> None:
    conversation = BenchmarkConversationInput(
        messages=(),
        metadata={
            "session_original_index": True,
            "pair_index": -1,
        },
    )

    seed = ranked_evidence_seed_case(_case(conversations=(conversation,)))

    assert seed.conversations[0].metadata == {}


def test_non_mapping_document_source_ref_is_rejected() -> None:
    malformed = cast(Mapping[str, object], 7)
    document = BenchmarkDocumentInput(
        title="title",
        text="body",
        source_refs=(malformed,),
    )

    with pytest.raises(TypeError):
        ranked_evidence_seed_case(_case(documents=(document,)))
