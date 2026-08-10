"""Lossless canonical JSON codecs for private scheduler authority rows."""

from __future__ import annotations

from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_integrity import (
    canonical_mapping,
    canonical_text,
    require_exact_keys,
)

_CASE_KEYS = frozenset(
    {
        "benchmark",
        "case_id",
        "conversations",
        "documents",
        "expected_terms",
        "forbidden_terms",
        "memories",
        "memory_scope_external_ref",
        "metadata",
        "question",
        "thread_external_ref",
    }
)
_MEMORY_INPUT_KEYS = frozenset({"kind", "metadata", "source_external_id", "text"})
_DOCUMENT_KEYS = frozenset(
    {"classification", "source_external_id", "source_refs", "source_type", "text", "title"}
)
_CONVERSATION_KEYS = frozenset(
    {
        "messages",
        "metadata",
        "session_date",
        "session_external_id",
        "source_external_id",
        "timestamp",
    }
)
_MESSAGE_KEYS = frozenset({"content", "metadata", "role", "source_external_id", "timestamp"})
_RETRIEVED_MEMORY_KEYS = frozenset(
    {"created_at", "item_id", "metadata", "rank", "score", "source_refs", "text"}
)


def official_case_json(case: PublicBenchmarkCase) -> str:
    if type(case) is not PublicBenchmarkCase:
        _fail("scheduler_official_case_authority_case_invalid")
    return canonical_text(official_case_payload(case))


def official_case_payload(case: PublicBenchmarkCase) -> dict[str, object]:
    if (
        type(case) is not PublicBenchmarkCase
        or type(case.expected_terms) is not tuple
        or type(case.forbidden_terms) is not tuple
        or type(case.memories) is not tuple
        or type(case.documents) is not tuple
        or type(case.conversations) is not tuple
        or type(case.metadata) is not dict
    ):
        _fail("scheduler_official_case_authority_case_invalid")
    return {
        "benchmark": case.benchmark,
        "case_id": case.case_id,
        "conversations": [_conversation_payload(item) for item in case.conversations],
        "documents": [_document_payload(item) for item in case.documents],
        "expected_terms": list(case.expected_terms),
        "forbidden_terms": list(case.forbidden_terms),
        "memories": [_memory_input_payload(item) for item in case.memories],
        "memory_scope_external_ref": case.memory_scope_external_ref,
        "metadata": case.metadata,
        "question": case.question,
        "thread_external_ref": case.thread_external_ref,
    }


def official_case_from_json(value: object) -> PublicBenchmarkCase:
    payload = canonical_mapping(
        value,
        code="scheduler_official_case_authority_case_json_invalid",
    )
    require_exact_keys(
        payload,
        _CASE_KEYS,
        code="scheduler_official_case_authority_case_json_invalid",
    )
    try:
        memories = tuple(_memory_input_from_payload(item) for item in _list(payload["memories"]))
        documents = tuple(_document_from_payload(item) for item in _list(payload["documents"]))
        conversations = tuple(
            _conversation_from_payload(item) for item in _list(payload["conversations"])
        )
        expected_terms = tuple(_strings(payload["expected_terms"]))
        forbidden_terms = tuple(_strings(payload["forbidden_terms"]))
        metadata = _dict(payload["metadata"])
        case = PublicBenchmarkCase(
            benchmark=_str(payload["benchmark"]),
            case_id=_str(payload["case_id"]),
            question=_str(payload["question"]),
            expected_terms=expected_terms,
            forbidden_terms=forbidden_terms,
            memories=memories,
            documents=documents,
            memory_scope_external_ref=_optional_str(payload["memory_scope_external_ref"]),
            thread_external_ref=_optional_str(payload["thread_external_ref"]),
            metadata=metadata,
            conversations=conversations,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_case_authority_case_json_invalid"
        ) from error
    if official_case_json(case) != value:
        _fail("scheduler_official_case_authority_case_json_invalid")
    return case


def retrieved_memory_json(memory: RetrievedMemory) -> str:
    if type(memory) is not RetrievedMemory:
        _fail("scheduler_retrieval_evidence_authority_memory_invalid")
    return canonical_text(retrieved_memory_payload(memory))


def retrieved_memory_payload(memory: RetrievedMemory) -> dict[str, object]:
    if (
        type(memory) is not RetrievedMemory
        or type(memory.source_refs) is not tuple
        or type(memory.metadata) is not dict
    ):
        _fail("scheduler_retrieval_evidence_authority_memory_invalid")
    return {
        "created_at": memory.created_at,
        "item_id": memory.item_id,
        "metadata": memory.metadata,
        "rank": memory.rank,
        "score": memory.score,
        "source_refs": list(memory.source_refs),
        "text": memory.text,
    }


def retrieved_memory_from_json(value: object) -> RetrievedMemory:
    payload = canonical_mapping(
        value,
        code="scheduler_retrieval_evidence_authority_memory_json_invalid",
    )
    require_exact_keys(
        payload,
        _RETRIEVED_MEMORY_KEYS,
        code="scheduler_retrieval_evidence_authority_memory_json_invalid",
    )
    try:
        score = payload["score"]
        if type(score) not in {int, float} or isinstance(score, bool):
            raise TypeError
        memory = RetrievedMemory(
            text=_str(payload["text"]),
            rank=_int(payload["rank"]),
            score=score,
            item_id=_optional_str(payload["item_id"]),
            created_at=_optional_str(payload["created_at"]),
            source_refs=tuple(_strings(payload["source_refs"])),
            metadata=_dict(payload["metadata"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_retrieval_evidence_authority_memory_json_invalid"
        ) from error
    if retrieved_memory_json(memory) != value:
        _fail("scheduler_retrieval_evidence_authority_memory_json_invalid")
    return memory


def _memory_input_payload(value: object) -> dict[str, object]:
    if type(value) is not BenchmarkMemoryInput or type(value.metadata) is not dict:
        _fail("scheduler_official_case_authority_case_invalid")
    return {
        "kind": value.kind,
        "metadata": value.metadata,
        "source_external_id": value.source_external_id,
        "text": value.text,
    }


def _document_payload(value: object) -> dict[str, object]:
    if (
        type(value) is not BenchmarkDocumentInput
        or type(value.source_refs) is not tuple
        or any(type(item) is not dict for item in value.source_refs)
    ):
        _fail("scheduler_official_case_authority_case_invalid")
    return {
        "classification": value.classification,
        "source_external_id": value.source_external_id,
        "source_refs": list(value.source_refs),
        "source_type": value.source_type,
        "text": value.text,
        "title": value.title,
    }


def _conversation_payload(value: object) -> dict[str, object]:
    if (
        type(value) is not BenchmarkConversationInput
        or type(value.messages) is not tuple
        or type(value.metadata) is not dict
    ):
        _fail("scheduler_official_case_authority_case_invalid")
    return {
        "messages": [_message_payload(item) for item in value.messages],
        "metadata": value.metadata,
        "session_date": value.session_date,
        "session_external_id": value.session_external_id,
        "source_external_id": value.source_external_id,
        "timestamp": value.timestamp,
    }


def _message_payload(value: object) -> dict[str, object]:
    if type(value) is not BenchmarkMessageInput or type(value.metadata) is not dict:
        _fail("scheduler_official_case_authority_case_invalid")
    return {
        "content": value.content,
        "metadata": value.metadata,
        "role": value.role,
        "source_external_id": value.source_external_id,
        "timestamp": value.timestamp,
    }


def _memory_input_from_payload(value: object) -> BenchmarkMemoryInput:
    payload = _mapping(value, _MEMORY_INPUT_KEYS)
    return BenchmarkMemoryInput(
        text=_str(payload["text"]),
        kind=_str(payload["kind"]),
        source_external_id=_optional_str(payload["source_external_id"]),
        metadata=_dict(payload["metadata"]),
    )


def _document_from_payload(value: object) -> BenchmarkDocumentInput:
    payload = _mapping(value, _DOCUMENT_KEYS)
    refs = _list(payload["source_refs"])
    if any(type(item) is not dict for item in refs):
        raise TypeError
    return BenchmarkDocumentInput(
        title=_str(payload["title"]),
        text=_str(payload["text"]),
        source_type=_str(payload["source_type"]),
        classification=_str(payload["classification"]),
        source_external_id=_optional_str(payload["source_external_id"]),
        source_refs=tuple(refs),
    )


def _conversation_from_payload(value: object) -> BenchmarkConversationInput:
    payload = _mapping(value, _CONVERSATION_KEYS)
    return BenchmarkConversationInput(
        messages=tuple(_message_from_payload(item) for item in _list(payload["messages"])),
        source_external_id=_optional_str(payload["source_external_id"]),
        session_external_id=_optional_str(payload["session_external_id"]),
        session_date=_optional_str(payload["session_date"]),
        timestamp=_optional_int(payload["timestamp"]),
        metadata=_dict(payload["metadata"]),
    )


def _message_from_payload(value: object) -> BenchmarkMessageInput:
    payload = _mapping(value, _MESSAGE_KEYS)
    role = _str(payload["role"])
    if role not in {"user", "assistant", "system"}:
        raise ValueError
    return BenchmarkMessageInput(
        role=role,  # type: ignore[arg-type]
        content=_str(payload["content"]),
        source_external_id=_optional_str(payload["source_external_id"]),
        timestamp=_optional_int(payload["timestamp"]),
        metadata=_dict(payload["metadata"]),
    )


def _mapping(value: object, keys: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != keys:
        raise TypeError
    return value


def _dict(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError
    return value


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise TypeError
    return value


def _strings(value: object) -> list[str]:
    values = _list(value)
    if any(type(item) is not str for item in values):
        raise TypeError
    return values  # type: ignore[return-value]


def _str(value: object) -> str:
    if type(value) is not str:
        raise TypeError
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise TypeError
    return value


def _optional_str(value: object) -> str | None:
    if value is not None and type(value) is not str:
        raise TypeError
    return value  # type: ignore[return-value]


def _optional_int(value: object) -> int | None:
    if value is not None and type(value) is not int:
        raise TypeError
    return value  # type: ignore[return-value]


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "official_case_from_json",
    "official_case_json",
    "official_case_payload",
    "retrieved_memory_from_json",
    "retrieved_memory_json",
    "retrieved_memory_payload",
)
