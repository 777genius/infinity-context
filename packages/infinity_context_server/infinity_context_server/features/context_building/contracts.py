"""HTTP request models for the context_building server feature."""

from __future__ import annotations

from typing import Any

from infinity_context_contracts.features.context_building import (
    BuildContextRequestDto,
    ContextBudgetDto,
)
from pydantic import BaseModel, ConfigDict, Field


class ContextBudgetHttpRequest(BaseModel):
    """HTTP shape for a prompt context budget."""

    model_config = ConfigDict(extra="forbid")

    max_context_tokens: int = Field(default=1800, ge=1, le=64000)
    reserved_response_tokens: int = Field(default=0, ge=0, le=64000)
    max_items: int | None = Field(default=None, ge=1, le=1000)
    strategy: str = Field(default="balanced", min_length=1, max_length=80)

    def to_contract(self) -> ContextBudgetDto:
        return ContextBudgetDto(
            max_context_tokens=self.max_context_tokens,
            reserved_response_tokens=self.reserved_response_tokens,
            max_items=self.max_items,
            strategy=self.strategy,
        )


class BuildContextHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned context route seam."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=12000)
    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    budget: ContextBudgetHttpRequest | None = None
    include_kinds: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    policy_mode: str | None = Field(default=None, min_length=1, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> BuildContextRequestDto:
        return BuildContextRequestDto(
            query=self.query,
            space_id=self.space_id,
            memory_scope_id=self.memory_scope_id,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            memory_scope_external_ref=self.memory_scope_external_ref,
            thread_external_ref=self.thread_external_ref,
            budget=self.budget.to_contract() if self.budget is not None else None,
            include_kinds=tuple(self.include_kinds),
            tags=tuple(self.tags),
            policy_mode=self.policy_mode,
            metadata=self.metadata,
        )


__all__ = (
    "BuildContextHttpRequest",
    "ContextBudgetHttpRequest",
)
