"""Asset and context-link domain entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NewType

from memo_stack_core.domain.entities import (
    DataClassification,
    LifecycleStatus,
    MemoryScopeId,
    SpaceId,
    ThreadId,
)
from memo_stack_core.domain.errors import MemoryValidationError

MemoryAssetId = NewType("MemoryAssetId", str)
MemoryContextLinkId = NewType("MemoryContextLinkId", str)
MemoryContextLinkSuggestionId = NewType("MemoryContextLinkSuggestionId", str)

MAX_ASSET_FILENAME_CHARS = 240
MAX_ASSET_CONTENT_TYPE_CHARS = 120
MAX_ASSET_STORAGE_KEY_CHARS = 500
MAX_ASSET_METADATA_KEYS = 80
MAX_CONTEXT_LINK_METADATA_KEYS = 80
MAX_CONTEXT_LINK_REVIEW_REASON_CHARS = 320
MAX_CONTEXT_LINK_AUDIT_EVENTS = 20
MAX_CONTEXT_LINK_REVIEW_EVENTS = 20
_AUDIT_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "authorization:",
    "bearer ",
    "password",
    "private_key",
    "secret",
    "sk-",
    "token",
)


class AssetStatus(StrEnum):
    STORED = "stored"
    FAILED = "failed"
    DELETED = "deleted"


class ContextLinkSuggestionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class MemoryAsset:
    id: MemoryAssetId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    filename: str
    content_type: str
    byte_size: int
    sha256_hex: str
    storage_backend: str
    storage_key: str
    status: AssetStatus
    classification: str
    metadata: Mapping[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        asset_id: MemoryAssetId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        filename: str,
        content_type: str,
        byte_size: int,
        sha256_hex: str,
        storage_backend: str,
        storage_key: str,
        now: datetime,
        thread_id: ThreadId | None = None,
        classification: str = DataClassification.UNKNOWN.value,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryAsset:
        safe_filename = filename.strip()[:MAX_ASSET_FILENAME_CHARS]
        if not safe_filename:
            raise MemoryValidationError("Asset filename is required")
        safe_content_type = content_type.strip()[:MAX_ASSET_CONTENT_TYPE_CHARS]
        if not safe_content_type:
            safe_content_type = "application/octet-stream"
        if byte_size <= 0:
            raise MemoryValidationError("Asset byte_size must be positive")
        if not sha256_hex.strip():
            raise MemoryValidationError("Asset sha256_hex is required")
        if not storage_backend.strip():
            raise MemoryValidationError("Asset storage_backend is required")
        if not storage_key.strip():
            raise MemoryValidationError("Asset storage_key is required")
        if len(storage_key) > MAX_ASSET_STORAGE_KEY_CHARS:
            raise MemoryValidationError("Asset storage_key exceeds max length")
        safe_metadata = _safe_metadata(metadata, max_keys=MAX_ASSET_METADATA_KEYS)
        return cls(
            id=asset_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            filename=safe_filename,
            content_type=safe_content_type,
            byte_size=byte_size,
            sha256_hex=sha256_hex.strip().lower(),
            storage_backend=storage_backend.strip(),
            storage_key=storage_key.strip(),
            status=AssetStatus.STORED,
            classification=_classification_value(classification),
            metadata=safe_metadata,
            created_at=now,
            updated_at=now,
        )

    def delete(self, *, now: datetime) -> MemoryAsset:
        if self.status == AssetStatus.DELETED:
            return self
        return replace(self, status=AssetStatus.DELETED, updated_at=now)


@dataclass(frozen=True)
class MemoryContextLink:
    id: MemoryContextLinkId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    confidence: str
    reason: str
    status: LifecycleStatus
    metadata: Mapping[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        link_id: MemoryContextLinkId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
        confidence: str,
        reason: str,
        now: datetime,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryContextLink:
        safe_source_type = source_type.strip()
        safe_source_id = source_id.strip()
        safe_target_type = target_type.strip()
        safe_target_id = target_id.strip()
        safe_relation_type = relation_type.strip()
        if not safe_source_type or not safe_source_id:
            raise MemoryValidationError("Context link source is required")
        if not safe_target_type or not safe_target_id:
            raise MemoryValidationError("Context link target is required")
        if safe_source_type == safe_target_type and safe_source_id == safe_target_id:
            raise MemoryValidationError("Context link requires two distinct objects")
        if not safe_relation_type:
            raise MemoryValidationError("Context link relation_type is required")
        if not reason.strip():
            raise MemoryValidationError("Context link reason is required")
        safe_confidence = confidence.strip() or "medium"
        if safe_confidence not in {"low", "medium", "high"}:
            raise MemoryValidationError("Context link confidence is invalid")
        return cls(
            id=link_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            source_type=safe_source_type,
            source_id=safe_source_id,
            target_type=safe_target_type,
            target_id=safe_target_id,
            relation_type=safe_relation_type,
            confidence=safe_confidence,
            reason=reason.strip()[:320],
            status=LifecycleStatus.ACTIVE,
            metadata=_safe_metadata(metadata, max_keys=MAX_CONTEXT_LINK_METADATA_KEYS),
            created_at=now,
            updated_at=now,
        )

    def delete(self, *, now: datetime) -> MemoryContextLink:
        if self.status == LifecycleStatus.DELETED:
            return self
        return replace(self, status=LifecycleStatus.DELETED, updated_at=now)

    def update_details(
        self,
        *,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        confidence: str | None = None,
        reason: str | None = None,
        metadata: Mapping[str, object] | None = None,
        now: datetime,
    ) -> MemoryContextLink:
        if self.status != LifecycleStatus.ACTIVE:
            raise MemoryValidationError("Only active context links can be updated")
        safe_source_type = self.source_type if source_type is None else source_type.strip()
        safe_source_id = self.source_id if source_id is None else source_id.strip()
        safe_target_type = self.target_type if target_type is None else target_type.strip()
        safe_target_id = self.target_id if target_id is None else target_id.strip()
        safe_relation_type = self.relation_type if relation_type is None else relation_type.strip()
        safe_confidence = self.confidence if confidence is None else confidence.strip()
        safe_reason = self.reason if reason is None else reason.strip()
        if not safe_source_type or not safe_source_id:
            raise MemoryValidationError("Context link source is required")
        if not safe_target_type or not safe_target_id:
            raise MemoryValidationError("Context link target is required")
        if safe_source_type == safe_target_type and safe_source_id == safe_target_id:
            raise MemoryValidationError("Context link requires two distinct objects")
        if not safe_relation_type:
            raise MemoryValidationError("Context link relation_type is required")
        if safe_confidence not in {"low", "medium", "high"}:
            raise MemoryValidationError("Context link confidence is invalid")
        if not safe_reason:
            raise MemoryValidationError("Context link reason is required")
        changed_fields = _context_link_changed_fields(
            before={
                "source_type": self.source_type,
                "source_id": self.source_id,
                "target_type": self.target_type,
                "target_id": self.target_id,
                "relation_type": self.relation_type,
                "confidence": self.confidence,
                "reason": self.reason,
            },
            after={
                "source_type": safe_source_type,
                "source_id": safe_source_id,
                "target_type": safe_target_type,
                "target_id": safe_target_id,
                "relation_type": safe_relation_type,
                "confidence": safe_confidence,
                "reason": safe_reason[:320],
            },
        )
        safe_metadata = _safe_metadata(metadata, max_keys=MAX_CONTEXT_LINK_METADATA_KEYS)
        edit_source = str(safe_metadata.get("last_edit_source") or "manual")[:80]
        next_metadata = _append_context_link_audit(
            {**dict(self.metadata), **safe_metadata},
            event={
                "edited_at": now.isoformat(),
                "source": edit_source,
                "changed_fields": changed_fields,
                "previous": {
                    "source_type": self.source_type,
                    "source_id": self.source_id,
                    "target_type": self.target_type,
                    "target_id": self.target_id,
                    "relation_type": self.relation_type,
                    "confidence": self.confidence,
                    "reason": self.reason,
                },
                "next": {
                    "source_type": safe_source_type,
                    "source_id": safe_source_id,
                    "target_type": safe_target_type,
                    "target_id": safe_target_id,
                    "relation_type": safe_relation_type,
                    "confidence": safe_confidence,
                    "reason": safe_reason[:320],
                },
            },
        )
        return replace(
            self,
            source_type=safe_source_type,
            source_id=safe_source_id,
            target_type=safe_target_type,
            target_id=safe_target_id,
            relation_type=safe_relation_type,
            confidence=safe_confidence,
            reason=safe_reason[:320],
            metadata=next_metadata,
            updated_at=now,
        )


@dataclass(frozen=True)
class MemoryContextLinkSuggestion:
    id: MemoryContextLinkSuggestionId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    confidence: str
    reason: str
    score: float
    status: ContextLinkSuggestionStatus
    metadata: Mapping[str, object]
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    review_reason: str | None

    @classmethod
    def create(
        cls,
        *,
        suggestion_id: MemoryContextLinkSuggestionId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relation_type: str,
        confidence: str,
        reason: str,
        score: float,
        now: datetime,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryContextLinkSuggestion:
        safe_source_type = source_type.strip()
        safe_source_id = source_id.strip()
        safe_target_type = target_type.strip()
        safe_target_id = target_id.strip()
        safe_relation_type = relation_type.strip()
        if not safe_source_type or not safe_source_id:
            raise MemoryValidationError("Context link suggestion source is required")
        if not safe_target_type or not safe_target_id:
            raise MemoryValidationError("Context link suggestion target is required")
        if safe_source_type == safe_target_type and safe_source_id == safe_target_id:
            raise MemoryValidationError("Context link suggestion requires two distinct objects")
        if not safe_relation_type:
            raise MemoryValidationError("Context link suggestion relation_type is required")
        if not reason.strip():
            raise MemoryValidationError("Context link suggestion reason is required")
        safe_confidence = confidence.strip() or "medium"
        if safe_confidence not in {"low", "medium", "high"}:
            raise MemoryValidationError("Context link suggestion confidence is invalid")
        return cls(
            id=suggestion_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            source_type=safe_source_type,
            source_id=safe_source_id,
            target_type=safe_target_type,
            target_id=safe_target_id,
            relation_type=safe_relation_type,
            confidence=safe_confidence,
            reason=reason.strip()[:320],
            score=max(0.0, min(float(score), 100.0)),
            status=ContextLinkSuggestionStatus.PENDING,
            metadata=_safe_metadata(metadata, max_keys=MAX_CONTEXT_LINK_METADATA_KEYS),
            created_at=now,
            updated_at=now,
            reviewed_at=None,
            review_reason=None,
        )

    def approve(self, *, now: datetime, reason: str | None = None) -> MemoryContextLinkSuggestion:
        if self.status == ContextLinkSuggestionStatus.APPROVED:
            return self
        if self.status != ContextLinkSuggestionStatus.PENDING:
            raise MemoryValidationError("Only pending context link suggestions can be approved")
        review_reason = _optional_text(
            reason,
            max_chars=MAX_CONTEXT_LINK_REVIEW_REASON_CHARS,
        )
        next_metadata = _append_context_link_review_audit(
            self.metadata,
            event=_context_link_review_event(
                suggestion=self,
                action="approve",
                previous_status=self.status.value,
                new_status=ContextLinkSuggestionStatus.APPROVED.value,
                reviewed_at=now,
                reason=review_reason,
            ),
        )
        return replace(
            self,
            status=ContextLinkSuggestionStatus.APPROVED,
            metadata=next_metadata,
            updated_at=now,
            reviewed_at=now,
            review_reason=review_reason or self.review_reason,
        )

    def reject(self, *, now: datetime, reason: str | None = None) -> MemoryContextLinkSuggestion:
        if self.status == ContextLinkSuggestionStatus.REJECTED:
            return self
        if self.status != ContextLinkSuggestionStatus.PENDING:
            raise MemoryValidationError("Only pending context link suggestions can be rejected")
        review_reason = _optional_text(
            reason,
            max_chars=MAX_CONTEXT_LINK_REVIEW_REASON_CHARS,
        )
        next_metadata = _append_context_link_review_audit(
            self.metadata,
            event=_context_link_review_event(
                suggestion=self,
                action="reject",
                previous_status=self.status.value,
                new_status=ContextLinkSuggestionStatus.REJECTED.value,
                reviewed_at=now,
                reason=review_reason,
            ),
        )
        return replace(
            self,
            status=ContextLinkSuggestionStatus.REJECTED,
            metadata=next_metadata,
            updated_at=now,
            reviewed_at=now,
            review_reason=review_reason,
        )

    def expire(self, *, now: datetime, reason: str | None = None) -> MemoryContextLinkSuggestion:
        if self.status == ContextLinkSuggestionStatus.EXPIRED:
            return self
        if self.status != ContextLinkSuggestionStatus.PENDING:
            raise MemoryValidationError("Only pending context link suggestions can be expired")
        review_reason = _optional_text(
            reason,
            max_chars=MAX_CONTEXT_LINK_REVIEW_REASON_CHARS,
        )
        next_metadata = _append_context_link_review_audit(
            self.metadata,
            event=_context_link_review_event(
                suggestion=self,
                action="expire",
                previous_status=self.status.value,
                new_status=ContextLinkSuggestionStatus.EXPIRED.value,
                reviewed_at=now,
                reason=review_reason,
            ),
        )
        return replace(
            self,
            status=ContextLinkSuggestionStatus.EXPIRED,
            metadata=next_metadata,
            updated_at=now,
            reviewed_at=now,
            review_reason=review_reason,
        )


def _classification_value(value: str) -> str:
    try:
        return DataClassification(value).value
    except ValueError as exc:
        raise MemoryValidationError("Unknown data classification") from exc


def _safe_metadata(
    metadata: Mapping[str, object] | None,
    *,
    max_keys: int,
) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in dict(metadata or {}).items():
        if len(safe) >= max_keys:
            break
        key_text = str(key).strip()[:80]
        if not key_text:
            continue
        if isinstance(value, str):
            safe[key_text] = value[:500]
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key_text] = value
        elif isinstance(value, (list, tuple)):
            items: list[object] = []
            for item in value[:20]:
                if isinstance(item, str):
                    items.append(item[:120])
                elif isinstance(item, (int, float, bool)) or item is None:
                    items.append(item)
            if items:
                safe[key_text] = items
    return safe


def _context_link_changed_fields(
    *,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> list[str]:
    return [key for key, value in after.items() if before.get(key) != value]


def _append_context_link_audit(
    metadata: Mapping[str, object],
    *,
    event: Mapping[str, object],
) -> dict[str, object]:
    next_metadata = dict(metadata)
    existing = metadata.get("edit_events")
    events = (
        [item for item in existing if isinstance(item, Mapping)]
        if isinstance(existing, list)
        else []
    )
    events.append(dict(event))
    next_metadata["edit_events"] = events[-MAX_CONTEXT_LINK_AUDIT_EVENTS:]
    return next_metadata


def _append_context_link_review_audit(
    metadata: Mapping[str, object],
    *,
    event: Mapping[str, object],
) -> dict[str, object]:
    next_metadata = dict(metadata)
    existing = metadata.get("review_events")
    events = (
        [item for item in existing if isinstance(item, Mapping)]
        if isinstance(existing, list)
        else []
    )
    events.append(dict(event))
    next_metadata["review_events"] = events[-MAX_CONTEXT_LINK_REVIEW_EVENTS:]
    return next_metadata


def _context_link_review_event(
    *,
    suggestion: MemoryContextLinkSuggestion,
    action: str,
    previous_status: str,
    new_status: str,
    reviewed_at: datetime,
    reason: str | None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "context_link_suggestion_reviewed",
        "suggestion_id": str(suggestion.id),
        "space_id": str(suggestion.space_id),
        "memory_scope_id": str(suggestion.memory_scope_id),
        "source_type": suggestion.source_type,
        "source_id": suggestion.source_id,
        "target_type": suggestion.target_type,
        "target_id": suggestion.target_id,
        "relation_type": suggestion.relation_type,
        "action": action,
        "previous_status": previous_status,
        "new_status": new_status,
        "reviewed_at": reviewed_at.isoformat(),
    }
    policy_version = suggestion.metadata.get("suggestion_policy_version")
    if isinstance(policy_version, str) and policy_version.strip():
        event["policy_version"] = policy_version[:120]
    if reason:
        event["reason"] = _safe_audit_reason(reason)
    return event


def _safe_audit_reason(reason: str) -> str:
    normalized = reason.strip()[:MAX_CONTEXT_LINK_REVIEW_REASON_CHARS]
    lowered = normalized.lower()
    if any(marker in lowered for marker in _AUDIT_SECRET_MARKERS):
        return "[redacted]"
    return normalized


def _optional_text(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:max_chars] or None
