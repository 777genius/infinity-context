"""Memory management insights API."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application import BuildMemoryInsightsQuery
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_retrieve
from infinity_context_server.api.public_payload import safe_public_metadata
from infinity_context_server.api.v1.scope_resolution import resolve_existing_context_scope
from infinity_context_server.composition import Container
from infinity_context_server.features.context_building import public as context_building_server

router = APIRouter(tags=["insights"], dependencies=[Depends(require_service_token)])

_LEGACY_MEMORY_INSIGHTS_API_RESPONSES = (
    context_building_server.LegacyMemoryInsightsApiResponseMapper(
        safe_public_metadata=safe_public_metadata,
    )
)


class InsightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    memory_scope_external_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    max_facts: int = Field(default=200, ge=0, le=1000)
    max_documents: int = Field(default=100, ge=0, le=500)
    max_episodes: int = Field(default=100, ge=0, le=500)
    max_suggestions: int = Field(default=100, ge=0, le=500)
    max_captures: int = Field(default=100, ge=0, le=500)
    max_activity: int = Field(default=50, ge=0, le=100)


@router.post("/insights")
async def build_insights(
    request: InsightsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _LEGACY_MEMORY_INSIGHTS_API_RESPONSES.empty_insights_response(
            request_id=request_id,
            policy_mode=container.settings.policy_mode.value,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_insights",
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
        response = _LEGACY_MEMORY_INSIGHTS_API_RESPONSES.empty_insights_response(
            request_id=request_id,
            policy_mode=container.settings.policy_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_insights",
        )
        return response

    insights = await container.build_memory_insights.execute(
        BuildMemoryInsightsQuery(
            space_id=scope.space_id,
            memory_scope_ids=scope.memory_scope_ids,
            thread_id=scope.thread_id,
            max_facts=request.max_facts,
            max_documents=request.max_documents,
            max_episodes=request.max_episodes,
            max_suggestions=request.max_suggestions,
            max_captures=request.max_captures,
            max_activity=request.max_activity,
        )
    )
    response = _LEGACY_MEMORY_INSIGHTS_API_RESPONSES.insights_response_from_result(
        insights,
        request_id=request_id,
    )
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=insights.diagnostics,
        request_id=request_id,
        use_case="build_insights",
        scope=insights.scope,
    )
    return response


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
