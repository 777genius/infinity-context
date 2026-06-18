"""Search and prompt-context API."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from memo_stack_core.application import BuildContextQuery, ConsistencyMode
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import should_retrieve
from memo_stack_server.api.v1.scope_resolution import (
    resolve_existing_context_scope,
)
from memo_stack_server.api.v1.source_refs import source_ref_to_response
from memo_stack_server.composition import Container

router = APIRouter(tags=["context"], dependencies=[Depends(require_service_token)])

_MAX_PUBLIC_CONTEXT_SOURCE_REFS = 20


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
    max_conflicting_suggestions: int = Field(default=5, ge=0, le=20)
    include_superseded: bool = False
    include_stale: bool = False
    category: str | None = Field(default=None, max_length=80)
    tags_any: list[str] = Field(default_factory=list, max_length=10)
    tags_all: list[str] = Field(default_factory=list, max_length=10)
    tags_none: list[str] = Field(default_factory=list, max_length=10)


def context_item_to_response(item) -> dict[str, Any]:
    diagnostics = dict(item.diagnostics or {})
    source_refs = tuple(item.source_refs)
    public_source_refs = source_refs[:_MAX_PUBLIC_CONTEXT_SOURCE_REFS]
    if len(source_refs) > len(public_source_refs):
        diagnostics["source_refs_total"] = len(source_refs)
        diagnostics["source_refs_returned"] = len(public_source_refs)
        diagnostics["source_refs_truncated"] = True
    return {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "memory_scope_id": diagnostics.get("memory_scope_id"),
        "text": item.text,
        "score": item.score,
        "source_refs": [source_ref_to_response(ref) for ref in public_source_refs],
        "is_instruction": item.is_instruction,
        "diagnostics": diagnostics,
    }


@router.post("/context")
async def build_context(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
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
        response = _empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
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
        BuildContextQuery(
            space_id=scope.space_id,
            memory_scope_ids=scope.memory_scope_ids,
            thread_id=scope.thread_id,
            query=request.query,
            consistency_mode=request.consistency_mode,
            token_budget=request.token_budget,
            max_rendered_chars=container.settings.max_context_chars,
            max_facts=request.max_facts,
            max_chunks=request.max_chunks,
            max_conflicting_suggestions=request.max_conflicting_suggestions,
            include_superseded=request.include_superseded,
            include_stale=request.include_stale,
            category=_normalize_label(request.category),
            tags_any=_normalize_tags(request.tags_any),
            tags_all=_normalize_tags(request.tags_all),
            tags_none=_normalize_tags(request.tags_none),
        )
    )
    response = {
        "meta": {"request_id": request_id},
        "data": {
            "bundle_id": bundle.bundle_id,
            "rendered_text": bundle.rendered_text,
            "items": [context_item_to_response(item) for item in bundle.items],
            "diagnostics": bundle.diagnostics,
        },
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=bundle.diagnostics,
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
        response = {
            "meta": {"request_id": request_id},
            "data": {
                "items": [],
                "next_cursor": None,
                "diagnostics": {
                    "policy_mode": container.settings.policy_mode.value,
                    "retrieval_disabled": True,
                },
            },
        }
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
        response = _empty_search_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
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
        BuildContextQuery(
            space_id=scope.space_id,
            memory_scope_ids=scope.memory_scope_ids,
            thread_id=scope.thread_id,
            query=request.query,
            consistency_mode=request.consistency_mode,
            token_budget=request.token_budget,
            max_rendered_chars=container.settings.max_context_chars,
            max_facts=request.max_facts,
            max_chunks=request.max_chunks,
            max_conflicting_suggestions=request.max_conflicting_suggestions,
            include_superseded=request.include_superseded,
            include_stale=request.include_stale,
            category=_normalize_label(request.category),
            tags_any=_normalize_tags(request.tags_any),
            tags_all=_normalize_tags(request.tags_all),
            tags_none=_normalize_tags(request.tags_none),
        )
    )
    response = {
        "meta": {"request_id": request_id},
        "data": {
            "items": [context_item_to_response(item) for item in bundle.items],
            "next_cursor": None,
            "diagnostics": bundle.diagnostics,
        },
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=bundle.diagnostics,
        request_id=request_id,
        use_case="search_memory",
        scope=_trace_scope(scope),
    )
    return response


def _empty_context_response(
    *,
    policy_mode: str,
    request_id: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    diagnostics: dict[str, object] = {
        "policy_mode": policy_mode,
        "retrieval_disabled": True,
    }
    if scope_not_found:
        diagnostics = {
            "policy_mode": policy_mode,
            "scope_not_found": True,
            "retrieval_disabled": False,
        }
    return {
        "meta": {"request_id": request_id},
        "data": {
            "bundle_id": "ctx_disabled",
            "rendered_text": "",
            "items": [],
            "diagnostics": diagnostics,
        },
    }


def _empty_search_response(
    *,
    policy_mode: str,
    request_id: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    diagnostics: dict[str, object] = {
        "policy_mode": policy_mode,
        "retrieval_disabled": True,
    }
    if scope_not_found:
        diagnostics = {
            "policy_mode": policy_mode,
            "scope_not_found": True,
            "retrieval_disabled": False,
        }
    return {
        "meta": {"request_id": request_id},
        "data": {
            "items": [],
            "next_cursor": None,
            "diagnostics": diagnostics,
        },
    }


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
