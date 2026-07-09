"""FastMCP composition root for Infinity Context."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from infinity_context_mcp.adapters.http_gateway import HttpMemoryGateway
from infinity_context_mcp.application.local_runtime import LocalRuntimeMcpService
from infinity_context_mcp.application.obsidian import ObsidianMcpService
from infinity_context_mcp.application.prepare import ObsidianPrepareMcpService
from infinity_context_mcp.application.service import MEMORY_USAGE_GUIDE, MemoryToolService
from infinity_context_mcp.config import McpTransport, MemoryMcpSettings, load_settings
from infinity_context_mcp.server_context_tools import register_memory_context_tools
from infinity_context_mcp.server_fact_tools import register_memory_fact_tools
from infinity_context_mcp.server_hardening import (
    harden_tool_input_schemas,
    install_host_argument_sanitizers,
)
from infinity_context_mcp.server_local_runtime_tools import register_local_runtime_tools
from infinity_context_mcp.server_obsidian_tools import register_obsidian_tools
from infinity_context_mcp.server_query_tools import (
    register_memory_query_tools,
    register_memory_status_tool,
)
from infinity_context_mcp.server_request_mapping import (
    CaptureConsolidationStatus,
    CaptureStatus,
    ConfidenceValue,
    ContextLinkReviewAction,
    ContextLinkStatus,
    ContextLinkSuggestionStatus,
    FactRelationStatus,
    FactRelationType,
    FactStatus,
    MemoryBrowserAnchorStatus,
    MemoryBrowserAssetStatus,
    MemoryBrowserChunkStatus,
    MemoryBrowserDocumentStatus,
    MemoryBrowserEpisodeStatus,
    MemoryBrowserExtractionStatus,
    MemoryBrowserThreadStatus,
    MemoryClassification,
    MemoryKind,
    MemoryScopeSnapshotMergeStrategy,
    ReviewAction,
    SourceType,
    SuggestionOperation,
    SuggestionStatus,
)
from infinity_context_mcp.server_resources import register_memory_resources_and_prompts

__all__ = [
    "CaptureConsolidationStatus",
    "CaptureStatus",
    "ConfidenceValue",
    "ContextLinkReviewAction",
    "ContextLinkStatus",
    "ContextLinkSuggestionStatus",
    "FactRelationStatus",
    "FactRelationType",
    "FactStatus",
    "MemoryBrowserAnchorStatus",
    "MemoryBrowserAssetStatus",
    "MemoryBrowserChunkStatus",
    "MemoryBrowserDocumentStatus",
    "MemoryBrowserEpisodeStatus",
    "MemoryBrowserExtractionStatus",
    "MemoryBrowserThreadStatus",
    "MemoryClassification",
    "MemoryKind",
    "MemoryScopeSnapshotMergeStrategy",
    "ReviewAction",
    "SourceType",
    "SuggestionOperation",
    "SuggestionStatus",
    "create_mcp_server",
    "create_service",
    "main",
]


def create_service(settings: MemoryMcpSettings | None = None) -> MemoryToolService:
    resolved = settings or load_settings()
    gateway = HttpMemoryGateway(
        base_url=resolved.api_url,
        auth_token=resolved.auth_token,
        timeout_seconds=resolved.request_timeout_seconds,
    )
    return MemoryToolService(gateway=gateway, settings=resolved)


def create_mcp_server(
    *,
    service: MemoryToolService | None = None,
    settings: MemoryMcpSettings | None = None,
) -> FastMCP:
    resolved_settings = settings or load_settings()
    tool_service = service or create_service(resolved_settings)
    local_runtime_service = LocalRuntimeMcpService(settings=resolved_settings)
    obsidian_service = ObsidianMcpService(settings=resolved_settings)
    obsidian_prepare_service = ObsidianPrepareMcpService(
        local_runtime=local_runtime_service,
        obsidian=obsidian_service,
    )
    mcp = FastMCP("Infinity Context", instructions=MEMORY_USAGE_GUIDE)

    register_memory_status_tool(mcp, tool_service)
    register_local_runtime_tools(mcp, local_runtime_service)
    register_obsidian_tools(mcp, obsidian_service, obsidian_prepare_service)
    register_memory_query_tools(mcp, tool_service)
    register_memory_fact_tools(mcp, tool_service)
    register_memory_context_tools(mcp, tool_service)
    register_memory_resources_and_prompts(mcp, tool_service)

    harden_tool_input_schemas(mcp)
    install_host_argument_sanitizers(mcp)
    return mcp


def main() -> None:
    settings = load_settings()
    server = create_mcp_server(settings=settings)
    server.run(transport=_transport(settings))


def _transport(settings: MemoryMcpSettings) -> str:
    if settings.transport == McpTransport.STREAMABLE_HTTP:
        return "streamable-http"
    return "stdio"


if __name__ == "__main__":
    main()
