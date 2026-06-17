"""Row serialization helpers for memory_scope snapshot transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memo_stack_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryCaptureRow,
    MemoryChunkRow,
    MemoryContextLinkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRow,
    MemorySourceRefRow,
)
from memo_stack_core.application.safe_payload import safe_metadata, safe_metadata_text


def contains_redacted_memory(
    payload: dict[str, Any],
    *,
    facts: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    captures: list[dict[str, Any]],
) -> bool:
    if payload.get("redacted") is True:
        return True
    if any(fact.get("text") is None for fact in facts):
        return True
    if any(episode.get("text") is None for episode in episodes):
        return True
    if any(capture.get("text_redacted") is None for capture in captures):
        return True
    return any(
        chunk.get("text") is None or chunk.get("normalized_text") is None for chunk in chunks
    )


def fact_to_json(row: MemoryFactRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "kind": row.kind,
        "text": None if redacted else row.text,
        "status": row.status,
        "confidence": row.confidence,
        "trust_level": row.trust_level,
        "classification": row.classification,
        "category": row.category,
        "tags": list(row.tags_json or []),
        "ttl_policy": row.ttl_policy,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def document_to_json(row: MemoryDocumentRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "title": row.title,
        "source_type": row.source_type,
        "source_external_id": row.source_external_id,
        "content_hash": row.content_hash,
        "classification": row.classification,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def episode_to_json(row: MemoryEpisodeRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "source_type": row.source_type,
        "source_external_id": row.source_external_id,
        "text": None if redacted else row.text,
        "speaker": row.speaker,
        "trust_level": row.trust_level,
        "status": row.status,
        "occurred_at": row.occurred_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "metadata_json": safe_metadata(row.metadata_json),
    }


def chunk_to_json(row: MemoryChunkRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "document_id": row.document_id,
        "episode_id": row.episode_id,
        "source_type": row.source_type,
        "source_external_id": row.source_external_id,
        "source_hash": row.source_hash,
        "kind": row.kind,
        "text": None if redacted else row.text,
        "normalized_text": None if redacted else row.normalized_text,
        "status": row.status,
        "sequence": row.sequence,
        "char_start": row.char_start,
        "char_end": row.char_end,
        "token_estimate": row.token_estimate,
        "classification": row.classification,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "metadata_json": safe_metadata(row.metadata_json),
    }


def source_ref_to_json(row: MemorySourceRefRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "fact_id": row.fact_id,
        "fact_version": row.fact_version,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "chunk_id": row.chunk_id,
        "char_start": row.char_start,
        "char_end": row.char_end,
        "quote_preview": None if redacted else bounded_optional_text(row.quote_preview, 240),
    }


def capture_to_json(row: MemoryCaptureRow, *, redacted: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "source_agent": row.source_agent,
        "source_kind": row.source_kind,
        "event_type": row.event_type,
        "actor_role": row.actor_role,
        "text_redacted": None if redacted else row.text_redacted,
        "evidence_refs": list(row.evidence_refs_json or []),
        "payload_hash": row.payload_hash,
        "idempotency_key": row.idempotency_key,
        "status": row.status,
        "consolidation_status": row.consolidation_status,
        "trust_level": row.trust_level,
        "source_authority": row.source_authority,
        "sensitivity": row.sensitivity,
        "data_classification": row.data_classification,
        "occurred_at": row.occurred_at.isoformat(),
        "received_at": row.received_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "metadata_json": safe_metadata(row.metadata_json),
        "source_event_id": row.source_event_id,
        "source_actor_external_ref": row.source_actor_external_ref,
        "client_instance_id": row.client_instance_id,
        "agent_session_external_ref": row.agent_session_external_ref,
        "turn_external_ref": row.turn_external_ref,
        "parent_capture_id": row.parent_capture_id,
        "sequence_index": row.sequence_index,
        "trace_id": row.trace_id,
        "schema_version": row.schema_version,
        "parser_version": row.parser_version,
        "redaction_version": row.redaction_version,
        "admission_version": row.admission_version,
        "normalization_version": row.normalization_version,
        "policy_version": row.policy_version,
        "extractor_version": row.extractor_version,
        "extractor_prompt_version": row.extractor_prompt_version,
        "resolver_version": row.resolver_version,
        "last_error_code": row.last_error_code,
        "last_error_message": safe_bounded_optional_text(row.last_error_message, 400),
    }


def anchor_to_json(row: MemoryAnchorRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "normalized_key": row.normalized_key,
        "label": row.label,
        "aliases": list(row.aliases_json or []),
        "description": row.description,
        "status": row.status,
        "confidence": row.confidence,
        "evidence_refs": _anchor_evidence_refs_to_json(row.evidence_refs_json or []),
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "metadata_json": safe_metadata(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def context_link_to_json(row: MemoryContextLinkRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "relation_type": row.relation_type,
        "confidence": row.confidence,
        "reason": row.reason,
        "status": row.status,
        "metadata_json": safe_metadata(row.metadata_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def fact_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryFactRow:
    return MemoryFactRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=bounded_optional_text(item.get("thread_id"), 80),
        kind=str(item.get("kind", "note")),
        text=str(item.get("text") or "[redacted]"),
        status=str(item.get("status", "active")),
        confidence=str(item.get("confidence", "medium")),
        trust_level=str(item.get("trust_level", "medium")),
        classification=str(item.get("classification", "internal")),
        category=bounded_optional_text(item.get("category"), 80),
        tags_json=_bounded_tags(item.get("tags")),
        ttl_policy=bounded_optional_text(item.get("ttl_policy"), 80),
        expires_at=_parse_optional_dt(item.get("expires_at")),
        version=int(item.get("version", 1)),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def document_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=bounded_optional_text(item.get("thread_id"), 80),
        title=str(item.get("title") or "Imported document"),
        source_type=str(item.get("source_type", "import")),
        source_external_id=str(item.get("source_external_id", item["id"])),
        content_hash=str(item.get("content_hash", item["id"])),
        classification=str(item.get("classification", "unknown")),
        status=str(item.get("status", "active")),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def episode_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryEpisodeRow:
    return MemoryEpisodeRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=str(item["thread_id"]),
        source_type=str(item.get("source_type", "import")),
        source_external_id=str(item.get("source_external_id", item["id"])),
        text=str(item.get("text") or "[redacted]"),
        speaker=str(item.get("speaker", "unknown")),
        trust_level=str(item.get("trust_level", "medium")),
        status=str(item.get("status", "active")),
        occurred_at=_parse_dt(item.get("occurred_at"), now),
        created_at=_parse_dt(item.get("created_at"), now),
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
    )


def chunk_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryChunkRow:
    text = str(item.get("text") or "[redacted]")
    return MemoryChunkRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=item.get("thread_id"),
        document_id=item.get("document_id"),
        episode_id=item.get("episode_id"),
        source_type=str(item.get("source_type", "import")),
        source_external_id=str(item.get("source_external_id", item["id"])),
        source_hash=str(item.get("source_hash", item["id"])),
        kind=str(item.get("kind", "document_section")),
        text=text,
        normalized_text=str(item.get("normalized_text") or text),
        status=str(item.get("status", "active")),
        sequence=int(item.get("sequence", 0)),
        char_start=int(item.get("char_start", 0)),
        char_end=int(item.get("char_end", len(text))),
        token_estimate=int(item.get("token_estimate", max(1, len(text) // 4))),
        classification=str(item.get("classification", "unknown")),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
        metadata_json=safe_metadata(item.get("metadata_json") or {}),
    )


def source_ref_from_json(item: dict[str, Any]) -> MemorySourceRefRow:
    return MemorySourceRefRow(
        fact_id=str(item["fact_id"]),
        fact_version=int(item.get("fact_version", 1)),
        source_type=str(item.get("source_type", "import")),
        source_id=str(item.get("source_id", "import")),
        chunk_id=item.get("chunk_id"),
        char_start=item.get("char_start"),
        char_end=item.get("char_end"),
        quote_preview=bounded_optional_text(item.get("quote_preview"), 240),
    )


def capture_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryCaptureRow:
    return MemoryCaptureRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=bounded_optional_text(item.get("thread_id"), 80),
        source_agent=str(item.get("source_agent", "import")),
        source_kind=str(item.get("source_kind", "manual")),
        event_type=str(item.get("event_type", "ImportedCapture")),
        actor_role=str(item.get("actor_role", "unknown")),
        text_redacted=str(item.get("text_redacted") or "[redacted]"),
        evidence_refs_json=list(item.get("evidence_refs") or []),
        payload_hash=str(item.get("payload_hash", item["id"])),
        idempotency_key=str(item.get("idempotency_key", item["id"])),
        status=str(item.get("status", "accepted")),
        consolidation_status=str(item.get("consolidation_status", "pending")),
        trust_level=str(item.get("trust_level", "medium")),
        source_authority=str(item.get("source_authority", "unknown")),
        sensitivity=str(item.get("sensitivity", "medium")),
        data_classification=str(item.get("data_classification", "internal")),
        occurred_at=_parse_dt(item.get("occurred_at"), now),
        received_at=_parse_dt(item.get("received_at"), now),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
        source_event_id=bounded_optional_text(item.get("source_event_id"), 240),
        source_actor_external_ref=bounded_optional_text(
            item.get("source_actor_external_ref"),
            240,
        ),
        client_instance_id=bounded_optional_text(item.get("client_instance_id"), 160),
        agent_session_external_ref=bounded_optional_text(
            item.get("agent_session_external_ref"),
            240,
        ),
        turn_external_ref=bounded_optional_text(item.get("turn_external_ref"), 240),
        parent_capture_id=bounded_optional_text(item.get("parent_capture_id"), 80),
        sequence_index=(
            int(item["sequence_index"]) if item.get("sequence_index") is not None else None
        ),
        trace_id=bounded_optional_text(item.get("trace_id"), 120),
        schema_version=int(item.get("schema_version", 1)),
        parser_version=str(item.get("parser_version", "capture-parser-v1")),
        redaction_version=str(item.get("redaction_version", "redaction-v1")),
        admission_version=str(item.get("admission_version", "capture-admission-v1")),
        normalization_version=str(item.get("normalization_version", "capture-normalization-v1")),
        policy_version=str(item.get("policy_version", "capture-policy-v1")),
        extractor_version=bounded_optional_text(item.get("extractor_version"), 80),
        extractor_prompt_version=bounded_optional_text(
            item.get("extractor_prompt_version"),
            80,
        ),
        resolver_version=bounded_optional_text(item.get("resolver_version"), 80),
        last_error_code=bounded_optional_text(item.get("last_error_code"), 120),
        last_error_message=safe_bounded_optional_text(item.get("last_error_message"), 400),
    )


def anchor_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryAnchorRow:
    return MemoryAnchorRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        kind=str(item.get("kind", "concept")),
        normalized_key=str(item.get("normalized_key") or item["id"]),
        label=str(item.get("label") or item.get("normalized_key") or item["id"]),
        aliases_json=_bounded_string_list(item.get("aliases"), limit=20, item_limit=120),
        description=bounded_optional_text(item.get("description"), 500),
        status=str(item.get("status", "active")),
        confidence=str(item.get("confidence", "medium")),
        evidence_refs_json=_anchor_evidence_refs_from_json(item.get("evidence_refs")),
        observed_at=_parse_optional_dt(item.get("observed_at")),
        valid_from=_parse_optional_dt(item.get("valid_from")),
        valid_to=_parse_optional_dt(item.get("valid_to")),
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def context_link_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryContextLinkRow:
    return MemoryContextLinkRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        source_type=str(item.get("source_type", "unknown")),
        source_id=str(item.get("source_id", item["id"])),
        target_type=str(item.get("target_type", "unknown")),
        target_id=str(item.get("target_id", item["id"])),
        relation_type=str(item.get("relation_type", "related_to")),
        confidence=str(item.get("confidence", "medium")),
        reason=str(item.get("reason", "Imported context link")),
        status=str(item.get("status", "active")),
        metadata_json=safe_metadata(item.get("metadata_json") or item.get("metadata") or {}),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def _anchor_evidence_refs_to_json(items: list[dict[str, object]]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "source_type": bounded_optional_text(item.get("source_type"), 80) or "unknown",
                "source_id": bounded_optional_text(item.get("source_id"), 160) or "unknown",
                "chunk_id": bounded_optional_text(item.get("chunk_id"), 160),
                "char_start": item.get("char_start"),
                "char_end": item.get("char_end"),
                "quote_preview": safe_bounded_optional_text(item.get("quote_preview"), 240),
            }
        )
    return refs


def _anchor_evidence_refs_from_json(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, object]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "source_type": bounded_optional_text(item.get("source_type"), 80) or "unknown",
                "source_id": bounded_optional_text(item.get("source_id"), 160) or "unknown",
                "chunk_id": bounded_optional_text(item.get("chunk_id"), 160),
                "char_start": item.get("char_start"),
                "char_end": item.get("char_end"),
                "quote_preview": safe_bounded_optional_text(item.get("quote_preview"), 240),
            }
        )
    return refs


def bounded_optional_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


def safe_bounded_optional_text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    return safe_metadata_text(str(value), limit=limit)


def _parse_dt(value: object, fallback: datetime) -> datetime:
    if not value:
        return fallback
    return datetime.fromisoformat(str(value))


def _parse_optional_dt(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _bounded_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        tag = str(item).strip().lower()[:48]
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 10:
            break
    return tags


def _bounded_string_list(value: object, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()[:item_limit]
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items
