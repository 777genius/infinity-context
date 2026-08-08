"""Search and prompt-context API."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from infinity_context_core.application import ContextBundle as LegacyContextBundle
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
    normalize_context_diagnostics,
)
from infinity_context_core.application.context_stage_diagnostics import (
    record_context_stage_duration,
)
from infinity_context_core.domain.errors import MemoryForbiddenError, MemoryValidationError

from infinity_context_server.api.auth import (
    get_authorized_agent_context,
    require_service_token,
)
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_retrieve
from infinity_context_server.api.public_payload import safe_public_metadata, safe_public_text
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_context_scope,
)
from infinity_context_server.api.v1.source_refs import source_ref_to_response
from infinity_context_server.auth_tokens import (
    MEMORY_PERMISSION_ADMIN,
    MEMORY_PERMISSION_READ,
)
from infinity_context_server.composition import Container
from infinity_context_server.context_feature_legacy_bridge import (
    legacy_bundle_from_canonical_facts,
)
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

_RANKED_EVIDENCE_DIAGNOSTIC_KEYS = (
    "ranked_evidence_candidate_count",
    "ranked_evidence_projection_candidate_count",
    "ranked_evidence_selectable_candidate_count",
    "ranked_evidence_eligible_candidate_count",
    "ranked_evidence_returned_count",
    "ranked_evidence_compact_projection_count",
    "ranked_evidence_source_diversity_count",
    "ranked_evidence_budget_drop_count",
    "ranked_evidence_item_budget_drop_count",
    "ranked_evidence_token_budget_drop_count",
    "ranked_evidence_char_budget_drop_count",
    "ranked_evidence_instruction_drop_count",
    "ranked_evidence_unsafe_source_drop_count",
    "ranked_evidence_source_dedupe_drop_count",
    "ranked_evidence_temporal_interval_reservation_count",
    "ranked_evidence_paired_reservation_count",
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
    http_request: Request,
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
    request = _apply_authorized_agent_scope(request, http_request=http_request, scope=scope)
    bundle = await _build_context_bundle(
        request,
        scope=scope,
        container=container,
        bundle_id=request_id,
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
    http_request: Request,
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
    request = _apply_authorized_agent_scope(request, http_request=http_request, scope=scope)
    bundle = await _build_context_bundle(
        request,
        scope=scope,
        container=container,
        bundle_id=request_id,
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
    http_request: Request,
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
            use_case="benchmark_search_memory",
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
            use_case="benchmark_search_memory",
        )
        return response
    request = _apply_authorized_agent_scope(request, http_request=http_request, scope=scope)
    bundle = await _build_context_bundle(
        request,
        scope=scope,
        container=container,
        bundle_id=request_id,
        max_rendered_chars=context_building_server.benchmark_context_char_budget(
            token_budget=request.token_budget,
            deployment_max_context_chars=container.settings.max_context_chars,
        ),
        selection_mode="ranked_evidence",
        selection_item_limit=request.max_evidence_items,
    )
    response = _LEGACY_CONTEXT_API_RESPONSES.search_response_from_bundle(
        bundle,
        request_id=request_id,
    )
    _preserve_ranked_evidence_diagnostics(
        response["data"]["diagnostics"],
        bundle.diagnostics,
    )
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response["data"]["diagnostics"],
        request_id=request_id,
        use_case="benchmark_search_memory",
        scope=_trace_scope(scope),
    )
    return response


def _preserve_ranked_evidence_diagnostics(
    response_diagnostics: dict[str, Any],
    bundle_diagnostics: dict[str, object],
) -> None:
    for key in tuple(response_diagnostics):
        if key.startswith("ranked_evidence_") and key not in (_RANKED_EVIDENCE_DIAGNOSTIC_KEYS):
            response_diagnostics.pop(key)
    response_diagnostics.update(
        {
            key: bundle_diagnostics[key]
            for key in _RANKED_EVIDENCE_DIAGNOSTIC_KEYS
            if key in bundle_diagnostics
        }
    )


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


async def _build_context_bundle(
    request,
    *,
    scope,
    container: Container,
    bundle_id: str,
    max_rendered_chars: int | None = None,
    selection_mode: str = "prompt_context",
    selection_item_limit: int | None = None,
):
    memory_scope_ids = tuple(str(value) for value in scope.memory_scope_ids)
    if request.repository_id is not None and len(memory_scope_ids) == 1:
        unsupported_filters = tuple(
            name
            for name, enabled in (
                ("category", request.category is not None),
                ("tags_any", bool(request.tags_any)),
                ("tags_all", bool(request.tags_all)),
                ("tags_none", bool(request.tags_none)),
                ("include_superseded", request.include_superseded),
                ("include_stale", request.include_stale),
            )
            if enabled
        )
        if unsupported_filters:
            raise MemoryValidationError(
                "Repository-scoped canonical context does not support filters: "
                + ", ".join(unsupported_filters)
            )
        canonical_item_limit = min(
            request.max_facts,
            request.max_evidence_items,
            selection_item_limit if selection_item_limit is not None else request.max_facts,
        )
        if canonical_item_limit <= 0:
            return LegacyContextBundle(
                bundle_id=bundle_id,
                rendered_text="",
                items=(),
                token_estimate=0,
                diagnostics={
                    "context_owner": context_building_server.FEATURE_ID,
                    "canonical_hydration": True,
                    "candidate_count": 0,
                    "repository_isolation_mode": "canonical_facts_only",
                    "non_fact_evidence_status": "deferred_until_repository_scoped",
                    "requested_max_chunks": request.max_chunks,
                    "canonical_chunk_candidate_count": 0,
                },
            )
        feature_request = context_building_server.BuildContextHttpRequest(
            query=request.query,
            space_id=str(scope.space_id),
            memory_scope_id=memory_scope_ids[0],
            thread_id=str(scope.thread_id) if scope.thread_id else None,
            repository_id=request.repository_id,
            code_scope_id=request.code_scope_id,
            as_of=request.as_of,
            budget=context_building_server.ContextBudgetHttpRequest(
                max_context_tokens=request.token_budget,
                max_items=canonical_item_limit,
            ),
            tags=(),
        )
        result = await container.build_canonical_fact_context.execute(
            context_building_server.build_context_query_from_contract(feature_request.to_contract())
        )
        return legacy_bundle_from_canonical_facts(
            result,
            bundle_id=bundle_id,
            memory_scope_id=memory_scope_ids[0],
            requested_max_chunks=request.max_chunks,
            requested_max_evidence_items=request.max_evidence_items,
        )
    return await container.build_context.execute(
        context_building_server.build_legacy_context_query_from_request(
            request,
            scope=scope,
            max_rendered_chars=(
                max_rendered_chars
                if max_rendered_chars is not None
                else container.settings.max_context_chars
            ),
            selection_mode=selection_mode,
            selection_item_limit=selection_item_limit,
        )
    )


def _apply_authorized_agent_scope(request, *, http_request: Request, scope):
    context = get_authorized_agent_context(http_request)
    if context is None:
        return request
    if context.repository_id is not None and len(scope.memory_scope_ids) != 1:
        raise MemoryForbiddenError("Repository-scoped context requires exactly one MemoryScope")
    required_permission = (
        MEMORY_PERMISSION_READ
        if MEMORY_PERMISSION_READ in context.permissions
        else MEMORY_PERMISSION_ADMIN
    )
    try:
        authorized = context.authorize(
            requested_space_id=str(scope.space_id),
            requested_memory_scope_ids=tuple(
                str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
            ),
            required_permission=required_permission,
            requested_repository_id=request.repository_id,
            requested_code_scope_id=request.code_scope_id,
        )
    except PermissionError as exc:
        raise MemoryForbiddenError(str(exc)) from exc
    return request.model_copy(
        update={
            "repository_id": authorized.repository_id,
            "code_scope_id": authorized.code_scope_id,
        }
    )


def _trace_scope(scope) -> dict[str, object]:
    return {
        "space_id": str(scope.space_id),
        "memory_scope_ids": tuple(
            str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
        ),
        "thread_id": str(scope.thread_id) if scope.thread_id else None,
    }
