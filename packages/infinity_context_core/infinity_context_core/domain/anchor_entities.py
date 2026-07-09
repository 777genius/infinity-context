"""Memory anchor aggregate entity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from infinity_context_core.domain.entity_policies import (
    _append_anchor_audit,
    _latest_datetime,
    _max_confidence,
    _merge_temporal_window,
    _safe_audit_text,
    _unique_strings,
    _validate_temporal_range,
)
from infinity_context_core.domain.entity_types import (
    Confidence,
    LifecycleStatus,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.domain.source_refs import SourceRef, _unique_source_refs


@dataclass(frozen=True)
class MemoryAnchor:
    id: MemoryAnchorId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    kind: MemoryAnchorKind
    normalized_key: str
    label: str
    aliases: tuple[str, ...]
    description: str | None
    status: LifecycleStatus
    confidence: Confidence
    evidence_refs: tuple[SourceRef, ...]
    observed_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None
    metadata: Mapping[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        anchor_id: MemoryAnchorId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        kind: MemoryAnchorKind,
        normalized_key: str,
        label: str,
        now: datetime,
        aliases: tuple[str, ...] = (),
        description: str | None = None,
        confidence: Confidence = Confidence.MEDIUM,
        evidence_refs: tuple[SourceRef, ...] = (),
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MemoryAnchor:
        safe_key = normalized_key.strip().lower()
        safe_label = label.strip()
        if not safe_key:
            raise MemoryValidationError("MemoryAnchor normalized_key is required")
        if not safe_label:
            raise MemoryValidationError("MemoryAnchor label is required")
        _validate_temporal_range(valid_from=valid_from, valid_to=valid_to)
        return cls(
            id=anchor_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            kind=kind,
            normalized_key=safe_key[:160],
            label=safe_label[:240],
            aliases=_unique_aliases((safe_label, *aliases)),
            description=description.strip()[:500] if description and description.strip() else None,
            status=LifecycleStatus.ACTIVE,
            confidence=confidence,
            evidence_refs=_unique_source_refs(evidence_refs),
            observed_at=observed_at or now,
            valid_from=valid_from,
            valid_to=valid_to,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )

    def merge_observation(
        self,
        *,
        label: str | None = None,
        aliases: tuple[str, ...] = (),
        confidence: Confidence | None = None,
        evidence_refs: tuple[SourceRef, ...] = (),
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
        now: datetime,
    ) -> MemoryAnchor:
        next_label = self.label if label is None or not label.strip() else label.strip()[:240]
        next_valid_from, next_valid_to = _merge_temporal_window(
            current_from=self.valid_from,
            current_to=self.valid_to,
            observed_from=valid_from,
            observed_to=valid_to,
        )
        _validate_temporal_range(valid_from=next_valid_from, valid_to=next_valid_to)
        return replace(
            self,
            label=next_label,
            aliases=_unique_aliases((*self.aliases, next_label, *aliases)),
            confidence=_max_confidence(self.confidence, confidence),
            evidence_refs=_unique_source_refs((*self.evidence_refs, *evidence_refs)),
            observed_at=_latest_datetime(self.observed_at, observed_at),
            valid_from=next_valid_from,
            valid_to=next_valid_to,
            metadata={**dict(self.metadata), **dict(metadata or {})},
            updated_at=now,
        )

    def update_details(
        self,
        *,
        normalized_key: str | None = None,
        label: str | None = None,
        aliases: tuple[str, ...] = (),
        description: str | None = None,
        confidence: Confidence | None = None,
        evidence_refs: tuple[SourceRef, ...] = (),
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
        now: datetime,
    ) -> MemoryAnchor:
        if self.status != LifecycleStatus.ACTIVE:
            raise MemoryValidationError("Only active memory anchors can be updated")
        next_label = self.label if label is None or not label.strip() else label.strip()[:240]
        next_key = self.normalized_key if normalized_key is None else normalized_key.strip().lower()
        if not next_key:
            raise MemoryValidationError("MemoryAnchor normalized_key is required")
        next_valid_from = self.valid_from if valid_from is None else valid_from
        next_valid_to = self.valid_to if valid_to is None else valid_to
        _validate_temporal_range(valid_from=next_valid_from, valid_to=next_valid_to)
        return replace(
            self,
            normalized_key=next_key[:160],
            label=next_label,
            aliases=_unique_aliases((next_label, *self.aliases, *aliases)),
            description=(
                self.description
                if description is None
                else description.strip()[:500] if description.strip() else None
            ),
            confidence=_max_confidence(self.confidence, confidence),
            evidence_refs=_unique_source_refs((*self.evidence_refs, *evidence_refs)),
            observed_at=_latest_datetime(self.observed_at, observed_at),
            valid_from=next_valid_from,
            valid_to=next_valid_to,
            metadata={**dict(self.metadata), **dict(metadata or {})},
            updated_at=now,
        )

    def delete(self, *, reason: str, now: datetime) -> MemoryAnchor:
        if self.status == LifecycleStatus.DELETED:
            return self
        return replace(
            self,
            status=LifecycleStatus.DELETED,
            metadata={
                **dict(self.metadata),
                "resolver_version": "anchor-lifecycle-v2",
                "delete_reason": _safe_audit_text(reason, max_chars=320) or "manual delete",
                "deleted_at": now.isoformat(),
            },
            updated_at=now,
        )

    def merge_source(
        self,
        *,
        source: MemoryAnchor,
        reason: str,
        now: datetime,
    ) -> MemoryAnchor:
        if self.status != LifecycleStatus.ACTIVE or source.status != LifecycleStatus.ACTIVE:
            raise MemoryValidationError("Only active memory anchors can be merged")
        if self.id == source.id:
            raise MemoryValidationError("Cannot merge a memory anchor into itself")
        if self.space_id != source.space_id or self.memory_scope_id != source.memory_scope_id:
            raise MemoryValidationError("Memory anchors must belong to the same scope")
        if self.kind != source.kind:
            raise MemoryValidationError("Memory anchors must have the same kind")
        audit = {
            "source_anchor_id": str(source.id),
            "source_label": source.label,
            "reason": _safe_audit_text(reason, max_chars=320),
            "merged_at": now.isoformat(),
        }
        next_valid_from, next_valid_to = _merge_temporal_window(
            current_from=self.valid_from,
            current_to=self.valid_to,
            observed_from=source.valid_from,
            observed_to=source.valid_to,
        )
        _validate_temporal_range(valid_from=next_valid_from, valid_to=next_valid_to)
        return replace(
            self,
            aliases=_unique_aliases((*self.aliases, source.label, *source.aliases)),
            confidence=_max_confidence(self.confidence, source.confidence),
            evidence_refs=_unique_source_refs((*self.evidence_refs, *source.evidence_refs)),
            observed_at=_latest_datetime(self.observed_at, source.observed_at),
            valid_from=next_valid_from,
            valid_to=next_valid_to,
            metadata=_append_anchor_audit(
                self.metadata,
                key="merge_events",
                event=audit,
                extra={
                    "resolver_version": "anchor-lifecycle-v2",
                    "merged_anchor_ids": list(
                        _unique_strings(
                            (
                                *tuple(
                                    str(item)
                                    for item in self.metadata.get("merged_anchor_ids", ())
                                ),
                                str(source.id),
                            )
                        )
                    ),
                },
            ),
            updated_at=now,
        )

    def mark_merged_into(
        self,
        *,
        target_anchor_id: MemoryAnchorId,
        reason: str,
        now: datetime,
    ) -> MemoryAnchor:
        if self.status != LifecycleStatus.ACTIVE:
            raise MemoryValidationError("Only active memory anchors can be merged")
        if self.id == target_anchor_id:
            raise MemoryValidationError("Cannot merge a memory anchor into itself")
        return replace(
            self,
            status=LifecycleStatus.DELETED,
            metadata={
                **dict(self.metadata),
                "resolver_version": "anchor-lifecycle-v2",
                "merged_into_anchor_id": str(target_anchor_id),
                "merge_reason": _safe_audit_text(reason, max_chars=320),
                "merged_at": now.isoformat(),
            },
            updated_at=now,
        )

    def remove_alias(
        self,
        *,
        alias: str,
        reason: str,
        now: datetime,
    ) -> MemoryAnchor:
        safe_alias = alias.strip()
        if self.status != LifecycleStatus.ACTIVE:
            raise MemoryValidationError("Only active memory anchors can be split")
        if not safe_alias:
            raise MemoryValidationError("Split alias is required")
        if safe_alias.lower() == self.label.lower():
            raise MemoryValidationError("Anchor label cannot be split as an alias")
        remaining = tuple(item for item in self.aliases if item.lower() != safe_alias.lower())
        if len(remaining) == len(self.aliases):
            raise MemoryValidationError("Split alias does not belong to anchor")
        return replace(
            self,
            aliases=_unique_aliases((self.label, *remaining)),
            metadata=_append_anchor_audit(
                self.metadata,
                key="split_events",
                event={
                    "alias": safe_alias[:240],
                    "reason": _safe_audit_text(reason, max_chars=320),
                    "split_at": now.isoformat(),
                },
                extra={"resolver_version": "anchor-lifecycle-v2"},
            ),
            updated_at=now,
        )

def _unique_aliases(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    aliases: list[str] = []
    for value in values:
        alias = value.strip()
        key = alias.lower()
        if not alias or key in seen:
            continue
        seen.add(key)
        aliases.append(alias[:240])
        if len(aliases) >= 20:
            break
    return tuple(aliases)
