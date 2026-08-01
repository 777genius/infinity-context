"""Pure request construction helpers for HTTP comparison ingestion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_canonical_source_hash import (
    CanonicalSourceHash,
    conversation_source_hashes,
    document_source_hash,
    memory_source_hash,
    validate_unambiguous_source_hashes,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_message_payloads,
    conversation_metadata,
    safe_preview,
    source_ref_payload,
)
from infinity_context_server.public_benchmark_checkpoint import safe_identifier
from infinity_context_server.public_benchmark_models import (
    BenchmarkDocumentInput,
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)


def mirrored_memory_documents(
    case: PublicBenchmarkCase,
) -> tuple[BenchmarkDocumentInput, ...]:
    if case.documents:
        return ()
    documents: list[BenchmarkDocumentInput] = []
    for index, memory in enumerate(case.memories, start=1):
        source_external_id = memory.source_external_id or f"{case.case_id}:memory:{index}"
        documents.append(
            BenchmarkDocumentInput(
                title=f"Raw memory turn {index}",
                text=memory.text,
                source_type="memory_comparison_raw_turn",
                classification="internal",
                source_external_id=f"{source_external_id}:raw-turn-document",
                source_refs=(
                    source_reference_payload(
                        source_type="memory_comparison_benchmark",
                        source_id=safe_identifier(source_external_id, max_chars=160),
                        quote_preview=memory.text[:240],
                    ),
                ),
            )
        )
    return tuple(documents)


def source_reference_payload(
    *,
    source_type: str,
    source_id: str,
    quote_preview: str,
) -> dict[str, object]:
    return source_ref_payload(
        source_type=source_type,
        source_id=source_id,
        quote_preview=quote_preview,
    )


def source_temporal_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    timestamp = optional_int(metadata.get("source_timestamp"))
    if timestamp is None:
        timestamp = optional_int(metadata.get("timestamp"))
    result: dict[str, object] = {}
    if timestamp is not None:
        result["source_timestamp"] = timestamp
    for key in ("session_key", "session_date", "dia_id", "role"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value
    return result


def case_message_groups(
    case: PublicBenchmarkCase,
) -> tuple[tuple[tuple[dict[str, str], ...], int | None, dict[str, object]], ...]:
    groups: list[tuple[tuple[dict[str, str], ...], int | None, dict[str, object]]] = []
    identities: list[CanonicalSourceHash] = []
    if case.conversations:
        conversation_identities = iter(conversation_source_hashes(case))
        for index, conversation in enumerate(case.conversations, start=1):
            messages = conversation_message_payloads(conversation)
            if messages:
                identity = next(conversation_identities, None)
                if identity is None:
                    raise ValueError("canonical conversation identity rendering drifted")
                metadata = conversation_metadata(case, conversation, index=index)
                metadata_source_id = metadata.get("source_id")
                if (
                    not isinstance(metadata_source_id, str)
                    or safe_identifier(metadata_source_id, max_chars=160)
                    != identity.source_id
                ):
                    raise ValueError("canonical conversation source_id rendering drifted")
                metadata.update(identity.metadata())
                groups.append(
                    (
                        messages,
                        conversation.timestamp,
                        metadata,
                    )
                )
                identities.append(identity)
        if next(conversation_identities, None) is not None:
            raise ValueError("canonical conversation identity rendering drifted")
        return tuple(groups)
    for memory in case.memories:
        identity = memory_source_hash(memory)
        metadata = _mem0_source_metadata(memory)
        if metadata.get("source_id") != identity.source_id:
            raise ValueError("canonical memory source_id projection drifted")
        metadata.update(identity.metadata())
        groups.append(
            (
                (
                    {
                        "role": message_role(memory.metadata.get("role")),
                        "content": memory.text,
                    },
                ),
                optional_int(memory.metadata.get("timestamp")),
                metadata,
            )
        )
        identities.append(identity)
    for document in case.documents:
        identity = document_source_hash(document)
        metadata = _mem0_document_metadata(document)
        if metadata.get("source_id") != identity.source_id:
            raise ValueError("canonical document source_id projection drifted")
        metadata.update(identity.metadata())
        groups.append(
            (
                ({"role": "user", "content": document.text},),
                None,
                metadata,
            )
        )
        identities.append(identity)
    validate_unambiguous_source_hashes(tuple(identities))
    return tuple(groups)


def messages_preview(messages: Sequence[Mapping[str, str]]) -> str:
    content = " ".join(str(message.get("content", "")) for message in messages)
    return safe_preview(content)


def optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def message_role(value: object) -> str:
    role = str(value or "user").strip().lower()
    return role if role in {"user", "assistant", "system"} else "user"


def _mem0_source_metadata(memory: BenchmarkMemoryInput) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if memory.source_external_id:
        metadata["source_external_id"] = memory.source_external_id
        metadata["source_id"] = safe_identifier(memory.source_external_id, max_chars=160)
    for key in ("session_key", "session_date", "dia_id", "role", "speaker"):
        value = memory.metadata.get(key)
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
    source_timestamp = optional_int(memory.metadata.get("timestamp"))
    if source_timestamp is not None:
        metadata["source_timestamp"] = source_timestamp
    dia_id = metadata.get("dia_id")
    if isinstance(dia_id, str) and dia_id.strip():
        metadata["locomo_evidence_ref"] = dia_id.strip()
    return metadata


def _mem0_document_metadata(document: BenchmarkDocumentInput) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if document.source_external_id:
        metadata["source_external_id"] = document.source_external_id
        metadata["source_id"] = safe_identifier(
            document.source_external_id,
            max_chars=160,
        )
    source_ids = tuple(
        str(ref.get("source_id"))
        for ref in document.source_refs
        if isinstance(ref, Mapping) and ref.get("source_id")
    )
    if source_ids:
        metadata["source_refs"] = list(source_ids)
    return metadata
