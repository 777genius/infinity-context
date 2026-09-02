"""Compatibility mapping from legacy suggestions to canonical reviewed fact commands."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

from infinity_context_core.application.code_scope_metadata import code_scope_from_metadata
from infinity_context_core.domain.entities import MemorySuggestion
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryForbiddenError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.features.memory_facts.public import (
    FactCodeScopeReference,
    FactQuality,
    FactRetention,
    FactTemporalExtent,
    FactTemporalKind,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSourceRef,
    ReviewedFactCandidate,
    ReviewedFactDecision,
    ReviewedFactMutationResult,
    ReviewedFactTarget,
)
from infinity_context_core.features.review_governance.public import SuggestionReviewScope


def authorize_suggestion_review(
    suggestion: MemorySuggestion,
    review_scope: SuggestionReviewScope | None,
) -> None:
    """Fail closed for scoped reviewers while retaining explicit root workflows."""

    if review_scope is None:
        return
    repository_id, code_scope_id = code_scope_from_metadata(
        suggestion.review_payload or {},
        source="Suggestion",
    )
    if not review_scope.allows(
        space_id=str(suggestion.space_id),
        memory_scope_id=str(suggestion.memory_scope_id),
        repository_id=repository_id,
        code_scope_id=code_scope_id,
    ):
        raise MemoryForbiddenError("Reviewer is not authorized for suggestion scope")


async def apply_reviewed_fact_mutation(
    mutation: Awaitable[ReviewedFactMutationResult],
) -> ReviewedFactMutationResult:
    """Translate canonical policy failures at the legacy process boundary."""

    try:
        return await mutation
    except LookupError as exc:
        raise MemoryNotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise MemoryConflictError(str(exc)) from exc


def reviewed_fact_decision(
    suggestion: MemorySuggestion,
    *,
    actor_id: str,
    reason: str,
    now: datetime,
    allow_weaker: bool,
    target_fact_id: str | None = None,
    target_fact_version: int | None = None,
) -> ReviewedFactDecision:
    repository_id, code_scope_id = code_scope_from_metadata(
        suggestion.review_payload or {},
        source="Suggestion",
    )
    code_scope = (
        FactCodeScopeReference(repository_id, code_scope_id) if repository_id is not None else None
    )
    scope = MemoryFactScope(
        space_id=str(suggestion.space_id),
        memory_scope_id=str(suggestion.memory_scope_id),
        thread_id=_canonical_source_thread_id(suggestion.review_payload or {}),
    )
    sources = tuple(_canonical_source_ref(ref) for ref in suggestion.source_refs)
    candidate = ReviewedFactCandidate(
        scope=scope,
        text=suggestion.candidate_text,
        source_refs=sources,
        evidence_refs=tuple(MemoryFactEvidenceRef(source_ref=ref) for ref in sources),
        kind=suggestion.kind.value,
        quality=FactQuality(
            confidence=suggestion.confidence.value,
            trust_level=suggestion.trust_level.value,
            classification="internal",
        ),
        temporal_extent=_candidate_temporal_extent(
            suggestion.review_payload or {},
            observed_at=now,
        ),
        category=suggestion.category,
        tags=suggestion.tags,
        retention=FactRetention(
            ttl_policy=suggestion.ttl_policy,
            context_expires_at=_as_aware_utc(suggestion.expires_at),
        ),
        code_scope=code_scope,
    )
    resolved_target_id = target_fact_id or (
        str(suggestion.target_fact_id) if suggestion.target_fact_id is not None else None
    )
    resolved_target_version = target_fact_version or suggestion.target_fact_version
    target = None
    if resolved_target_id is not None:
        if resolved_target_version is None:
            raise MemoryValidationError("Target fact version is required")
        target = ReviewedFactTarget(
            identity=MemoryFactIdentity(resolved_target_id, scope),
            expected_version=resolved_target_version,
            code_scope=code_scope,
        )
    return ReviewedFactDecision(
        candidate=candidate,
        target=target,
        actor_id=actor_id,
        reason_code=reason,
        idempotency_key=f"suggestion:{suggestion.id}:{_resolution_key(reason)}",
        effective_at=now,
        allow_weaker_evidence=allow_weaker,
    )


def _candidate_temporal_extent(
    payload: dict[str, object],
    *,
    observed_at: datetime,
) -> FactTemporalExtent | None:
    valid_from = _optional_aware_datetime(payload.get("valid_from"), "valid_from")
    valid_to = _optional_aware_datetime(payload.get("valid_until"), "valid_until")
    if valid_from is None and valid_to is None:
        return None
    try:
        return FactTemporalExtent(
            kind=FactTemporalKind.STATE,
            observed_at=observed_at,
            valid_from=valid_from,
            valid_to=valid_to,
            basis="extracted",
        )
    except ValueError as exc:
        raise MemoryValidationError(str(exc)) from exc


def _optional_aware_datetime(value: object, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise MemoryValidationError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryValidationError(f"{field_name} must be timezone-aware")
    return parsed


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def targeted_suggestion_resolution_kind(suggestion: MemorySuggestion) -> str:
    value = str((suggestion.review_payload or {}).get("resolution_kind") or "").strip()
    if value in {"correction", "supersede"}:
        return value
    raise MemoryValidationError(
        "Targeted suggestion requires resolution_kind=correction or supersede"
    )


def annotate_canonical_review_resolution(
    suggestion: MemorySuggestion,
    *,
    outcome: ReviewedFactMutationResult,
    resolution_kind: str,
    actor_id: str,
    now: datetime,
) -> MemorySuggestion:
    payload = dict(suggestion.review_payload or {})
    payload.update(
        {
            "canonical_resolution_kind": resolution_kind,
            "canonical_review_actor_id": actor_id,
            "canonical_resolved_at": now.isoformat(),
            "canonical_fact_ids": [fact.identity.fact_id for fact in outcome.affected_facts],
            "canonical_fact_versions": [fact.visibility.version for fact in outcome.affected_facts],
            "temporal_decision_id": (
                outcome.decision.decision_id if outcome.decision is not None else None
            ),
            "outbox_message_ids": list(outcome.outbox_message_ids),
        }
    )
    return replace(suggestion, review_payload=payload, updated_at=now)


def annotate_suggestion_reviewer(
    suggestion: MemorySuggestion,
    *,
    actor_id: str,
    now: datetime,
) -> MemorySuggestion:
    payload = dict(suggestion.review_payload or {})
    payload.update(
        {
            "review_actor_id": actor_id,
            "reviewed_at": now.isoformat(),
        }
    )
    return replace(suggestion, review_payload=payload, updated_at=now)


def _canonical_source_ref(ref: object) -> MemoryFactSourceRef:
    return MemoryFactSourceRef(
        source_type=str(ref.source_type),
        source_id=str(ref.source_id),
        chunk_id=getattr(ref, "chunk_id", None),
        char_start=getattr(ref, "char_start", None),
        char_end=getattr(ref, "char_end", None),
        quote_preview=getattr(ref, "quote_preview", None),
        page_number=getattr(ref, "page_number", None),
        time_start_ms=getattr(ref, "time_start_ms", None),
        time_end_ms=getattr(ref, "time_end_ms", None),
        bbox=getattr(ref, "bbox", None),
    )


def _canonical_source_thread_id(payload: Mapping[str, object]) -> str | None:
    value = payload.get("canonical_source_thread_id")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError("Suggestion canonical source thread is invalid")
    return value.strip()


def _resolution_key(reason: str) -> str:
    return sha256(reason.strip().encode("utf-8")).hexdigest()[:24]


__all__ = (
    "annotate_canonical_review_resolution",
    "annotate_suggestion_reviewer",
    "apply_reviewed_fact_mutation",
    "authorize_suggestion_review",
    "reviewed_fact_decision",
    "targeted_suggestion_resolution_kind",
)
