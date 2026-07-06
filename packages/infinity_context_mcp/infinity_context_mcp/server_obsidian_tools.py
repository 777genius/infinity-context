"""FastMCP Obsidian tool registrations for Infinity Context."""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from infinity_context_mcp.application.obsidian import ObsidianMcpService
from infinity_context_mcp.application.prepare import ObsidianPrepareMcpService
from infinity_context_mcp.domain.obsidian_models import MemoryObsidianResponse
from infinity_context_mcp.domain.prepare_models import MemoryObsidianPrepareResponse
from infinity_context_mcp.server_response import tool_response as _tool_response

ObsidianLayoutVersion = Literal["v1", "v2"]


def register_obsidian_tools(
    mcp: FastMCP,
    obsidian_service: ObsidianMcpService,
    obsidian_prepare_service: ObsidianPrepareMcpService,
) -> None:
    @mcp.tool(
        name="memory_obsidian_prepare",
        title="Prepare Infinity Context Obsidian Vault",
        description=(
            "Run the safe first-use setup flow for a local Infinity Context Obsidian vault. "
            "Dry-run by default. With apply=true it initializes local Infinity Context config, "
            "writes vault "
            "setup/plugin files, checks local backend status, and runs preview only if the API "
            "is already ready. It never starts Docker, launches Obsidian, runs a watcher, or "
            "runs mutating sync."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_obsidian_prepare(
        vault_path: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        obsidian_config_dir: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        root_folder: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        layout_version: Annotated[
            ObsidianLayoutVersion | None,
            Field(default=None),
        ] = None,
        space_slug: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
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
            Field(default=False, description="Actually write setup files after approval."),
        ] = False,
        force: Annotated[
            bool,
            Field(default=False, description="Overwrite local runtime config/env files."),
        ] = False,
        overwrite: Annotated[
            bool,
            Field(default=False, description="Overwrite existing vault guide/plugin files."),
        ] = False,
        install_plugin: Annotated[
            bool,
            Field(default=True, description="Install bundled Obsidian plugin files."),
        ] = True,
        enable_plugin: Annotated[
            bool,
            Field(default=True, description="Enable the bundled Obsidian plugin id."),
        ] = True,
        include_inbox: Annotated[bool, Field(default=True)] = True,
    ) -> Annotated[CallToolResult, MemoryObsidianPrepareResponse]:
        return _tool_response(
            await obsidian_prepare_service.prepare(
                vault_path=vault_path,
                obsidian_config_dir=obsidian_config_dir,
                root_folder=root_folder,
                layout_version=layout_version,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                home=home,
                repo_dir=repo_dir,
                api_url=api_url,
                apply=apply,
                force=force,
                overwrite=overwrite,
                install_plugin=install_plugin,
                enable_plugin=enable_plugin,
                include_inbox=include_inbox,
            ),
            MemoryObsidianPrepareResponse,
        )

    @mcp.tool(
        name="memory_obsidian_status",
        title="Obsidian Vault Status",
        description=(
            "Check Infinity Context Obsidian integration readiness without writing files, starting "
            "servers, launching Obsidian, or running a watcher. Safe to call when the user asks "
            "whether a vault is connected. If disabled, reports the required env gate instead "
            "of touching the filesystem."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_obsidian_status(
        vault_path: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        obsidian_config_dir: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        root_folder: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        layout_version: Annotated[
            ObsidianLayoutVersion | None,
            Field(default=None),
        ] = None,
        space_slug: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        require_plugin: Annotated[
            bool,
            Field(default=False, description="Also verify plugin files/settings."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryObsidianResponse]:
        return _tool_response(
            await obsidian_service.status(
                vault_path=vault_path,
                obsidian_config_dir=obsidian_config_dir,
                root_folder=root_folder,
                layout_version=layout_version,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                require_plugin=require_plugin,
            ),
            MemoryObsidianResponse,
        )

    @mcp.tool(
        name="memory_obsidian_setup",
        title="Set Up Obsidian Vault",
        description=(
            "Plan or apply Infinity Context Obsidian vault setup. Dry-run by default and never "
            "imports or exports memory. Requires MEMORY_MCP_OBSIDIAN_ENABLED=true before it "
            "can inspect or write the vault. Set apply=true only after the user approves the "
            "planned folder and plugin changes."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_obsidian_setup(
        vault_path: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        obsidian_config_dir: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        root_folder: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        layout_version: Annotated[
            ObsidianLayoutVersion | None,
            Field(default=None),
        ] = None,
        space_slug: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        apply: Annotated[
            bool,
            Field(default=False, description="Actually write setup files after approval."),
        ] = False,
        overwrite: Annotated[
            bool,
            Field(default=False, description="Overwrite existing connector guide files."),
        ] = False,
        install_plugin: Annotated[
            bool,
            Field(default=False, description="Also install bundled plugin assets."),
        ] = False,
        enable_plugin: Annotated[
            bool,
            Field(default=False, description="Also add the plugin id to community plugins."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryObsidianResponse]:
        return _tool_response(
            await obsidian_service.setup(
                vault_path=vault_path,
                obsidian_config_dir=obsidian_config_dir,
                root_folder=root_folder,
                layout_version=layout_version,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                apply=apply,
                overwrite=overwrite,
                install_plugin=install_plugin,
                enable_plugin=enable_plugin,
            ),
            MemoryObsidianResponse,
        )

    @mcp.tool(
        name="memory_obsidian_preview",
        title="Preview Obsidian Sync",
        description=(
            "Preview Obsidian vault import/export effects without writing vault files or backend "
            "memory. Requires MEMORY_MCP_OBSIDIAN_ENABLED=true. Use this before any Obsidian "
            "sync action."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_obsidian_preview(
        vault_path: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        obsidian_config_dir: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        root_folder: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        layout_version: Annotated[
            ObsidianLayoutVersion | None,
            Field(default=None),
        ] = None,
        space_slug: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        include_inbox: Annotated[bool, Field(default=True)] = True,
    ) -> Annotated[CallToolResult, MemoryObsidianResponse]:
        return _tool_response(
            await obsidian_service.preview(
                vault_path=vault_path,
                obsidian_config_dir=obsidian_config_dir,
                root_folder=root_folder,
                layout_version=layout_version,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                include_inbox=include_inbox,
            ),
            MemoryObsidianResponse,
        )

    @mcp.tool(
        name="memory_obsidian_sync",
        title="Sync Obsidian Vault",
        description=(
            "Run Obsidian sync only when explicitly requested. With apply=false this behaves "
            "as a preview and does not write. Mutating sync requires both apply=true and "
            "MEMORY_MCP_OBSIDIAN_SYNC_ENABLED=true. It never starts Infinity Context services or "
            "launches Obsidian."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_obsidian_sync(
        vault_path: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=1000),
        ] = None,
        obsidian_config_dir: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        root_folder: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=240),
        ] = None,
        layout_version: Annotated[
            ObsidianLayoutVersion | None,
            Field(default=None),
        ] = None,
        space_slug: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        apply: Annotated[
            bool,
            Field(default=False, description="Actually run a mutating sync after approval."),
        ] = False,
        apply_import: Annotated[
            bool,
            Field(default=False, description="Apply direct managed note imports."),
        ] = False,
        include_inbox: Annotated[bool, Field(default=True)] = True,
    ) -> Annotated[CallToolResult, MemoryObsidianResponse]:
        return _tool_response(
            await obsidian_service.sync(
                vault_path=vault_path,
                obsidian_config_dir=obsidian_config_dir,
                root_folder=root_folder,
                layout_version=layout_version,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                apply=apply,
                apply_import=apply_import,
                include_inbox=include_inbox,
            ),
            MemoryObsidianResponse,
        )
