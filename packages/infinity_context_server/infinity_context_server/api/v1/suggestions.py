"""Suggestions review API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from infinity_context_core.application import (
    ApproveSuggestionCommand,
    ExpireSuggestionCommand,
    ListSuggestionsQuery,
    RejectSuggestionCommand,
    ResolveDuplicateMergeCommand,
    ResolveSuggestionConflictCommand,
)

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

suggestion_to_response = memory_facts_feature.suggestion_to_response


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_suggestion(
    request: memory_facts_feature.CreateSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    memory_facts_feature.validate_suggestion_confidence_and_trust(
        request.confidence,
        request.trust_level,
    )
    memory_facts_feature.validate_suggestion_operation(request.operation)
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
        memory_facts_feature.create_suggestion_command_from_v1_request(
            request,
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
        )
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
    memory_facts_feature.validate_suggestion_status_filter(status_filter)
    if operation is not None:
        memory_facts_feature.validate_suggestion_operation(operation)
    normalized_tag = memory_facts_feature.normalize_suggestion_tag_filter(tag)
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
    request: memory_facts_feature.CreateSuggestionsBatchRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    for item in request.items:
        memory_facts_feature.validate_suggestion_confidence_and_trust(
            item.confidence,
            item.trust_level,
        )
        memory_facts_feature.validate_suggestion_operation(item.operation)
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
        memory_facts_feature.create_suggestions_batch_command_from_v1_request(
            request,
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
        )
    )
    return {"data": memory_facts_feature.create_suggestions_batch_to_response(result)}


@router.post("/review-batch")
async def review_suggestions_batch(
    request: memory_facts_feature.ReviewSuggestionsBatchRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.review_suggestions_batch.execute(
        memory_facts_feature.review_suggestions_batch_command_from_v1_request(
            request,
        )
    )
    return {"data": memory_facts_feature.review_suggestions_batch_to_response(result)}


@router.post("/{suggestion_id}/resolve-conflict")
async def resolve_suggestion_conflict(
    suggestion_id: str,
    request: memory_facts_feature.ResolveSuggestionConflictRequest,
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
    request: memory_facts_feature.ResolveDuplicateMergeRequest,
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
    request: memory_facts_feature.ReviewSuggestionRequest,
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
    request: memory_facts_feature.ReviewSuggestionRequest,
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
    request: memory_facts_feature.ReviewSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.expire_suggestion.execute(
        ExpireSuggestionCommand(suggestion_id=suggestion_id, reason=request.reason)
    )
    return {"data": memory_facts_feature.suggestion_to_response(result.suggestion)}
