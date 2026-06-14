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
        return replace(
            self,
            status=ContextLinkSuggestionStatus.APPROVED,
            updated_at=now,
            reviewed_at=now,
            review_reason=review_reason or self.review_reason,
        )

    def reject(self, *, now: datetime, reason: str | None = None) -> MemoryContextLinkSuggestion:
        if self.status == ContextLinkSuggestionStatus.REJECTED:
            return self
        if self.status != ContextLinkSuggestionStatus.PENDING:
            raise MemoryValidationError("Only pending context link suggestions can be rejected")
        return replace(
            self,
            status=ContextLinkSuggestionStatus.REJECTED,
            updated_at=now,
            reviewed_at=now,
            review_reason=_optional_text(
                reason,
                max_chars=MAX_CONTEXT_LINK_REVIEW_REASON_CHARS,
            ),
        )

    def expire(self, *, now: datetime, reason: str | None = None) -> MemoryContextLinkSuggestion:
        if self.status == ContextLinkSuggestionStatus.EXPIRED:
            return self
        if self.status != ContextLinkSuggestionStatus.PENDING:
            raise MemoryValidationError("Only pending context link suggestions can be expired")
        return replace(
            self,
            status=ContextLinkSuggestionStatus.EXPIRED,
            updated_at=now,
            reviewed_at=now,
            review_reason=_optional_text(
                reason,
                max_chars=MAX_CONTEXT_LINK_REVIEW_REASON_CHARS,
            ),
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


def _optional_text(value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:max_chars] or None
