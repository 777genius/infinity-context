"""FastMCP local runtime tool registrations."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from infinity_context_mcp.application.local_runtime import LocalRuntimeMcpService
from infinity_context_mcp.domain.local_runtime_models import MemoryLocalRuntimeResponse
from infinity_context_mcp.server_response import tool_response as _tool_response

RuntimeComposeProfile = Literal["lite", "full"]


def register_local_runtime_tools(
    mcp: FastMCP,
    local_runtime_service: LocalRuntimeMcpService,
) -> None:
    @mcp.tool(
        name="memory_local_runtime_status",
        title="Local Infinity Context Runtime Status",
        description=(
            "Check local Infinity Context runtime configuration and API reachability without "
            "writing files, starting Docker, or launching Obsidian. If disabled, reports the "
            "required "
            "env gate instead of touching the filesystem."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_local_runtime_status(
        home: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
    ) -> Annotated[CallToolResult, MemoryLocalRuntimeResponse]:
        return _tool_response(
            await local_runtime_service.status(home=home),
            MemoryLocalRuntimeResponse,
        )

    @mcp.tool(
        name="memory_local_runtime_init",
        title="Initialize Local Infinity Context Runtime",
        description=(
            "Plan or apply local Infinity Context config initialization. Dry-run by default and "
            "never starts services. Requires MEMORY_MCP_LOCAL_RUNTIME_ENABLED=true before it can "
            "write "
            "the local config or env file. The service token is never returned."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_local_runtime_init(
        home: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        repo_dir: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        api_url: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        apply: Annotated[
            bool,
            Field(default=False, description="Actually write local config files after approval."),
        ] = False,
        force: Annotated[
            bool,
            Field(default=False, description="Overwrite existing local config and env files."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryLocalRuntimeResponse]:
        return _tool_response(
            await local_runtime_service.init(
                home=home,
                repo_dir=repo_dir,
                api_url=api_url,
                apply=apply,
                force=force,
            ),
            MemoryLocalRuntimeResponse,
        )

    @mcp.tool(
        name="memory_local_runtime_doctor",
        title="Diagnose Local Infinity Context Runtime",
        description=(
            "Run local Infinity Context diagnostics without writing files or starting services. "
            "Checks "
            "repo root, Docker availability, service token configuration, and API endpoints."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_local_runtime_doctor(
        home: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
    ) -> Annotated[CallToolResult, MemoryLocalRuntimeResponse]:
        return _tool_response(
            await local_runtime_service.doctor(home=home),
            MemoryLocalRuntimeResponse,
        )

    @mcp.tool(
        name="memory_local_runtime_start",
        title="Start Local Infinity Context Runtime",
        description=(
            "Plan or start the local Infinity Context Docker runtime. With apply=false this only "
            "returns the docker compose command. Mutating start requires both apply=true and "
            "MEMORY_MCP_LOCAL_RUNTIME_START_ENABLED=true. It never launches Obsidian."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_local_runtime_start(
        compose_profile: Annotated[
            RuntimeComposeProfile,
            Field(default="lite", description="Runtime compose profile to start."),
        ] = "lite",
        home: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        apply: Annotated[
            bool,
            Field(default=False, description="Actually run docker compose up after approval."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryLocalRuntimeResponse]:
        return _tool_response(
            await local_runtime_service.start(
                compose_profile=compose_profile,
                home=home,
                apply=apply,
            ),
            MemoryLocalRuntimeResponse,
        )
