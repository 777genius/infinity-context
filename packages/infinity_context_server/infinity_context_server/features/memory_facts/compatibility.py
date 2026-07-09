"""Legacy memory compatibility mapping for the memory_facts seam."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application import (
    ForgetFactCommand,
    LinkFactsCommand,
    RememberFactCommand,
    UnlinkFactRelationCommand,
    UpdateFactCommand,
)
from infinity_context_core.domain.entities import (
    FactStatus,
    MemoryChunkKind,
    MemoryKind,
    SourceRef,
    SpeakerRole,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryValidationError


def remember_fact_command_from_v1_request(
    request: object,
    *,
    resolved_scope: object,
    idempotency_key: str | None = None,
) -> RememberFactCommand:
    """Map the stable /v1 write request into the legacy fact use case command."""

    return RememberFactCommand(
        space_id=_required_value(resolved_scope, "space_id"),
        memory_scope_id=_required_value(resolved_scope, "memory_scope_id"),
        thread_id=_value(resolved_scope, "thread_id", None),
        text=_required_value(request, "text"),
        kind=memory_kind_from_v1_request(_value(request, "kind", "note")),
        source_refs=tuple(
            source_ref_from_v1_request(source_ref)
            for source_ref in _required_sequence(request, "source_refs")
        ),
        classification=_value(request, "classification", "internal"),
        category=_value(request, "category", None),
        tags=tuple(_value(request, "tags", ())),
        ttl_policy=_value(request, "ttl_policy", None),
        idempotency_key=idempotency_key,
    )


def update_fact_command_from_v1_request(
    fact_id: str,
    request: object,
) -> UpdateFactCommand:
    """Map the stable /v1 update request into the legacy fact use case command."""

    return UpdateFactCommand(
        fact_id=fact_id,
        expected_version=int(_required_value(request, "expected_version")),
        text=_required_value(request, "text"),
        reason=_required_value(request, "reason"),
        source_refs=tuple(
            source_ref_from_v1_request(source_ref)
            for source_ref in _required_sequence(request, "source_refs")
        ),
    )


def forget_fact_command_from_v1_path(fact_id: str) -> ForgetFactCommand:
    """Map the stable /v1 delete path into the legacy fact use case command."""

    return ForgetFactCommand(fact_id=fact_id)


def link_fact_relation_command_from_v1_request(
    fact_id: str,
    request: object,
) -> LinkFactsCommand:
    """Map the stable /v1 relation write request into the legacy relation command."""

    return LinkFactsCommand(
        source_fact_id=fact_id,
        target_fact_id=_required_value(request, "target_fact_id"),
        relation_type=_value(request, "relation_type", "related_to"),
        reason=_required_value(request, "reason"),
        observed_at=_value(request, "observed_at", None),
        valid_from=_value(request, "valid_from", None),
        valid_to=_value(request, "valid_to", None),
    )


def unlink_fact_relation_command_from_v1_path(relation_id: str) -> UnlinkFactRelationCommand:
    """Map the stable /v1 relation delete path into the legacy relation command."""

    return UnlinkFactRelationCommand(relation_id=relation_id)


def source_ref_from_v1_request(source_ref: object) -> SourceRef:
    """Map a stable /v1 source ref request into the legacy domain value object."""

    return SourceRef(
        source_type=_required_value(source_ref, "source_type"),
        source_id=_required_value(source_ref, "source_id"),
        chunk_id=_value(source_ref, "chunk_id", None),
        char_start=_value(source_ref, "char_start", None),
        char_end=_value(source_ref, "char_end", None),
        quote_preview=_value(source_ref, "quote_preview", None),
        page_number=_value(source_ref, "page_number", None),
        time_start_ms=_value(source_ref, "time_start_ms", None),
        time_end_ms=_value(source_ref, "time_end_ms", None),
        bbox=_value(source_ref, "bbox", None),
    )


def memory_kind_from_v1_request(value: object) -> MemoryKind:
    """Map the legacy kind string while preserving the /v1 validation error."""

    try:
        return MemoryKind(value)
    except ValueError as exc:
        raise MemoryValidationError(f"Unknown memory kind: {value}") from exc


def legacy_interview_source(value: str) -> str:
    return value.strip() or "unknown"


def legacy_interview_kind(value: str | None) -> MemoryChunkKind | None:
    if not value:
        return None
    try:
        return MemoryChunkKind(value)
    except ValueError:
        return MemoryChunkKind.RAW_TRANSCRIPT_CHUNK


def legacy_interview_speaker(speaker: str | None, source: str) -> SpeakerRole:
    if speaker:
        try:
            return SpeakerRole(speaker)
        except ValueError:
            pass
    if source == "ai_response":
        return SpeakerRole.ASSISTANT
    if source in {"system_audio", "signal"}:
        return SpeakerRole.INTERVIEWER
    if source in {"microphone", "manual_prompt"}:
        return SpeakerRole.USER
    return SpeakerRole.UNKNOWN


def legacy_interview_trust(source: str) -> TrustLevel:
    if source == "ai_response":
        return TrustLevel.LOW
    if source in {"focus_copy", "manual_prompt"}:
        return TrustLevel.HIGH
    if source in {"browser_selection", "microphone", "signal", "system_audio"}:
        return TrustLevel.MEDIUM
    return TrustLevel.LOW


def validate_fact_status_filter(status_filter: str | None) -> None:
    if status_filter is None:
        return
    try:
        FactStatus(status_filter)
    except ValueError as exc:
        raise ValueError("Unknown fact status") from exc


def _required_sequence(source: object, name: str) -> tuple[object, ...]:
    value = _required_value(source, name)
    if isinstance(value, list | tuple):
        return tuple(value)
    raise TypeError(f"{name} must be a sequence")


def _required_value(source: object, name: str) -> Any:
    value = _value(source, name, None)
    if value is None:
        raise KeyError(name)
    return value


def _value(source: object, name: str, default: object) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


__all__ = (
    "forget_fact_command_from_v1_path",
    "legacy_interview_kind",
    "legacy_interview_source",
    "legacy_interview_speaker",
    "legacy_interview_trust",
    "link_fact_relation_command_from_v1_request",
    "memory_kind_from_v1_request",
    "remember_fact_command_from_v1_request",
    "source_ref_from_v1_request",
    "unlink_fact_relation_command_from_v1_path",
    "update_fact_command_from_v1_request",
    "validate_fact_status_filter",
)
