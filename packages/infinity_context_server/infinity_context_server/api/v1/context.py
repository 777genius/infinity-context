"""Search and prompt-context API."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
    normalize_context_diagnostics,
)
from infinity_context_core.application.context_stage_diagnostics import (
    record_context_stage_duration,
)

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

ContextRequest = context_building_server.ContextRequest
BenchmarkContextRequest = context_building_server.BenchmarkContextRequest

_LEGACY_CONTEXT_API_RESPONSES = context_building_server.LegacyContextApiResponseMapper(
    normalize_context_diagnostics=normalize_context_diagnostics,
    normalize_context_bundle_diagnostics=normalize_context_bundle_diagnostics,
    safe_public_metadata=safe_public_metadata,
    safe_public_text=safe_public_text,
    source_ref_to_response=source_ref_to_response,
)


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


@router.post("/context")
async def build_context(
    request: context_building_server.ContextRequest,
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
    scope_started = perf_counter()
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
    scope_resolution_ms = _elapsed_ms(scope_started)
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
        context_building_server.build_legacy_context_query_from_request(
            request,
            scope=scope,
            max_rendered_chars=container.settings.max_context_chars,
        )
    )
    record_context_stage_duration(
        bundle.diagnostics,
        stage="scope_resolution",
        duration_ms=scope_resolution_ms,
    )
    response_mapping_started = perf_counter()
    response = _LEGACY_CONTEXT_API_RESPONSES.context_response_from_bundle(
        bundle,
        request_id=request_id,
    )
    response_diagnostics = response["data"]["diagnostics"]
    record_context_stage_duration(
        response_diagnostics,
        stage="response_mapping",
        duration_ms=_elapsed_ms(response_mapping_started),
    )
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response_diagnostics,
        request_id=request_id,
        use_case="build_context",
        scope=_trace_scope(scope),
    )
    record_context_stage_duration(
        response_diagnostics,
        stage="total",
        duration_ms=_elapsed_ms(started),
    )
    return response


@router.post("/search")
async def search_memory(
    request: context_building_server.ContextRequest,
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
        context_building_server.build_legacy_context_query_from_request(
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
    request: context_building_server.BenchmarkContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return await search_memory(request, container)  # type: ignore[arg-type]


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def _trace_scope(scope) -> dict[str, object]:
    return {
        "space_id": str(scope.space_id),
        "memory_scope_ids": tuple(
            str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
        ),
        "thread_id": str(scope.thread_id) if scope.thread_id else None,
    }
