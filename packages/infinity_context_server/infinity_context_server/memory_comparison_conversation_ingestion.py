"""Adapter-facing projections of provider-neutral benchmark conversations."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_server.memory_comparison_case_identity import (
    safe_benchmark_identifier,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkDocumentInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

_SUPPORTED_ROLES = frozenset({"user", "assistant", "system"})


def conversation_documents(case: PublicBenchmarkCase) -> tuple[BenchmarkDocumentInput, ...]:
    """Render each typed operation as one canonical Infinity conversation document."""

    documents: list[BenchmarkDocumentInput] = []
    for index, conversation in enumerate(case.conversations, start=1):
        messages = valid_conversation_messages(conversation)
        if not messages:
            continue
        pair_id = _conversation_id(case, conversation, index=index)
        session_id = _session_id(conversation, index=index)
        header = _session_header(conversation, session_id=session_id)
        text_lines = [header]
        text_lines.extend(f"{message.role}: {message.content}" for message in messages)
        pair_preview = " ".join(text_lines[1:])
        source_refs = [
            source_ref_payload(
                source_type="benchmark_conversation_pair",
                source_id=pair_id,
                quote_preview=pair_preview,
            ),
            source_ref_payload(
                source_type="benchmark_conversation_session",
                source_id=session_id,
                quote_preview=header,
            ),
        ]
        source_refs.extend(
            source_ref_payload(
                source_type="benchmark_conversation_message",
                source_id=safe_benchmark_identifier(
                    message.source_external_id or f"{pair_id}:message:{position}",
                    max_chars=160,
                ),
                quote_preview=message.content,
            )
            for position, message in enumerate(messages, start=1)
        )
        pair_number = _non_negative_int(conversation.metadata.get("pair_index"))
        if pair_number is None:
            pair_number = index - 1
        documents.append(
            BenchmarkDocumentInput(
                title=f"Conversation {session_id} pair {pair_number + 1}",
                text="\n".join(text_lines),
                source_type="benchmark_conversation_pair",
                classification="internal",
                source_external_id=pair_id,
                source_refs=tuple(source_refs),
            )
        )
    return tuple(documents)


def conversation_metadata(
    case: PublicBenchmarkCase,
    conversation: BenchmarkConversationInput,
    *,
    index: int,
) -> dict[str, object]:
    pair_id = _conversation_id(case, conversation, index=index)
    metadata: dict[str, object] = {
        "source_external_id": pair_id,
        "source_id": pair_id,
    }
    if conversation.session_external_id:
        session_id = _session_id(conversation, index=index)
        metadata["session_id"] = session_id
        metadata["session_external_id"] = session_id
    if conversation.session_date and conversation.session_date.strip():
        metadata["session_date"] = safe_preview(conversation.session_date, max_chars=120)
    if _non_negative_int(conversation.timestamp) is not None:
        metadata["source_timestamp"] = conversation.timestamp
    message_source_ids = tuple(
        safe_benchmark_identifier(message.source_external_id, max_chars=160)
        for message in valid_conversation_messages(conversation)
        if message.source_external_id
    )
    if message_source_ids:
        metadata["message_source_ids"] = list(message_source_ids)
    for key in ("session_original_index", "pair_index"):
        value = _non_negative_int(conversation.metadata.get(key))
        if value is not None:
            metadata[key] = value
    return metadata


def conversation_message_payloads(
    conversation: BenchmarkConversationInput,
) -> tuple[dict[str, str], ...]:
    """Keep message content intact while dropping non-message metadata."""

    return tuple(
        {"role": message.role, "content": message.content}
        for message in valid_conversation_messages(conversation)
    )


def valid_conversation_messages(
    conversation: BenchmarkConversationInput,
) -> tuple[BenchmarkMessageInput, ...]:
    return tuple(
        message
        for message in conversation.messages
        if message.role in _SUPPORTED_ROLES
        and isinstance(message.content, str)
        and bool(message.content.strip())
    )


def source_ref_payload(
    *,
    source_type: str,
    source_id: str,
    quote_preview: str,
) -> dict[str, object]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "quote_preview": safe_preview(quote_preview),
    }


def sanitize_source_refs(
    source_refs: tuple[Mapping[str, object], ...],
) -> list[dict[str, object]]:
    sanitized: list[dict[str, object]] = []
    for source_ref in source_refs:
        payload = dict(source_ref)
        quote_preview = payload.get("quote_preview")
        if isinstance(quote_preview, str):
            payload["quote_preview"] = safe_preview(quote_preview)
        sanitized.append(payload)
    return sanitized


def safe_preview(value: str, *, max_chars: int = 240) -> str:
    return redact_sensitive_text(str(value or ""))[:max_chars]


def _conversation_id(
    case: PublicBenchmarkCase,
    conversation: BenchmarkConversationInput,
    *,
    index: int,
) -> str:
    return safe_benchmark_identifier(
        conversation.source_external_id or f"{case.case_id}:conversation:{index}",
        max_chars=240,
    )


def _session_id(conversation: BenchmarkConversationInput, *, index: int) -> str:
    return safe_benchmark_identifier(
        conversation.session_external_id or f"session-{index}",
        max_chars=160,
    )


def _session_header(
    conversation: BenchmarkConversationInput,
    *,
    session_id: str,
) -> str:
    if conversation.session_date and conversation.session_date.strip():
        return f"{session_id} date: {safe_preview(conversation.session_date, max_chars=120)}"
    return session_id


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


# Compatibility aliases for internal call sites.
typed_message_payloads = conversation_message_payloads
mem0_conversation_metadata = conversation_metadata
