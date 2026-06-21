"""MCP config generation for local agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infinity_context_cli.config import InfinityContextCliConfig

SUPPORTED_AGENTS = {"codex", "claude", "cursor", "gemini", "opencode"}
_SERVICE_TOKEN_ENV_KEY = "MEMORY_SERVICE_TOKEN"


def build_mcp_config(
    *,
    agent: str,
    config: InfinityContextCliConfig,
    include_token: bool = False,
) -> dict[str, Any]:
    if agent not in SUPPORTED_AGENTS:
        raise ValueError(f"Unsupported agent: {agent}")
    command = _mcp_command(config.repo_dir)
    env = {
        "MEMORY_MCP_AGENT_NAME": agent,
        "MEMORY_MCP_API_URL": config.api_url,
        "MEMORY_MCP_DEFAULT_SPACE_SLUG": config.default_space_slug,
        "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": config.default_memory_scope_external_ref,
        "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF": "__INFINITY_CONTEXT_NO_DEFAULT_THREAD__",
        "MEMORY_MCP_WRITE_MODE": "suggest",
        "MEMORY_MCP_DELETE_MODE": "off",
        "MEMORY_MCP_INGEST_MODE": "small_docs",
    }
    if include_token:
        env["MEMORY_MCP_AUTH_TOKEN"] = config.service_token
    else:
        env["MEMORY_MCP_AUTH_TOKEN_FILE"] = str(config.env_path)
    if agent in {"codex", "cursor"}:
        return {"infinity-context": {"command": command, "env": env}}
    return {"mcpServers": {"infinity-context": {"command": command, "env": env}}}


def render_mcp_config(
    *,
    agent: str,
    config: InfinityContextCliConfig,
    include_token: bool = False,
) -> str:
    return json.dumps(
        build_mcp_config(agent=agent, config=config, include_token=include_token),
        indent=2,
        sort_keys=True,
    )


def write_mcp_config(
    *,
    agent: str,
    config: InfinityContextCliConfig,
    include_token: bool = False,
) -> Path:
    if not include_token:
        sync_token_file(config)
    output_dir = config.home / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{agent}-mcp.json"
    path.write_text(
        render_mcp_config(agent=agent, config=config, include_token=include_token) + "\n",
        encoding="utf-8",
    )
    if include_token:
        path.chmod(0o600)
    return path


def sync_token_file(config: InfinityContextCliConfig) -> None:
    config.env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        config.env_path.read_text(encoding="utf-8").splitlines()
        if config.env_path.exists()
        else []
    )
    token_line = f"{_SERVICE_TOKEN_ENV_KEY}={config.service_token}"
    updated = False
    rendered: list[str] = []
    for line in lines:
        if line.startswith(f"{_SERVICE_TOKEN_ENV_KEY}="):
            rendered.append(token_line)
            updated = True
        else:
            rendered.append(line)
    if not updated:
        rendered.insert(0, token_line)
    config.env_path.write_text("\n".join([*rendered, ""]), encoding="utf-8")
    config.env_path.chmod(0o600)


def _mcp_command(repo_dir: Path) -> str:
    plugin_command = (
        repo_dir
        / "plugins"
        / "infinity-context-agent-plugin"
        / "bin"
        / "infinity-context-mcp"
    )
    if plugin_command.exists():
        return str(plugin_command)
    return "infinity-context-mcp"
