"""Memory suggestion aggregate entity and review audit policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from infinity_context_core.domain.entity_policies import _safe_audit_text
from infinity_context_core.domain.entity_types import (
    MAX_SUGGESTION_REVIEW_EVENTS,
    MAX_SUGGESTION_REVIEW_REASON_CHARS,
    Confidence,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    MemorySuggestionId,
    SpaceId,
    SuggestionOperation,
    SuggestionStatus,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.domain.source_refs import SourceRef, _unique_source_refs


@dataclass(frozen=True)
class MemorySuggestion:
    id: MemorySuggestionId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    candidate_text: str
    kind: MemoryKind
    operation: SuggestionOperation
    status: SuggestionStatus
    source_refs: tuple[SourceRef, ...]
    confidence: Confidence
    trust_level: TrustLevel
    safe_reason: str
    target_fact_id: MemoryFactId | None
    target_fact_version: int | None
    created_at: datetime
    updated_at: datetime
    category: str | None = None
    tags: tuple[str, ...] = ()
    ttl_policy: str | None = None
    expires_at: datetime | None = None
    expiry_reason: str | None = None
    created_from_capture_id: str | None = None
    candidate_fingerprint: str | None = None
    review_payload: dict[str, object] | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        suggestion_id: MemorySuggestionId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        candidate_text: str,
        kind: MemoryKind,
        source_refs: tuple[SourceRef, ...],
        safe_reason: str,
        now: datetime,
        confidence: Confidence = Confidence.MEDIUM,
        trust_level: TrustLevel = TrustLevel.MEDIUM,
        target_fact_id: MemoryFactId | None = None,
        target_fact_version: int | None = None,
        operation: SuggestionOperation = SuggestionOperation.ADD,
        category: str | None = None,
        tags: tuple[str, ...] = (),
        ttl_policy: str | None = None,
        expires_at: datetime | None = None,
        expiry_reason: str | None = None,
        created_from_capture_id: str | None = None,
        candidate_fingerprint: str | None = None,
        review_payload: dict[str, object] | None = None,
    ) -> MemorySuggestion:
        if not candidate_text.strip():
            raise MemoryValidationError("Suggestion candidate_text is required")
        if not safe_reason.strip():
            raise MemoryValidationError("Suggestion safe_reason is required")
        if len(tags) > 10:
            raise MemoryValidationError("Suggestion tags exceed limit")
        if (
            operation in {SuggestionOperation.UPDATE, SuggestionOperation.DELETE}
            and not target_fact_id
        ):
            raise MemoryValidationError("Update/delete suggestion requires target fact")
        return cls(
            id=suggestion_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            candidate_text=candidate_text.strip(),
            kind=kind,
            operation=operation,
            status=SuggestionStatus.PENDING,
            source_refs=_unique_source_refs(source_refs),
            confidence=confidence,
            trust_level=trust_level,
            safe_reason=safe_reason.strip(),
            target_fact_id=target_fact_id,
            target_fact_version=target_fact_version,
            category=category,
            tags=tuple(tags),
            ttl_policy=ttl_policy,
            expires_at=expires_at,
            expiry_reason=expiry_reason,
            created_from_capture_id=created_from_capture_id,
            candidate_fingerprint=candidate_fingerprint,
            review_payload=dict(review_payload or {}),
            created_at=now,
            updated_at=now,
        )

    def approve(self, *, now: datetime, reason: str | None = None) -> MemorySuggestion:
        if self.status != SuggestionStatus.PENDING:
            raise MemoryConflictError("Only pending suggestion can be approved")
        if not self.source_refs:
            raise MemoryValidationError("Suggestion approval requires source refs")
        previous_status = self.status.value
        return replace(
            self,
            status=SuggestionStatus.APPROVED,
            updated_at=now,
            reviewed_at=now,
            review_reason=reason,
            review_payload=_append_suggestion_review_audit(
                self.review_payload or {},
                event=_suggestion_review_event(
                    suggestion=self,
                    action="approve",
                    previous_status=previous_status,
                    new_status=SuggestionStatus.APPROVED.value,
                    reviewed_at=now,
                    reason=reason,
                ),
            ),
        )

    def reject(self, *, now: datetime, reason: str | None = None) -> MemorySuggestion:
        if self.status != SuggestionStatus.PENDING:
            raise MemoryConflictError("Only pending suggestion can be rejected")
        previous_status = self.status.value
        return replace(
            self,
            status=SuggestionStatus.REJECTED,
            updated_at=now,
            reviewed_at=now,
            review_reason=reason,
            review_payload=_append_suggestion_review_audit(
                self.review_payload or {},
                event=_suggestion_review_event(
                    suggestion=self,
                    action="reject",
                    previous_status=previous_status,
                    new_status=SuggestionStatus.REJECTED.value,
                    reviewed_at=now,
                    reason=reason,
                ),
            ),
        )

    def expire(self, *, now: datetime, reason: str | None = None) -> MemorySuggestion:
        if self.status != SuggestionStatus.PENDING:
            return self
        previous_status = self.status.value
        return replace(
            self,
            status=SuggestionStatus.EXPIRED,
            updated_at=now,
            reviewed_at=now,
            review_reason=reason,
            review_payload=_append_suggestion_review_audit(
                self.review_payload or {},
                event=_suggestion_review_event(
                    suggestion=self,
                    action="expire",
                    previous_status=previous_status,
                    new_status=SuggestionStatus.EXPIRED.value,
                    reviewed_at=now,
                    reason=reason,
                ),
            ),
        )

def _append_suggestion_review_audit(
    review_payload: Mapping[str, object],
    *,
    event: Mapping[str, object],
) -> dict[str, object]:
    next_payload = dict(review_payload)
    existing = review_payload.get("review_events")
    events = (
        [item for item in existing if isinstance(item, Mapping)]
        if isinstance(existing, list)
        else []
    )
    events.append(dict(event))
    next_payload["review_events"] = events[-MAX_SUGGESTION_REVIEW_EVENTS:]
    return next_payload

def _suggestion_review_event(
    *,
    suggestion: MemorySuggestion,
    action: str,
    previous_status: str,
    new_status: str,
    reviewed_at: datetime,
    reason: str | None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "event_type": "memory_suggestion_reviewed",
        "suggestion_id": str(suggestion.id),
        "space_id": str(suggestion.space_id),
        "memory_scope_id": str(suggestion.memory_scope_id),
        "operation": suggestion.operation.value,
        "action": action,
        "previous_status": previous_status,
        "new_status": new_status,
        "reviewed_at": reviewed_at.isoformat(),
    }
    if suggestion.target_fact_id:
        event["target_fact_id"] = str(suggestion.target_fact_id)
    if suggestion.target_fact_version is not None:
        event["target_fact_version"] = suggestion.target_fact_version
    if suggestion.created_from_capture_id:
        event["created_from_capture_id"] = suggestion.created_from_capture_id
    if reason:
        event["reason"] = _safe_audit_text(
            reason,
            max_chars=MAX_SUGGESTION_REVIEW_REASON_CHARS,
        )
    return event
