"""Search and prompt-context API."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application import BuildContextQuery, ConsistencyMode
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
    normalize_context_diagnostics,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_retrieve
from infinity_context_server.api.public_payload import safe_public_metadata, safe_public_text
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_context_scope,
)
from infinity_context_server.api.v1.source_refs import source_ref_to_response
from infinity_context_server.composition import Container
from infinity_context_server.features.context_building import public as context_building_server

router = APIRouter(tags=["context"], dependencies=[Depends(require_service_token)])

_LEGACY_CONTEXT_API_RESPONSES = context_building_server.LegacyContextApiResponseMapper(
    normalize_context_diagnostics=normalize_context_diagnostics,
    normalize_context_bundle_diagnostics=normalize_context_bundle_diagnostics,
    safe_public_metadata=safe_public_metadata,
    safe_public_text=safe_public_text,
    source_ref_to_response=source_ref_to_response,
)


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    memory_scope_external_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=12000)
    consistency_mode: ConsistencyMode = Field(default=ConsistencyMode.BEST_EFFORT)
    token_budget: int = Field(default=1800, ge=64, le=16000)
    max_facts: int = Field(default=20, ge=0, le=100)
    max_chunks: int = Field(default=30, ge=0, le=200)
    max_evidence_items: int = Field(default=12, ge=0, le=100)
    max_conflicting_suggestions: int = Field(default=5, ge=0, le=20)
    include_superseded: bool = False
    include_stale: bool = False
    category: str | None = Field(default=None, max_length=80)
    tags_any: list[str] = Field(default_factory=list, max_length=10)
    tags_all: list[str] = Field(default_factory=list, max_length=10)
    tags_none: list[str] = Field(default_factory=list, max_length=10)


class BenchmarkContextRequest(ContextRequest):
    token_budget: int = Field(default=16000, ge=64, le=64000)
    max_facts: int = Field(default=200, ge=0, le=1000)
    max_chunks: int = Field(default=400, ge=0, le=2000)


def context_item_to_response(item: object) -> dict[str, Any]:
    return _LEGACY_CONTEXT_API_RESPONSES.context_item_to_response(item)


def _context_diagnostics_to_response(
    diagnostics: dict[str, Any],
    *,
    items: list[dict[str, Any]],
    top_evidence: list[dict[str, Any]] | None = None,
    answer_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _LEGACY_CONTEXT_API_RESPONSES.context_diagnostics_to_response(
        diagnostics,
        items=items,
        top_evidence=top_evidence,
        answer_support=answer_support,
    )


def _top_evidence_to_response(
    items: list[dict[str, Any]],
    *,
    limit: int = 5,
    include_review_only: bool = False,
    include_stale: bool = False,
) -> list[dict[str, Any]]:
    return _LEGACY_CONTEXT_API_RESPONSES.top_evidence_to_response(
        items,
        limit=limit,
        include_review_only=include_review_only,
        include_stale=include_stale,
    )


def _answer_support_to_response(
    *,
    items: list[dict[str, Any]],
    top_evidence: list[dict[str, Any]],
    diagnostics: dict[str, Any] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    return _LEGACY_CONTEXT_API_RESPONSES.answer_support_to_response(
        items=items,
        top_evidence=top_evidence,
        diagnostics=diagnostics,
        limit=limit,
    )


def _legacy_build_context_query_from_feature_seam(
    request: ContextRequest,
    *,
    scope,
    max_rendered_chars: int,
) -> BuildContextQuery:
    feature_query = _feature_context_query_for_legacy_request(request, scope=scope)
    memory_scope_ids = scope.memory_scope_ids
    if feature_query is not None and len(memory_scope_ids) == 1:
        memory_scope_ids = (feature_query.query.scope.memory_scope_id,)
    space_id = feature_query.query.scope.space_id if feature_query is not None else scope.space_id
    thread_id = (
        feature_query.query.scope.thread_id if feature_query is not None else scope.thread_id
    )
    token_budget = (
        feature_query.budget.max_prompt_tokens
        if feature_query is not None
        else request.token_budget
    )

    return BuildContextQuery(
        space_id=space_id,
        memory_scope_ids=memory_scope_ids,
        thread_id=thread_id,
        query=request.query,
        consistency_mode=request.consistency_mode,
        token_budget=token_budget,
        max_rendered_chars=max_rendered_chars,
        max_facts=request.max_facts,
        max_chunks=request.max_chunks,
        max_evidence_items=request.max_evidence_items,
        max_conflicting_suggestions=request.max_conflicting_suggestions,
        include_superseded=request.include_superseded,
        include_stale=request.include_stale,
        category=_normalize_label(request.category),
        tags_any=_normalize_tags(request.tags_any),
        tags_all=_normalize_tags(request.tags_all),
        tags_none=_normalize_tags(request.tags_none),
    )


def _feature_context_query_for_legacy_request(request: ContextRequest, *, scope):
    if not scope.memory_scope_ids:
        return None

    try:
        return context_building_server.build_context_query_from_contract(
            context_building_server.BuildContextHttpRequest(
                query=request.query,
                space_id=str(scope.space_id),
                memory_scope_id=str(scope.memory_scope_ids[0]),
                thread_id=str(scope.thread_id) if scope.thread_id else None,
                budget=context_building_server.ContextBudgetHttpRequest(
                    max_context_tokens=request.token_budget,
                ),
                tags=request.tags_any,
            ).to_contract()
        )
    except (ValueError, ValidationError):
        return None


@router.post("/context")
async def build_context(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _LEGACY_CONTEXT_API_RESPONSES.empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_context",
        )
        return response
    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _LEGACY_CONTEXT_API_RESPONSES.empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_context",
        )
        return response
    bundle = await container.build_context.execute(
        _legacy_build_context_query_from_feature_seam(
            request,
            scope=scope,
            max_rendered_chars=container.settings.max_context_chars,
        )
    )
    response = _LEGACY_CONTEXT_API_RESPONSES.context_response_from_bundle(
        bundle,
        request_id=request_id,
    )
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response["data"]["diagnostics"],
        request_id=request_id,
        use_case="build_context",
        scope=_trace_scope(scope),
    )
    return response


@router.post("/search")
async def search_memory(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _LEGACY_CONTEXT_API_RESPONSES.empty_search_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            include_answer_support=False,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="search_memory",
        )
        return response
    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _LEGACY_CONTEXT_API_RESPONSES.empty_search_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="search_memory",
        )
        return response
    bundle = await container.build_context.execute(
        _legacy_build_context_query_from_feature_seam(
            request,
            scope=scope,
            max_rendered_chars=container.settings.max_context_chars,
        )
    )
    response = _LEGACY_CONTEXT_API_RESPONSES.search_response_from_bundle(
        bundle,
        request_id=request_id,
    )
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response["data"]["diagnostics"],
        request_id=request_id,
        use_case="search_memory",
        scope=_trace_scope(scope),
    )
    return response


@router.post("/context/benchmark-search", include_in_schema=False)
async def benchmark_search_memory(
    request: BenchmarkContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return await search_memory(request, container)  # type: ignore[arg-type]


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


_LABEL_RE = re.compile(r"[^a-z0-9_-]+")


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _LABEL_RE.sub("_", value.strip().lower()).strip("_-")
    return normalized or None


def _normalize_tags(values: list[str]) -> tuple[str, ...]:
    tags: list[str] = []
    for value in values:
        normalized = _normalize_label(value)
        if normalized and normalized not in tags:
            tags.append(normalized[:48].rstrip("_-"))
    return tuple(tag for tag in tags if tag)


def _trace_scope(scope) -> dict[str, object]:
    return {
        "space_id": str(scope.space_id),
        "memory_scope_ids": tuple(
            str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
        ),
        "thread_id": str(scope.thread_id) if scope.thread_id else None,
    }
