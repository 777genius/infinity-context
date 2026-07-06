"""Suggestion request contracts and command mappers for the memory_facts seam."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infinity_context_core.application import (
    CreateSuggestionCommand,
    CreateSuggestionsBatchCommand,
    ReviewSuggestionBatchItemCommand,
    ReviewSuggestionsBatchCommand,
)
from infinity_context_core.domain.entities import Confidence, SuggestionStatus, TrustLevel
from infinity_context_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.features.memory_facts.compatibility import (
    memory_kind_from_v1_request,
    source_ref_from_v1_request,
)
from infinity_context_server.features.memory_facts.contracts import SourceRefRequest


class CreateSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    candidate_text: str = Field(min_length=1, max_length=4000)
    kind: str = "note"
    source_refs: list[SourceRefRequest] = Field(default_factory=list)
    confidence: str = "medium"
    trust_level: str = "medium"
    safe_reason: str = Field(min_length=1, max_length=320)
    target_fact_id: str | None = Field(default=None, max_length=80)
    target_fact_version: int | None = Field(default=None, ge=1)
    operation: str = Field(default="add", max_length=40)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=10)
    ttl_policy: str | None = Field(default=None, max_length=80)
    expires_at: datetime | None = None
    expiry_reason: str | None = Field(default=None, max_length=160)
    created_from_capture_id: str | None = Field(default=None, max_length=80)
    candidate_fingerprint: str | None = Field(default=None, max_length=80)
    review_payload: dict[str, Any] | None = None
    auto_approve: bool = False


class CreateSuggestionBatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_text: str = Field(min_length=1, max_length=4000)
    kind: str = "note"
    source_refs: list[SourceRefRequest] = Field(default_factory=list)
    confidence: str = "medium"
    trust_level: str = "medium"
    safe_reason: str = Field(min_length=1, max_length=320)
    target_fact_id: str | None = Field(default=None, max_length=80)
    target_fact_version: int | None = Field(default=None, ge=1)
    operation: str = Field(default="add", max_length=40)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=10)
    ttl_policy: str | None = Field(default=None, max_length=80)
    expires_at: datetime | None = None
    expiry_reason: str | None = Field(default=None, max_length=160)
    created_from_capture_id: str | None = Field(default=None, max_length=80)
    candidate_fingerprint: str | None = Field(default=None, max_length=80)
    review_payload: dict[str, Any] | None = None
    auto_approve: bool = False


class CreateSuggestionsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    items: list[CreateSuggestionBatchItemRequest] = Field(min_length=1, max_length=50)
    continue_on_error: bool = False


class ReviewSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=320)
    force: bool = False


class ResolveSuggestionConflictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=40)
    reason: str | None = Field(default=None, max_length=320)
    force: bool = False


class ResolveDuplicateMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=40)
    reason: str | None = Field(default=None, max_length=320)
    force: bool = False


class ReviewSuggestionBatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(min_length=1, max_length=160)
    action: str = Field(max_length=16)
    reason: str | None = Field(default=None, max_length=320)
    force: bool = False


class ReviewSuggestionsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReviewSuggestionBatchItemRequest] = Field(min_length=1, max_length=50)
    continue_on_error: bool = False


def create_suggestion_command_from_v1_request(
    request: CreateSuggestionRequest | CreateSuggestionBatchItemRequest,
    *,
    space_id: Any,
    memory_scope_id: Any,
) -> CreateSuggestionCommand:
    validate_suggestion_confidence_and_trust(request.confidence, request.trust_level)
    validate_suggestion_operation(request.operation)
    return CreateSuggestionCommand(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        candidate_text=request.candidate_text,
        kind=memory_kind_from_v1_request(request.kind),
        source_refs=tuple(
            source_ref_from_v1_request(ref) for ref in request.source_refs
        ),
        confidence=request.confidence,
        trust_level=request.trust_level,
        safe_reason=request.safe_reason,
        target_fact_id=request.target_fact_id,
        target_fact_version=request.target_fact_version,
        operation=request.operation,
        category=request.category,
        tags=tuple(_normalize_tags(request.tags)),
        ttl_policy=request.ttl_policy,
        expires_at=request.expires_at,
        expiry_reason=request.expiry_reason,
        created_from_capture_id=request.created_from_capture_id,
        candidate_fingerprint=request.candidate_fingerprint,
        review_payload=request.review_payload,
        auto_approve=request.auto_approve,
    )


def create_suggestions_batch_command_from_v1_request(
    request: CreateSuggestionsBatchRequest,
    *,
    space_id: Any,
    memory_scope_id: Any,
) -> CreateSuggestionsBatchCommand:
    return CreateSuggestionsBatchCommand(
        items=tuple(
            create_suggestion_command_from_v1_request(
                item,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
            )
            for item in request.items
        ),
        continue_on_error=request.continue_on_error,
    )


def review_suggestions_batch_command_from_v1_request(
    request: ReviewSuggestionsBatchRequest,
) -> ReviewSuggestionsBatchCommand:
    return ReviewSuggestionsBatchCommand(
        items=tuple(
            _review_suggestion_batch_item_command_from_v1_request(item)
            for item in request.items
        ),
        continue_on_error=request.continue_on_error,
    )


def validate_suggestion_confidence_and_trust(
    confidence: str,
    trust_level: str,
) -> None:
    try:
        Confidence(confidence)
        TrustLevel(trust_level)
    except ValueError as exc:
        raise MemoryValidationError("Unknown confidence or trust level") from exc


def validate_suggestion_status_filter(status_filter: str | None) -> None:
    if status_filter is None:
        return
    try:
        SuggestionStatus(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown suggestion status") from exc


def validate_suggestion_operation(value: str) -> None:
    if value not in {"add", "update", "delete", "review"}:
        raise MemoryValidationError("Unknown suggestion operation")


def validate_suggestion_review_action(value: str) -> None:
    if value not in {"approve", "reject", "expire"}:
        raise MemoryValidationError("Unknown suggestion review action")


def normalize_suggestion_tag_filter(tag: str | None) -> str | None:
    return _normalize_single_tag(tag)


def _review_suggestion_batch_item_command_from_v1_request(
    request: ReviewSuggestionBatchItemRequest,
) -> ReviewSuggestionBatchItemCommand:
    validate_suggestion_review_action(request.action)
    return ReviewSuggestionBatchItemCommand(
        suggestion_id=request.suggestion_id,
        action=request.action,
        reason=request.reason,
        force=request.force,
    )


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        stripped = _normalize_single_tag(tag)
        if not stripped:
            continue
        if stripped not in normalized:
            normalized.append(stripped)
    return normalized


def _normalize_single_tag(tag: str | None) -> str | None:
    if tag is None:
        return None
    stripped = tag.strip().lower()
    if not stripped:
        return None
    if len(stripped) > 48:
        raise MemoryValidationError("Suggestion tag is too long")
    return stripped


__all__ = (
    "CreateSuggestionBatchItemRequest",
    "CreateSuggestionRequest",
    "CreateSuggestionsBatchRequest",
    "ResolveDuplicateMergeRequest",
    "ResolveSuggestionConflictRequest",
    "ReviewSuggestionBatchItemRequest",
    "ReviewSuggestionRequest",
    "ReviewSuggestionsBatchRequest",
    "create_suggestion_command_from_v1_request",
    "create_suggestions_batch_command_from_v1_request",
    "normalize_suggestion_tag_filter",
    "review_suggestions_batch_command_from_v1_request",
    "validate_suggestion_confidence_and_trust",
    "validate_suggestion_operation",
    "validate_suggestion_review_action",
    "validate_suggestion_status_filter",
)
