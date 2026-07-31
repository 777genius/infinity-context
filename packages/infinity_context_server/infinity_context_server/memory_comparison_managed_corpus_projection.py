"""Gold-blind managed-ingest projection derived only from benchmark corpus inputs."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

MANAGED_CORPUS_PROJECTION_SCHEMA_VERSION = "memory-comparison-managed-corpus.v1"
_SESSION_ALIAS = re.compile(r"session-[0-9]{4}")


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
            "role": _memory_role(memory.metadata.get("role")),
            "session_alias": session_alias,
            "source_alias": f"memory-{index:06d}",
            "text": _memory_text(memory.text, memory.metadata),
        }
        timestamp = memory.metadata.get("timestamp")
        if type(timestamp) is int:
            item["timestamp"] = timestamp
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
                    **({"timestamp": message.timestamp} if type(message.timestamp) is int else {}),
                }
                for message_index, message in enumerate(conversation.messages, start=1)
            ],
            "session_alias": session_alias,
            "source_alias": f"conversation-{conversation_index:04d}",
        }
        if type(conversation.session_date) is str and conversation.session_date:
            projected["session_date"] = conversation.session_date
        if type(conversation.timestamp) is int:
            projected["timestamp"] = conversation.timestamp
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


def _opaque_identity(benchmark: str, kind: str, source: str) -> str:
    digest = hashlib.sha256(f"{benchmark}\0{kind}\0{source}".encode()).hexdigest()
    return f"{benchmark}-{kind}-{digest}"


def _memory_role(value: object) -> str:
    return value if type(value) is str and value in {"user", "assistant", "system"} else "user"


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
