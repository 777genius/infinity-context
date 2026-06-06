"""Suggestions review API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from memo_stack_core.application import (
    ApproveSuggestionCommand,
    CreateSuggestionCommand,
    ExpireSuggestionCommand,
    ListSuggestionsQuery,
    RejectSuggestionCommand,
)
from memo_stack_core.domain.entities import (
    Confidence,
    MemorySuggestion,
    SuggestionStatus,
    TrustLevel,
)
from memo_stack_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.api.v1.facts import (
    SourceRefRequest,
    fact_to_response,
    map_memory_kind,
    map_source_ref,
)
from memo_stack_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from memo_stack_server.composition import Container

router = APIRouter(
    prefix="/suggestions",
    tags=["suggestions"],
    dependencies=[Depends(require_service_token)],
)


class CreateSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    profile_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    profile_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
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


class ReviewSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=320)
    force: bool = False


def suggestion_to_response(suggestion: MemorySuggestion) -> dict[str, Any]:
    return {
        "id": str(suggestion.id),
        "space_id": str(suggestion.space_id),
        "profile_id": str(suggestion.profile_id),
        "candidate_text": suggestion.candidate_text,
        "kind": suggestion.kind.value,
        "operation": suggestion.operation.value,
        "status": suggestion.status.value,
        "source_refs": [
            {
                "source_type": ref.source_type,
                "source_id": ref.source_id,
                "chunk_id": ref.chunk_id,
                "char_start": ref.char_start,
                "char_end": ref.char_end,
                "quote_preview": ref.quote_preview,
            }
            for ref in suggestion.source_refs
        ],
        "confidence": suggestion.confidence.value,
        "trust_level": suggestion.trust_level.value,
        "safe_reason": suggestion.safe_reason,
        "target_fact_id": str(suggestion.target_fact_id) if suggestion.target_fact_id else None,
        "target_fact_version": suggestion.target_fact_version,
        "category": suggestion.category,
        "tags": list(suggestion.tags),
        "ttl_policy": suggestion.ttl_policy,
        "expires_at": suggestion.expires_at.isoformat() if suggestion.expires_at else None,
        "expiry_reason": suggestion.expiry_reason,
        "created_from_capture_id": suggestion.created_from_capture_id,
        "candidate_fingerprint": suggestion.candidate_fingerprint,
        "review_payload": suggestion.review_payload or {},
        "review_reason": suggestion.review_reason,
        "created_at": suggestion.created_at.isoformat(),
        "updated_at": suggestion.updated_at.isoformat(),
        "reviewed_at": suggestion.reviewed_at.isoformat() if suggestion.reviewed_at else None,
    }


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
        profile_id=request.profile_id,
        thread_id=None,
        space_slug=request.space_slug,
        profile_external_ref=request.profile_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    result = await container.create_suggestion.execute(
        CreateSuggestionCommand(
            space_id=scope.space_id,
            profile_id=scope.profile_id,
            candidate_text=request.candidate_text,
            kind=map_memory_kind(request.kind),
            source_refs=tuple(map_source_ref(ref) for ref in request.source_refs),
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
    )
    return {"data": suggestion_to_response(result.suggestion)}


@router.get("")
async def list_suggestions(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    profile_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    profile_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    _validate_suggestion_status(status_filter)
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        profile_id=profile_id,
        thread_id=None,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    if scope is None:
        return {"data": []}
    suggestions = await container.list_suggestions.execute(
        ListSuggestionsQuery(
            space_id=scope.space_id,
            profile_id=scope.profile_id,
            status=status_filter,
            limit=limit,
        )
    )
    return {"data": [suggestion_to_response(suggestion) for suggestion in suggestions]}


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
    body = {"suggestion": suggestion_to_response(result.suggestion)}
    if result.fact:
        body["fact"] = fact_to_response(result.fact, result.indexing_status)
    return {"data": body}


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
    return {"data": suggestion_to_response(result.suggestion)}


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
    return {"data": suggestion_to_response(result.suggestion)}


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


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        stripped = tag.strip().lower()
        if not stripped:
            continue
        if len(stripped) > 48:
            raise MemoryValidationError("Suggestion tag is too long")
        if stripped not in normalized:
            normalized.append(stripped)
    return normalized
