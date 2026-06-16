"""MCP response model for the memory browser read model."""

from __future__ import annotations

from pydantic import Field

from memo_stack_mcp.domain.models import JsonScalar, McpDataModel, McpToolResponse

JsonBrowserLeaf = JsonScalar | list[JsonScalar]
JsonBrowserValue = JsonBrowserLeaf | dict[str, JsonBrowserLeaf] | list[dict[str, JsonBrowserLeaf]]
JsonBrowserObject = dict[str, JsonBrowserValue]


class MemoryBrowserData(McpDataModel):
    generated_at: str | None = None
    memory_scope: JsonBrowserObject | None = None
    facts: list[JsonBrowserObject] = Field(default_factory=list)
    episodes: list[JsonBrowserObject] = Field(default_factory=list)
    documents: list[JsonBrowserObject] = Field(default_factory=list)
    chunks: list[JsonBrowserObject] = Field(default_factory=list)
    extraction_jobs: list[JsonBrowserObject] = Field(default_factory=list)
    threads: list[JsonBrowserObject] = Field(default_factory=list)
    captures: list[JsonBrowserObject] = Field(default_factory=list)
    assets: list[JsonBrowserObject] = Field(default_factory=list)
    anchors: list[JsonBrowserObject] = Field(default_factory=list)
    context_links: list[JsonBrowserObject] = Field(default_factory=list)
    context_link_suggestions: list[JsonBrowserObject] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    diagnostics: JsonBrowserObject = Field(default_factory=dict)


class MemoryBrowserResponse(McpToolResponse):
    data: MemoryBrowserData | None = None
