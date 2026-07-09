"""MCP DTOs for context-link tools."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from infinity_context_mcp.domain.models import (
    JsonScalar,
    McpDataModel,
    McpPublicModel,
    McpToolResponse,
)

ContextLinkMetadataValue = JsonScalar | list[JsonScalar] | dict[str, JsonScalar]


class MemoryContextLinkData(McpDataModel):
    id: str | None = None
    space_id: str | None = None
    memory_scope_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    confidence: str | None = None
    reason: str | None = None
    status: str | None = None
    metadata: dict[str, ContextLinkMetadataValue] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class MemoryContextLinkSuggestionData(MemoryContextLinkData):
    score: float | None = None
    reviewed_at: str | None = None
    review_reason: str | None = None


class MemoryContextLinkListData(McpDataModel):
    items: list[MemoryContextLinkData] = Field(default_factory=list)


class MemoryContextLinkSuggestionListData(McpDataModel):
    items: list[MemoryContextLinkSuggestionData] = Field(default_factory=list)


class MemoryContextLinkCandidateData(McpDataModel):
    target_type: str | None = None
    target_id: str | None = None
    label: str | None = None
    preview: str | None = None
    score: float | None = None
    tier: str | None = None
    reasons: list[str] = Field(default_factory=list)
    suggestion_id: str | None = None
    status: str | None = None
    metadata: dict[str, ContextLinkMetadataValue] = Field(default_factory=dict)


class MemorySuggestContextLinksData(McpDataModel):
    candidates: list[MemoryContextLinkCandidateData] = Field(default_factory=list)
    diagnostics: dict[str, ContextLinkMetadataValue] = Field(default_factory=dict)


class MemoryReviewContextLinkSuggestionData(McpDataModel):
    suggestion: MemoryContextLinkSuggestionData | None = None
    link: MemoryContextLinkData | None = None
    duplicate_link: bool | None = None


class MemoryReviewContextLinkBatchItemData(MemoryReviewContextLinkSuggestionData):
    suggestion_id: str | None = None
    action: str | None = None
    status: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class MemoryReviewContextLinksBatchData(McpDataModel):
    applied: int | None = None
    failed: int | None = None
    stopped: bool | None = None
    results: list[MemoryReviewContextLinkBatchItemData] = Field(default_factory=list)


class MemoryContextLinkReviewBatchItemInput(McpPublicModel):
    suggestion_id: str = Field(min_length=1, max_length=160)
    action: Literal["approve", "reject", "expire"]
    reason: str | None = Field(default=None, max_length=320)
    target_type: str | None = Field(default=None, min_length=1, max_length=80)
    target_id: str | None = Field(default=None, min_length=1, max_length=160)
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    confidence: Literal["low", "medium", "high"] | None = None
    link_reason: str | None = Field(default=None, min_length=1, max_length=320)


class MemoryContextLinkListResponse(McpToolResponse):
    data: MemoryContextLinkListData | None = None


class MemoryContextLinkSuggestionListResponse(McpToolResponse):
    data: MemoryContextLinkSuggestionListData | None = None


class MemorySuggestContextLinksResponse(McpToolResponse):
    data: MemorySuggestContextLinksData | None = None


class MemoryReviewContextLinkSuggestionResponse(McpToolResponse):
    data: MemoryReviewContextLinkSuggestionData | None = None


class MemoryReviewContextLinksBatchResponse(McpToolResponse):
    data: MemoryReviewContextLinksBatchData | None = None
