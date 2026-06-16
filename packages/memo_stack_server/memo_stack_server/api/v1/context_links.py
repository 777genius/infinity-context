"""Context-link suggestion and approval API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from memo_stack_core.application import (
    CreateContextLinkCommand,
    DeleteContextLinkCommand,
    ListContextLinksQuery,
    ListContextLinkSuggestionsQuery,
    ReviewContextLinkSuggestionCommand,
    ReviewContextLinkSuggestionBatchItemCommand,
    ReviewContextLinkSuggestionsBatchCommand,
    SuggestContextLinksCommand,
    UpdateContextLinkCommand,
)
from memo_stack_core.domain.assets import MemoryContextLink, MemoryContextLinkSuggestion
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from memo_stack_server.composition import Container

router = APIRouter(
    tags=["context-links"],
    dependencies=[Depends(require_service_token)],
)


class SuggestContextLinksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    text: str = Field(default="", max_length=20_000)
    source_type: str | None = Field(default=None, max_length=80)
    source_id: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=10, ge=1, le=30)
    persist: bool = False


class CreateContextLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=160)
    relation_type: str = Field(default="related_to", min_length=1, max_length=80)
    confidence: str = Field(default="medium", min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=320)
    metadata: dict[str, Any] | None = None


class ReviewContextLinkSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=16)
    reason: str | None = Field(default=None, max_length=320)
    target_type: str | None = Field(default=None, min_length=1, max_length=80)
    target_id: str | None = Field(default=None, min_length=1, max_length=160)
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    confidence: str | None = Field(default=None, min_length=1, max_length=40)
    link_reason: str | None = Field(default=None, min_length=1, max_length=320)


class ReviewContextLinkSuggestionBatchItemRequest(ReviewContextLinkSuggestionRequest):
    suggestion_id: str = Field(min_length=1, max_length=160)


class ReviewContextLinkSuggestionsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReviewContextLinkSuggestionBatchItemRequest] = Field(
        min_length=1,
        max_length=50,
    )
    continue_on_error: bool = False


class UpdateContextLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str | None = Field(default=None, min_length=1, max_length=80)
    source_id: str | None = Field(default=None, min_length=1, max_length=160)
    target_type: str | None = Field(default=None, min_length=1, max_length=80)
    target_id: str | None = Field(default=None, min_length=1, max_length=160)
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    confidence: str | None = Field(default=None, min_length=1, max_length=40)
    reason: str | None = Field(default=None, min_length=1, max_length=320)
    metadata: dict[str, Any] | None = None


@router.post("/link-suggestions")
async def suggest_context_links(
    request: SuggestContextLinksRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    if request.persist:
        ensure_server_writes_enabled(container)
    scope = await resolve_existing_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=request.thread_external_ref,
        thread_required=False,
    )
    if scope is None:
        return {"data": {"candidates": [], "diagnostics": {"scope_not_found": True}}}
    result = await container.suggest_context_links.execute(
        SuggestContextLinksCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            text=request.text,
            source_type=request.source_type,
            source_id=request.source_id,
            limit=request.limit,
            persist=request.persist,
        )
    )
    return {
        "data": {
            "candidates": [
                {
                    "target_type": item.target_type,
                    "target_id": item.target_id,
                    "label": item.label,
                    "preview": item.preview,
                    "score": item.score,
                    "tier": item.tier,
                    "reasons": list(item.reasons),
                    "suggestion_id": item.suggestion_id,
                    "status": item.status,
                    "metadata": item.metadata or {},
                }
                for item in result.candidates
            ],
            "diagnostics": result.diagnostics,
        }
    }


@router.post("/context-links")
async def create_context_link(
    request: CreateContextLinkRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
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
    result = await container.create_context_link.execute(
        CreateContextLinkCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            source_type=request.source_type,
            source_id=request.source_id,
            target_type=request.target_type,
            target_id=request.target_id,
            relation_type=request.relation_type,
            confidence=request.confidence,
            reason=request.reason,
            metadata=request.metadata,
        )
    )
    return {"data": {**context_link_to_response(result.link), "duplicate": result.duplicate}}


@router.get("/context-links")
async def list_context_links(
    container: Annotated[Container, Depends(get_container)],
    source_type: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    source_id: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    statuses_filter: Annotated[str | None, Query(alias="statuses", max_length=240)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
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
    links = await container.list_context_links.execute(
        ListContextLinksQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            source_type=source_type,
            source_id=source_id,
            status=None,
            statuses=_normalize_status_filter(status_filter, statuses_filter),
            limit=limit,
        )
    )
    return {"data": [context_link_to_response(link) for link in links]}


@router.get("/context-link-suggestions")
async def list_context_link_suggestions(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    source_type: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    source_id: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "pending",
    statuses_filter: Annotated[str | None, Query(alias="statuses", max_length=240)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
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
    suggestions = await container.list_context_link_suggestions.execute(
        ListContextLinkSuggestionsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            status=None,
            statuses=_normalize_status_filter(status_filter, statuses_filter),
            source_type=source_type,
            source_id=source_id,
            limit=limit,
        )
    )
    return {"data": [context_link_suggestion_to_response(item) for item in suggestions]}


@router.patch("/context-links/{context_link_id}")
async def update_context_link(
    context_link_id: str,
    request: UpdateContextLinkRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.update_context_link.execute(
        UpdateContextLinkCommand(
            context_link_id=context_link_id,
            source_type=request.source_type,
            source_id=request.source_id,
            target_type=request.target_type,
            target_id=request.target_id,
            relation_type=request.relation_type,
            confidence=request.confidence,
            reason=request.reason,
            metadata=request.metadata,
        )
    )
    return {"data": context_link_to_response(result.link)}


@router.post("/context-link-suggestions/review-batch")
async def review_context_link_suggestions_batch(
    request: ReviewContextLinkSuggestionsBatchRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.review_context_link_suggestions_batch.execute(
        ReviewContextLinkSuggestionsBatchCommand(
            items=tuple(
                ReviewContextLinkSuggestionBatchItemCommand(
                    suggestion_id=item.suggestion_id,
                    action=item.action,
                    reason=item.reason,
                    target_type=item.target_type,
                    target_id=item.target_id,
                    relation_type=item.relation_type,
                    confidence=item.confidence,
                    link_reason=item.link_reason,
                )
                for item in request.items
            ),
            continue_on_error=request.continue_on_error,
        )
    )
    return {"data": _review_context_link_batch_to_response(result)}


@router.post("/context-link-suggestions/{context_link_suggestion_id}/review")
async def review_context_link_suggestion(
    context_link_suggestion_id: str,
    request: ReviewContextLinkSuggestionRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.review_context_link_suggestion.execute(
        ReviewContextLinkSuggestionCommand(
            suggestion_id=context_link_suggestion_id,
            action=request.action,
            reason=request.reason,
            target_type=request.target_type,
            target_id=request.target_id,
            relation_type=request.relation_type,
            confidence=request.confidence,
            link_reason=request.link_reason,
        )
    )
    return {
        "data": {
            "suggestion": context_link_suggestion_to_response(result.suggestion),
            "link": context_link_to_response(result.link) if result.link else None,
            "duplicate_link": result.duplicate_link,
        }
    }


@router.delete("/context-links/{context_link_id}")
async def delete_context_link(
    context_link_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.delete_context_link.execute(
        DeleteContextLinkCommand(context_link_id=context_link_id)
    )
    return {"data": context_link_to_response(result.link)}


def _review_context_link_batch_to_response(result: Any) -> dict[str, Any]:
    return {
        "applied": result.applied,
        "failed": result.failed,
        "stopped": result.stopped,
        "results": [
            {
                "suggestion_id": item.suggestion_id,
                "action": item.action,
                "status": item.status,
                **_review_context_link_batch_item_payload(item),
            }
            for item in result.results
        ],
    }


def _review_context_link_batch_item_payload(item: Any) -> dict[str, Any]:
    if item.result is None:
        return {
            "error_code": item.error_code,
            "error_message": item.error_message,
        }
    return {
        "suggestion": context_link_suggestion_to_response(item.result.suggestion),
        "link": context_link_to_response(item.result.link) if item.result.link else None,
        "duplicate_link": item.result.duplicate_link,
    }


def context_link_to_response(link: MemoryContextLink) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "space_id": str(link.space_id),
        "memory_scope_id": str(link.memory_scope_id),
        "source_type": link.source_type,
        "source_id": link.source_id,
        "target_type": link.target_type,
        "target_id": link.target_id,
        "relation_type": link.relation_type,
        "confidence": link.confidence,
        "reason": link.reason,
        "status": link.status.value,
        "metadata": _safe_metadata(link.metadata),
        "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat(),
    }


def context_link_suggestion_to_response(
    suggestion: MemoryContextLinkSuggestion,
) -> dict[str, Any]:
    return {
        "id": str(suggestion.id),
        "space_id": str(suggestion.space_id),
        "memory_scope_id": str(suggestion.memory_scope_id),
        "source_type": suggestion.source_type,
        "source_id": suggestion.source_id,
        "target_type": suggestion.target_type,
        "target_id": suggestion.target_id,
        "relation_type": suggestion.relation_type,
        "confidence": suggestion.confidence,
        "reason": suggestion.reason,
        "score": suggestion.score,
        "status": suggestion.status.value,
        "metadata": _safe_metadata(suggestion.metadata),
        "created_at": suggestion.created_at.isoformat(),
        "updated_at": suggestion.updated_at.isoformat(),
        "reviewed_at": suggestion.reviewed_at.isoformat() if suggestion.reviewed_at else None,
        "review_reason": suggestion.review_reason,
    }


def _safe_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        if isinstance(value, (str, int, float, bool, type(None))):
            safe[key_text] = value
        elif key_text == "edit_events" and isinstance(value, list):
            events: list[dict[str, Any]] = []
            for item in value[-20:]:
                event = _safe_context_link_edit_event(item)
                if event is not None:
                    events.append(event)
            if events:
                safe[key_text] = events
        elif isinstance(value, list):
            items = [
                item
                for item in value[:20]
                if isinstance(item, (str, int, float, bool, type(None)))
            ]
            if items:
                safe[key_text] = items
    return safe


def _normalize_status_filter(
    status_filter: str | None,
    statuses_filter: str | None,
) -> tuple[str, ...] | None:
    raw_values = statuses_filter.split(",") if statuses_filter is not None else [status_filter]
    values: list[str] = []
    for raw_value in raw_values:
        value = (raw_value or "").strip().lower()
        if not value:
            continue
        if value in {"all", "*"}:
            return None
        if value not in values:
            values.append(value)
    return tuple(values) if values else None


def _safe_context_link_edit_event(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    event: dict[str, Any] = {}
    for key in ("edited_at", "source"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            event[key] = raw[:160]
    changed_fields = value.get("changed_fields")
    if isinstance(changed_fields, list):
        event["changed_fields"] = [
            str(item)[:80] for item in changed_fields[:20] if isinstance(item, str)
        ]
    for key in ("previous", "next"):
        raw = value.get(key)
        if isinstance(raw, dict):
            event[key] = _safe_context_link_snapshot(raw)
    return event or None


def _safe_context_link_snapshot(value: dict[str, Any]) -> dict[str, str]:
    allowed = {
        "source_type",
        "source_id",
        "target_type",
        "target_id",
        "relation_type",
        "confidence",
        "reason",
    }
    return {key: str(value[key])[:320] for key in allowed if isinstance(value.get(key), str)}
