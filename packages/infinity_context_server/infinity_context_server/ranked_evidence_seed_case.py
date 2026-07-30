"""Gold-free seed projection for ranked-evidence retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_CONVERSATION_INDEX_KEYS = ("session_original_index", "pair_index")


@dataclass(frozen=True, slots=True)
class RankedEvidenceSeedCase:
    """Only source content and identities allowed at the seed boundary."""

    benchmark: str
    case_id: str
    memories: tuple[BenchmarkMemoryInput, ...]
    documents: tuple[BenchmarkDocumentInput, ...]
    memory_scope_external_ref: str
    thread_external_ref: str
    conversations: tuple[BenchmarkConversationInput, ...]


def ranked_evidence_seed_case(case: PublicBenchmarkCase) -> RankedEvidenceSeedCase:
    """Copy ingestion inputs while dropping all evaluator-side case fields."""

    return RankedEvidenceSeedCase(
        benchmark=case.benchmark,
        case_id=case.case_id,
        memories=tuple(_seed_memory(memory) for memory in case.memories),
        documents=tuple(_seed_document(document) for document in case.documents),
        memory_scope_external_ref=(
            case.memory_scope_external_ref or f"{case.benchmark}-{case.case_id}"
        ),
        thread_external_ref=(case.thread_external_ref or f"{case.benchmark}-{case.case_id}"),
        conversations=tuple(
            _seed_conversation(conversation) for conversation in case.conversations
        ),
    )


def _seed_memory(memory: BenchmarkMemoryInput) -> BenchmarkMemoryInput:
    role = memory.metadata.get("role")
    metadata = {"role": role} if isinstance(role, str) and role.strip() else {}
    return BenchmarkMemoryInput(
        text=memory.text,
        kind=memory.kind,
        source_external_id=memory.source_external_id,
        metadata=MappingProxyType(metadata),
    )


def _seed_document(document: BenchmarkDocumentInput) -> BenchmarkDocumentInput:
    return BenchmarkDocumentInput(
        title=document.title,
        text=document.text,
        source_type=document.source_type,
        classification=document.classification,
        source_external_id=document.source_external_id,
        source_refs=tuple(
            MappingProxyType(dict(source_ref)) for source_ref in document.source_refs
        ),
    )


def _seed_conversation(
    conversation: BenchmarkConversationInput,
) -> BenchmarkConversationInput:
    metadata = {
        key: conversation.metadata[key]
        for key in _CONVERSATION_INDEX_KEYS
        if _is_non_negative_int(conversation.metadata.get(key))
    }
    return BenchmarkConversationInput(
        messages=tuple(_seed_message(message) for message in conversation.messages),
        source_external_id=conversation.source_external_id,
        session_external_id=conversation.session_external_id,
        session_date=conversation.session_date,
        timestamp=conversation.timestamp,
        metadata=MappingProxyType(metadata),
    )


def _seed_message(message: BenchmarkMessageInput) -> BenchmarkMessageInput:
    return BenchmarkMessageInput(
        role=message.role,
        content=message.content,
        source_external_id=message.source_external_id,
        timestamp=message.timestamp,
        metadata=MappingProxyType({}),
    )


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = (
    "RankedEvidenceSeedCase",
    "ranked_evidence_seed_case",
)
