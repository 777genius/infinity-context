"""Legacy /v1 context request models owned by the context_building seam."""

from __future__ import annotations

import re
from typing import Protocol

from infinity_context_core.application import BuildContextQuery, ConsistencyMode
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from infinity_context_server.features.context_building.contracts import (
    BuildContextHttpRequest,
    ContextBudgetHttpRequest,
)
from infinity_context_server.features.context_building.mappers import (
    build_context_query_from_contract,
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


class LegacyContextScope(Protocol):
    space_id: object
    memory_scope_ids: tuple[object, ...]
    thread_id: object | None


def build_legacy_context_query_from_request(
    request: ContextRequest,
    *,
    scope: LegacyContextScope,
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


def _feature_context_query_for_legacy_request(
    request: ContextRequest,
    *,
    scope: LegacyContextScope,
):
    if not scope.memory_scope_ids:
        return None

    try:
        return build_context_query_from_contract(
            BuildContextHttpRequest(
                query=request.query,
                space_id=str(scope.space_id),
                memory_scope_id=str(scope.memory_scope_ids[0]),
                thread_id=str(scope.thread_id) if scope.thread_id else None,
                budget=ContextBudgetHttpRequest(
                    max_context_tokens=request.token_budget,
                ),
                tags=request.tags_any,
            ).to_contract()
        )
    except (ValueError, ValidationError):
        return None


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


__all__ = (
    "BenchmarkContextRequest",
    "ContextRequest",
    "build_legacy_context_query_from_request",
)
