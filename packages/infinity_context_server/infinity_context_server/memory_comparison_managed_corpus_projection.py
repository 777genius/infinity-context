"""Gold-blind managed-ingest projection derived only from benchmark corpus inputs."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from types import MappingProxyType

from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedAnswerCase,
    ManagedRunError,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION = "memory-comparison-managed-corpus.v2"
_SESSION_ALIAS = re.compile(r"session-[0-9]{4}")
_OPAQUE_ID = re.compile(r"(locomo|longmemeval)-(corpus|thread)-[0-9a-f]{64}")
_SOURCE_ALIAS = re.compile(r"(?:memory|document)-[0-9]{6}")
_CONVERSATION_ALIAS = re.compile(r"conversation-[0-9]{4}")
_MESSAGE_ALIAS = re.compile(r"conversation-[0-9]{4}-message-[0-9]{4}")
_MANAGED_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")
_TOP_LEVEL_KEYS = {
    "schema_version",
    "benchmark",
    "corpus_id",
    "thread_id",
    "memories",
    "documents",
    "conversations",
}
_MEMORY_KEYS = {
    "kind",
    "role",
    "session_alias",
    "source_alias",
    "speaker",
    "session_date",
    "text",
    "timestamp",
}
_DOCUMENT_KEYS = {
    "classification",
    "source_alias",
    "source_type",
    "text",
    "title",
}
_CONVERSATION_KEYS = {
    "messages",
    "session_alias",
    "session_date",
    "source_alias",
    "timestamp",
}
_MESSAGE_KEYS = {"content", "role", "source_alias", "timestamp"}


def _managed_corpus_identity(case: PublicBenchmarkCase) -> tuple[str, str]:
    _exact_case(case)
    corpus_source = _scope_source(case.memory_scope_external_ref, case.case_id)
    thread_source = _scope_source(case.thread_external_ref, corpus_source)
    return (
        _opaque_identity(case.benchmark, "corpus", corpus_source),
        _opaque_identity(case.benchmark, "thread", thread_source),
    )


def _managed_corpus_record(case: PublicBenchmarkCase) -> dict[str, object]:
    """Return a fresh JSON projection without QA, evidence, evaluator or raw IDs."""

    corpus_id, thread_id = _managed_corpus_identity(case)
    official_locomo = (
        case.benchmark == "locomo" and case.metadata.get("locomo_ingest_mode") == "official-turns"
    )
    session_aliases: dict[str, str] = {}
    memories: list[dict[str, object]] = []
    for index, memory in enumerate(case.memories, start=1):
        raw_session = memory.metadata.get("session_key")
        session_key = raw_session if type(raw_session) is str and raw_session else "memory"
        session_alias = session_aliases.setdefault(
            session_key,
            f"session-{len(session_aliases) + 1:04d}",
        )
        item: dict[str, object] = {
            "kind": memory.kind,
            "role": _memory_role(
                memory.metadata.get("role"),
                required=official_locomo,
            ),
            "session_alias": session_alias,
            "source_alias": f"memory-{index:06d}",
            "speaker": _projection_optional_string(
                memory.metadata.get("speaker"), "memory speaker"
            ),
            "session_date": _projection_optional_string(
                memory.metadata.get("session_date"), "memory session_date"
            ),
            "text": _memory_text(memory.text, memory.metadata),
            "timestamp": _projection_optional_int(
                memory.metadata.get("timestamp"), "memory timestamp"
            ),
        }
        memories.append(item)

    documents = [
        {
            "classification": document.classification,
            "source_alias": f"document-{index:06d}",
            "source_type": document.source_type,
            "text": document.text,
            "title": document.title,
        }
        for index, document in enumerate(case.documents, start=1)
    ]
    conversations: list[dict[str, object]] = []
    conversation_sessions: dict[str, str] = {}
    for conversation_index, conversation in enumerate(case.conversations, start=1):
        raw_session = conversation.session_external_id
        session_key = (
            raw_session
            if type(raw_session) is str and raw_session
            else f"conversation-{conversation_index:04d}"
        )
        session_alias = conversation_sessions.setdefault(
            session_key, f"session-{len(conversation_sessions) + 1:04d}"
        )
        projected: dict[str, object] = {
            "messages": [
                {
                    "content": message.content,
                    "role": message.role,
                    "source_alias": (
                        f"conversation-{conversation_index:04d}-message-{message_index:04d}"
                    ),
                    "timestamp": _projection_optional_int(message.timestamp, "message timestamp"),
                }
                for message_index, message in enumerate(conversation.messages, start=1)
            ],
            "session_alias": session_alias,
            "session_date": _projection_optional_string(
                conversation.session_date, "conversation session_date"
            ),
            "source_alias": f"conversation-{conversation_index:04d}",
            "timestamp": _projection_optional_int(conversation.timestamp, "conversation timestamp"),
        }
        conversations.append(projected)

    return {
        "schema_version": MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION,
        "benchmark": case.benchmark,
        "corpus_id": corpus_id,
        "thread_id": thread_id,
        "memories": memories,
        "documents": documents,
        "conversations": conversations,
    }


def _reconstruct_managed_corpus_case(
    record: object,
    answer_case: ManagedAnswerCase | None = None,
    *,
    case_id: str | None = None,
    question: str | None = None,
    temporal_context: Mapping[str, object] | None = None,
) -> PublicBenchmarkCase:
    """Rebuild an HTTP-backend case from the admitted gold-blind projection."""

    benchmark, corpus_id, thread_id, memories, documents, conversations = _validated_projection(
        record
    )
    resolved_case_id, resolved_question, resolved_temporal = _answer_material(
        answer_case,
        case_id=case_id,
        question=question,
        temporal_context=temporal_context,
    )
    if benchmark == "locomo":
        transport_sample = _transport_sample_alias(corpus_id)
        transport_case_id = _transport_case_alias(transport_sample, resolved_case_id)
        rebuilt_memories = _reconstructed_locomo_memories(memories, transport_sample)
        metadata: dict[str, object] = {
            **resolved_temporal,
            "locomo_ingest_mode": "official-turns",
            "public_trigger_case_id": resolved_case_id,
        }
    else:
        transport_case_id = resolved_case_id
        rebuilt_memories = tuple(
            BenchmarkMemoryInput(
                text=item["text"],
                kind=item["kind"],
                source_external_id=f"{corpus_id}:{item['source_alias']}",
                metadata=_memory_metadata(item),
            )
            for item in memories
        )
        metadata = dict(resolved_temporal)
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id=transport_case_id,
        question=resolved_question,
        expected_terms=(),
        forbidden_terms=(),
        memories=rebuilt_memories,
        documents=tuple(
            BenchmarkDocumentInput(
                title=item["title"],
                text=item["text"],
                source_type=item["source_type"],
                classification=item["classification"],
                source_external_id=f"{corpus_id}:{item['source_alias']}",
                source_refs=(),
            )
            for item in documents
        ),
        memory_scope_external_ref=corpus_id,
        thread_external_ref=thread_id,
        metadata=metadata,
        conversations=_reconstructed_conversations(conversations, corpus_id),
    )


def _validated_projection(
    record: object,
) -> tuple[
    str,
    str,
    str,
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    value = _exact_object(record, _TOP_LEVEL_KEYS, "managed corpus projection")
    if value["schema_version"] != MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION:
        raise ManagedRunError("managed corpus projection schema version is invalid")
    benchmark = value["benchmark"]
    if type(benchmark) is not str or benchmark not in {"locomo", "longmemeval"}:
        raise ManagedRunError("managed corpus projection benchmark is invalid")
    corpus_id = _opaque_projection_id(value["corpus_id"], benchmark, "corpus")
    thread_id = _opaque_projection_id(value["thread_id"], benchmark, "thread")
    memories = _validated_memories(value["memories"], benchmark=benchmark)
    documents = _validated_documents(value["documents"])
    conversations = _validated_conversations(value["conversations"])
    if benchmark == "locomo" and (not memories or documents or conversations):
        raise ManagedRunError("LoCoMo projection must contain only official turn memories")
    if benchmark == "longmemeval" and (memories or documents or not conversations):
        raise ManagedRunError(
            "LongMemEval projection must contain only nonempty pair conversations"
        )
    return benchmark, corpus_id, thread_id, memories, documents, conversations


def _validated_memories(
    value: object,
    *,
    benchmark: str,
) -> tuple[dict[str, object], ...]:
    items = _exact_list(value, "managed corpus memories")
    result: list[dict[str, object]] = []
    seen_sessions: list[str] = []
    for index, raw in enumerate(items, start=1):
        item = _exact_object(raw, _MEMORY_KEYS, "managed corpus memory")
        _expected_alias(item["source_alias"], f"memory-{index:06d}", _SOURCE_ALIAS)
        session_alias = _session_alias(item["session_alias"], seen_sessions)
        kind = _required_string(item["kind"], "memory kind")
        role = _role(item["role"])
        text = _required_string(item["text"], "memory text")
        speaker = _nullable_string(item["speaker"], "memory speaker")
        session_date = _nullable_string(item["session_date"], "memory session_date")
        timestamp = _nullable_int(item["timestamp"], "memory timestamp")
        if benchmark == "locomo" and (
            role == "system" or speaker is None or session_date is None or timestamp is None
        ):
            raise ManagedRunError("LoCoMo official turn semantics are incomplete")
        result.append(
            {
                "kind": kind,
                "role": role,
                "session_alias": session_alias,
                "source_alias": item["source_alias"],
                "speaker": speaker,
                "session_date": session_date,
                "text": text,
                "timestamp": timestamp,
            }
        )
    return tuple(result)


def _validated_documents(value: object) -> tuple[dict[str, object], ...]:
    items = _exact_list(value, "managed corpus documents")
    result: list[dict[str, object]] = []
    for index, raw in enumerate(items, start=1):
        item = _exact_object(raw, _DOCUMENT_KEYS, "managed corpus document")
        _expected_alias(item["source_alias"], f"document-{index:06d}", _SOURCE_ALIAS)
        result.append(
            {key: _required_string(item[key], f"document {key}") for key in _DOCUMENT_KEYS}
        )
    return tuple(result)


def _validated_conversations(value: object) -> tuple[dict[str, object], ...]:
    items = _exact_list(value, "managed corpus conversations")
    result: list[dict[str, object]] = []
    seen_sessions: list[str] = []
    for conversation_index, raw in enumerate(items, start=1):
        item = _exact_object(raw, _CONVERSATION_KEYS, "managed corpus conversation")
        source_alias = f"conversation-{conversation_index:04d}"
        _expected_alias(item["source_alias"], source_alias, _CONVERSATION_ALIAS)
        session_alias = _session_alias(item["session_alias"], seen_sessions)
        messages = _exact_list(item["messages"], "managed corpus messages")
        if not messages:
            raise ManagedRunError("managed corpus conversation has no messages")
        validated_messages: list[dict[str, object]] = []
        for message_index, raw_message in enumerate(messages, start=1):
            message = _exact_object(raw_message, _MESSAGE_KEYS, "managed corpus message")
            message_alias = f"{source_alias}-message-{message_index:04d}"
            _expected_alias(message["source_alias"], message_alias, _MESSAGE_ALIAS)
            validated_messages.append(
                {
                    "content": _required_string(message["content"], "message content"),
                    "role": _role(message["role"]),
                    "source_alias": message_alias,
                    "timestamp": _nullable_int(message["timestamp"], "message timestamp"),
                }
            )
        result.append(
            {
                "messages": tuple(validated_messages),
                "session_alias": session_alias,
                "session_date": _nullable_string(item["session_date"], "conversation session_date"),
                "source_alias": source_alias,
                "timestamp": _nullable_int(item["timestamp"], "conversation timestamp"),
            }
        )
    return tuple(result)


def _reconstructed_locomo_memories(
    memories: tuple[dict[str, object], ...],
    sample_alias: str,
) -> tuple[BenchmarkMemoryInput, ...]:
    session_ordinals: dict[str, int] = {}
    turn_counts: dict[str, int] = {}
    result: list[BenchmarkMemoryInput] = []
    for item in memories:
        alias = item["session_alias"]
        assert type(alias) is str
        session_ordinal = session_ordinals.setdefault(alias, len(session_ordinals) + 1)
        turn_ordinal = turn_counts.get(alias, 0) + 1
        turn_counts[alias] = turn_ordinal
        alias_number = 900_000 + session_ordinal
        session_key = f"session_{alias_number}"
        dia_id = f"D{alias_number}:{turn_ordinal}"
        source_external_id = f"locomo:{sample_alias}:{session_key}:{dia_id}:turn"
        speaker = item["speaker"]
        session_date = item["session_date"]
        timestamp = item["timestamp"]
        text = item["text"]
        assert type(speaker) is str
        assert type(session_date) is str
        assert type(timestamp) is int
        assert type(text) is str
        result.append(
            BenchmarkMemoryInput(
                text=f"{session_key} date: {session_date}\n{dia_id} {speaker}: {text}",
                kind=item["kind"],
                source_external_id=source_external_id,
                metadata={
                    "role": item["role"],
                    "timestamp": timestamp,
                    "session_key": session_key,
                    "session_date": session_date,
                    "dia_id": dia_id,
                    "speaker": speaker,
                },
            )
        )
    return tuple(result)


def _reconstructed_conversations(
    conversations: tuple[dict[str, object], ...],
    corpus_id: str,
) -> tuple[BenchmarkConversationInput, ...]:
    session_ordinals: dict[str, int] = {}
    pair_counts: dict[str, int] = {}
    result: list[BenchmarkConversationInput] = []
    for item in conversations:
        alias = item["session_alias"]
        assert type(alias) is str
        session_index = session_ordinals.setdefault(alias, len(session_ordinals))
        pair_index = pair_counts.get(alias, 0)
        pair_counts[alias] = pair_index + 1
        source_alias = item["source_alias"]
        assert type(source_alias) is str
        result.append(
            BenchmarkConversationInput(
                messages=tuple(
                    BenchmarkMessageInput(
                        role=message["role"],
                        content=message["content"],
                        source_external_id=f"{corpus_id}:{message['source_alias']}",
                        timestamp=message["timestamp"],
                    )
                    for message in item["messages"]
                ),
                source_external_id=f"{corpus_id}:{source_alias}",
                session_external_id=f"{corpus_id}:{alias}",
                session_date=item["session_date"],
                timestamp=item["timestamp"],
                metadata={
                    "session_original_index": session_index,
                    "pair_index": pair_index,
                },
            )
        )
    return tuple(result)


def _answer_material(
    answer_case: ManagedAnswerCase | None,
    *,
    case_id: str | None,
    question: str | None,
    temporal_context: Mapping[str, object] | None,
) -> tuple[str, str, dict[str, object]]:
    if answer_case is not None:
        if (
            type(answer_case) is not ManagedAnswerCase
            or case_id is not None
            or question is not None
            or temporal_context is not None
        ):
            raise ManagedRunError("managed answer material modes are mutually exclusive")
        return (
            answer_case.case_id,
            answer_case.question,
            _validated_temporal_context(dict(answer_case.temporal_context)),
        )
    resolved_id = _required_string(case_id, "answer case_id")
    if _MANAGED_CASE_ID.fullmatch(resolved_id) is None:
        raise ManagedRunError("answer case_id is invalid")
    resolved_question = _required_string(question, "answer question")
    if type(temporal_context) is not dict:
        raise ManagedRunError("answer temporal context must be an exact dict")
    resolved_temporal = _validated_temporal_context(temporal_context)
    return resolved_id, resolved_question, resolved_temporal


def _validated_temporal_context(value: dict[str, object]) -> dict[str, object]:
    resolved = dict(value)
    if not set(resolved).issubset({"question_type", "question_date", "reference_date"}) or any(
        type(key) is not str
        or type(item) not in {str, int, float}
        or (type(item) is float and not math.isfinite(item))
        for key, item in resolved.items()
    ):
        raise ManagedRunError("answer temporal context must contain exact scalar JSON values")
    return resolved


def _memory_metadata(item: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(
        {
            key: item[key]
            for key in ("role", "speaker", "session_date", "timestamp")
            if item[key] is not None
        }
    )


def _transport_sample_alias(corpus_id: str) -> str:
    return f"managed{hashlib.sha256(corpus_id.encode()).hexdigest()[:32]}"


def _transport_case_alias(sample_alias: str, managed_case_id: str) -> str:
    ordinal = int(hashlib.sha256(managed_case_id.encode()).hexdigest()[:16], 16) + 1
    return f"{sample_alias}:qa:{ordinal}"


def _exact_object(value: object, keys: set[str], name: str) -> dict[str, object] | MappingProxyType:
    if type(value) not in {dict, MappingProxyType} or set(value) != keys:
        raise ManagedRunError(f"{name} fields are not exact")
    return value


def _exact_list(value: object, name: str) -> list[object] | tuple[object, ...]:
    if type(value) not in {list, tuple}:
        raise ManagedRunError(f"{name} must be an exact JSON sequence")
    return value


def _opaque_projection_id(value: object, benchmark: str, kind: str) -> str:
    if (
        type(value) is not str
        or _OPAQUE_ID.fullmatch(value) is None
        or not value.startswith(f"{benchmark}-{kind}-")
    ):
        raise ManagedRunError(f"managed corpus {kind}_id is invalid")
    return value


def _expected_alias(value: object, expected: str, pattern: re.Pattern[str]) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None or value != expected:
        raise ManagedRunError("managed corpus source alias sequence is invalid")


def _session_alias(value: object, seen: list[str]) -> str:
    if type(value) is not str or _SESSION_ALIAS.fullmatch(value) is None:
        raise ManagedRunError("managed corpus session alias is invalid")
    if value not in seen:
        expected = f"session-{len(seen) + 1:04d}"
        if value != expected:
            raise ManagedRunError("managed corpus session alias sequence is invalid")
        seen.append(value)
    return value


def _required_string(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ManagedRunError(f"{name} is invalid")
    return value


def _nullable_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, name)


def _nullable_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ManagedRunError(f"{name} is invalid")
    return value


def _role(value: object) -> str:
    if type(value) is not str or value not in {"user", "assistant", "system"}:
        raise ManagedRunError("managed corpus message role is invalid")
    return value


def _managed_corpus_session_mapping(
    record: object,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Derive case-local session coverage only from the sanitized corpus projection."""

    if type(record) is not dict:
        raise ManagedRunError("managed corpus session mapping requires an exact projection")
    benchmark = record.get("benchmark")
    source_name = {"locomo": "memories", "longmemeval": "conversations"}.get(benchmark)
    source = record.get(source_name) if source_name is not None else None
    if type(source) is not list:
        raise ManagedRunError("managed corpus projection has no authoritative sessions")
    aliases: list[str] = []
    for item in source:
        alias = item.get("session_alias") if type(item) is dict else None
        if type(alias) is not str or _SESSION_ALIAS.fullmatch(alias) is None:
            raise ManagedRunError("managed corpus projection session alias is invalid")
        if alias not in aliases:
            aliases.append(alias)
    if not aliases:
        raise ManagedRunError("managed corpus projection has no authoritative sessions")
    return (
        tuple(f"memory-{index:04d}" for index in range(1, len(aliases) + 1)),
        tuple(aliases),
    )


def _managed_official_turn_count(record: object) -> int:
    if type(record) is not dict:
        raise ManagedRunError("managed corpus turn count requires an exact projection")
    if record.get("benchmark") != "locomo":
        return 0
    memories = record.get("memories")
    if type(memories) is not list or not memories:
        raise ManagedRunError("LoCoMo managed corpus has no official turns")
    return len(memories)


def _scope_source(value: object, fallback: str) -> str:
    if type(value) is str and value and value == value.strip():
        return value
    return fallback


def _projection_optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or value != value.strip():
        raise ManagedRunError(f"{name} is invalid")
    return value


def _projection_optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ManagedRunError(f"{name} is invalid")
    return value


def _opaque_identity(benchmark: str, kind: str, source: str) -> str:
    digest = hashlib.sha256(f"{benchmark}\0{kind}\0{source}".encode()).hexdigest()
    return f"{benchmark}-{kind}-{digest}"


def _memory_role(value: object, *, required: bool) -> str:
    if value is None and not required:
        return "user"
    if type(value) is str and value in {"user", "assistant", "system"}:
        return value
    raise ManagedRunError("memory role is invalid")


def _memory_text(text: str, metadata: object) -> str:
    if not isinstance(metadata, Mapping):
        return text
    result = text
    session_key = metadata.get("session_key")
    session_date = metadata.get("session_date")
    if type(session_key) is str and type(session_date) is str and session_date:
        date_prefix = f"{session_key} date: {session_date}\n"
        if result.startswith(date_prefix):
            result = result[len(date_prefix) :]
    dia_id = metadata.get("dia_id")
    speaker = metadata.get("speaker")
    if type(dia_id) is str and type(speaker) is str:
        turn_prefix = f"{dia_id} {speaker}: "
        if result.startswith(turn_prefix):
            result = result[len(turn_prefix) :]
    return result


def _exact_case(case: object) -> PublicBenchmarkCase:
    if type(case) is not PublicBenchmarkCase:
        raise ManagedRunError("managed corpus projection requires an exact benchmark case")
    return case


__all__ = ("MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION",)
