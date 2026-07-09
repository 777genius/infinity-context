"""Legacy /v1 digest request models owned by the context_building seam."""

from __future__ import annotations

from typing import Literal, Protocol

from infinity_context_core.application import BuildMemoryDigestQuery, ConsistencyMode
from pydantic import BaseModel, ConfigDict, Field


class DigestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    memory_scope_external_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=12000)
    consistency_mode: ConsistencyMode = Field(default=ConsistencyMode.BEST_EFFORT)
    token_budget: int = Field(default=2400, ge=128, le=24000)
    max_facts: int = Field(default=20, ge=0, le=100)
    max_chunks: int = Field(default=20, ge=0, le=200)
    max_suggestions: int = Field(default=10, ge=0, le=100)
    include_pending_suggestions: bool = True
    include_superseded: bool = False
    include_related: bool = True
    format: Literal["markdown", "json"] = "markdown"


class LegacyDigestScope(Protocol):
    space_id: object
    memory_scope_ids: tuple[object, ...]
    thread_id: object | None


def build_legacy_digest_query_from_request(
    request: DigestRequest,
    *,
    scope: LegacyDigestScope,
    max_rendered_chars: int,
) -> BuildMemoryDigestQuery:
    return BuildMemoryDigestQuery(
        space_id=scope.space_id,
        memory_scope_ids=scope.memory_scope_ids,
        thread_id=scope.thread_id,
        topic=request.topic,
        consistency_mode=request.consistency_mode,
        token_budget=request.token_budget,
        max_rendered_chars=max_rendered_chars,
        max_facts=request.max_facts,
        max_chunks=request.max_chunks,
        max_suggestions=request.max_suggestions,
        include_pending_suggestions=request.include_pending_suggestions,
        include_superseded=request.include_superseded,
        include_related=request.include_related,
    )


__all__ = (
    "DigestRequest",
    "build_legacy_digest_query_from_request",
)
