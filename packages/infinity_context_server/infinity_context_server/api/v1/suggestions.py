"""Suggestions review API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from infinity_context_core.application import (
    ApproveSuggestionCommand,
    CreateSuggestionCommand,
    CreateSuggestionsBatchCommand,
    ExpireSuggestionCommand,
    ListSuggestionsQuery,
    RejectSuggestionCommand,
    ResolveDuplicateMergeCommand,
    ResolveSuggestionConflictCommand,
    ReviewSuggestionBatchItemCommand,
    ReviewSuggestionsBatchCommand,
)
from infinity_context_core.domain.entities import (
    Confidence,
    SuggestionStatus,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from infinity_context_server.composition import Container
from infinity_context_server.features.memory_facts import public as memory_facts_feature

router = APIRouter(
    prefix="/suggestions",
    tags=["suggestions"],
    dependencies=[Depends(require_service_token)],
)

SourceRefRequest = memory_facts_feature.SourceRefRequest


class CreateSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
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
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
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


suggestion_to_response = memory_facts_feature.suggestion_to_response


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_suggestion(
    request: CreateSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    _validate_confidence_and_trust(request.confidence, request.trust_level)
    _validate_operation(request.operation)
    scope = await resolve_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=None,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    result = await container.create_suggestion.execute(
        _create_suggestion_command(request, scope.space_id, scope.memory_scope_id)
    )
    return {"data": memory_facts_feature.suggestion_to_response(result.suggestion)}


@router.get("")
async def list_suggestions(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    operation: Annotated[str | None, Query(max_length=40)] = None,
    category: Annotated[str | None, Query(max_length=80)] = None,
    tag: Annotated[str | None, Query(max_length=48)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    _validate_suggestion_status(status_filter)
    if operation is not None:
        _validate_operation(operation)
    normalized_tag = _normalize_single_tag(tag)
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=None,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    if scope is None:
        return {"data": []}
    suggestions = await container.list_suggestions.execute(
        ListSuggestionsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            status=status_filter,
            operation=operation,
            category=category.strip().lower() if category else None,
            tag=normalized_tag,
            limit=limit,
        )
    )
    return {
        "data": [
            memory_facts_feature.suggestion_to_response(suggestion)
            for suggestion in suggestions
        ]
    }


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def create_suggestions_batch(
    request: CreateSuggestionsBatchRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    for item in request.items:
        _validate_confidence_and_trust(item.confidence, item.trust_level)
        _validate_operation(item.operation)
    scope = await resolve_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=None,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    result = await container.create_suggestions_batch.execute(
        CreateSuggestionsBatchCommand(
            items=tuple(
                _create_suggestion_command(item, scope.space_id, scope.memory_scope_id)
                for item in request.items
            ),
            continue_on_error=request.continue_on_error,
        )
    )
    return {"data": memory_facts_feature.create_suggestions_batch_to_response(result)}


@router.post("/review-batch")
async def review_suggestions_batch(
    request: ReviewSuggestionsBatchRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    for item in request.items:
        _validate_review_action(item.action)
    result = await container.review_suggestions_batch.execute(
        ReviewSuggestionsBatchCommand(
            items=tuple(
                ReviewSuggestionBatchItemCommand(
                    suggestion_id=item.suggestion_id,
                    action=item.action,
                    reason=item.reason,
                    force=item.force,
                )
                for item in request.items
            ),
            continue_on_error=request.continue_on_error,
        )
    )
    return {"data": memory_facts_feature.review_suggestions_batch_to_response(result)}


@router.post("/{suggestion_id}/resolve-conflict")
async def resolve_suggestion_conflict(
    suggestion_id: str,
    request: ResolveSuggestionConflictRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.resolve_suggestion_conflict.execute(
        ResolveSuggestionConflictCommand(
            suggestion_id=suggestion_id,
            action=request.action,
            reason=request.reason,
            force=request.force,
        )
    )
    return {"data": memory_facts_feature.suggestion_result_to_response(result)}


@router.post("/{suggestion_id}/resolve-duplicate")
async def resolve_duplicate_merge(
    suggestion_id: str,
    request: ResolveDuplicateMergeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.resolve_duplicate_merge.execute(
        ResolveDuplicateMergeCommand(
            suggestion_id=suggestion_id,
            action=request.action,
            reason=request.reason,
            force=request.force,
        )
    )
    return {"data": memory_facts_feature.suggestion_result_to_response(result)}


@router.post("/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: str,
    request: ReviewSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.approve_suggestion.execute(
        ApproveSuggestionCommand(
            suggestion_id=suggestion_id,
            reason=request.reason,
            force=request.force,
        )
    )
    return {"data": memory_facts_feature.suggestion_result_to_response(result)}


@router.post("/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    request: ReviewSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.reject_suggestion.execute(
        RejectSuggestionCommand(suggestion_id=suggestion_id, reason=request.reason)
    )
    return {"data": memory_facts_feature.suggestion_to_response(result.suggestion)}


@router.post("/{suggestion_id}/expire")
async def expire_suggestion(
    suggestion_id: str,
    request: ReviewSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.expire_suggestion.execute(
        ExpireSuggestionCommand(suggestion_id=suggestion_id, reason=request.reason)
    )
    return {"data": memory_facts_feature.suggestion_to_response(result.suggestion)}


def _validate_confidence_and_trust(confidence: str, trust_level: str) -> None:
    try:
        Confidence(confidence)
        TrustLevel(trust_level)
    except ValueError as exc:
        raise MemoryValidationError("Unknown confidence or trust level") from exc


def _validate_suggestion_status(status_filter: str | None) -> None:
    if status_filter is None:
        return
    try:
        SuggestionStatus(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown suggestion status") from exc


def _validate_operation(value: str) -> None:
    if value not in {"add", "update", "delete", "review"}:
        raise MemoryValidationError("Unknown suggestion operation")


def _validate_review_action(value: str) -> None:
    if value not in {"approve", "reject", "expire"}:
        raise MemoryValidationError("Unknown suggestion review action")


def _create_suggestion_command(
    request: CreateSuggestionRequest | CreateSuggestionBatchItemRequest,
    space_id: Any,
    memory_scope_id: Any,
) -> CreateSuggestionCommand:
    return CreateSuggestionCommand(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        candidate_text=request.candidate_text,
        kind=memory_facts_feature.memory_kind_from_v1_request(request.kind),
        source_refs=tuple(
            memory_facts_feature.source_ref_from_v1_request(ref)
            for ref in request.source_refs
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
