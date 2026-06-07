"""Memory management insights API."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from memo_stack_core.application import (
    BuildMemoryInsightsQuery,
    MemoryActivityItem,
    MemoryConsolidationPlanItem,
    MemoryInsightActionItem,
    MemoryInsightsResult,
)
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import should_retrieve
from memo_stack_server.api.v1.scope_resolution import resolve_existing_context_scope
from memo_stack_server.composition import Container

router = APIRouter(tags=["insights"], dependencies=[Depends(require_service_token)])


class InsightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    profile_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    profile_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    profile_external_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    max_facts: int = Field(default=200, ge=0, le=1000)
    max_documents: int = Field(default=100, ge=0, le=500)
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
        response = _empty_insights_response(
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
        profile_ids=request.profile_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        profile_external_ref=request.profile_external_ref,
        profile_external_refs=request.profile_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _empty_insights_response(
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
            profile_ids=scope.profile_ids,
            thread_id=scope.thread_id,
            max_facts=request.max_facts,
            max_documents=request.max_documents,
            max_suggestions=request.max_suggestions,
            max_captures=request.max_captures,
            max_activity=request.max_activity,
        )
    )
    response = {
        "meta": {"request_id": request_id},
        "data": insights_to_response(insights),
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=insights.diagnostics,
        request_id=request_id,
        use_case="build_insights",
        scope=insights.scope,
    )
    return response


def insights_to_response(insights: MemoryInsightsResult) -> dict[str, Any]:
    return {
        "insights_id": insights.insights_id,
        "generated_at": insights.generated_at.isoformat(),
        "scope": insights.scope,
        "health_score": insights.health_score,
        "metrics": insights.metrics,
        "taxonomy": insights.taxonomy,
        "action_items": [_action_item_to_response(item) for item in insights.action_items],
        "recent_activity": [_activity_item_to_response(item) for item in insights.recent_activity],
        "consolidation_plan": [
            _consolidation_plan_item_to_response(item) for item in insights.consolidation_plan
        ],
        "diagnostics": insights.diagnostics,
    }


def _action_item_to_response(item: MemoryInsightActionItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "severity": item.severity,
        "action": item.action,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "profile_id": item.profile_id,
        "reason": item.reason,
        "preview": item.preview,
        "metadata": item.metadata or {},
    }


def _activity_item_to_response(item: MemoryActivityItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "occurred_at": item.occurred_at.isoformat(),
        "event_type": item.event_type,
        "entity_type": item.entity_type,
        "entity_id": item.entity_id,
        "profile_id": item.profile_id,
        "thread_id": item.thread_id,
        "status": item.status,
        "preview": item.preview,
        "metadata": item.metadata or {},
    }


def _consolidation_plan_item_to_response(item: MemoryConsolidationPlanItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "plan_type": item.plan_type,
        "profile_id": item.profile_id,
        "confidence": item.confidence,
        "canonical_candidate_id": item.canonical_candidate_id,
        "candidate_fact_ids": list(item.candidate_fact_ids),
        "recommended_steps": list(item.recommended_steps),
        "reason": item.reason,
        "preview": item.preview,
        "metadata": item.metadata or {},
    }


def _empty_insights_response(
    *,
    request_id: str,
    policy_mode: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    diagnostics: dict[str, object] = {
        "policy_mode": policy_mode,
        "retrieval_disabled": True,
        "evidence_only": True,
        "read_only": True,
    }
    if scope_not_found:
        diagnostics = {
            "policy_mode": policy_mode,
            "scope_not_found": True,
            "retrieval_disabled": False,
            "evidence_only": True,
            "read_only": True,
        }
    return {
        "meta": {"request_id": request_id},
        "data": {
            "insights_id": "ins_disabled" if not scope_not_found else "ins_scope_not_found",
            "generated_at": None,
            "scope": {},
            "health_score": 0.0,
            "metrics": {},
            "taxonomy": {},
            "action_items": [],
            "recent_activity": [],
            "consolidation_plan": [],
            "diagnostics": diagnostics,
        },
    }


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
