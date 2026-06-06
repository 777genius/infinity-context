"""Configuration for the Memo Stack MCP adapter."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from memo_stack_mcp.domain.policy import (
    MemoryMcpDeleteMode,
    MemoryMcpIngestMode,
    MemoryMcpWriteMode,
)


class McpTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"


@dataclass(frozen=True)
class MemoryMcpSettings:
    api_url: str = "http://127.0.0.1:7788"
    auth_token: str | None = None
    default_space_slug: str = "default"
    default_profile_external_ref: str = "default"
    default_thread_external_ref: str | None = None
    agent_name: str = "mcp-agent"
    source_type: str = "ai_response"
    request_timeout_seconds: float = 10.0
    max_tool_text_chars: int = 20_000
    min_token_budget: int = 256
    max_token_budget: int = 6_000
    max_search_items: int = 50
    allow_writes: bool = True
    allow_deletes: bool = True
    write_mode: MemoryMcpWriteMode = MemoryMcpWriteMode.SUGGEST
    delete_mode: MemoryMcpDeleteMode = MemoryMcpDeleteMode.OFF
    ingest_mode: MemoryMcpIngestMode = MemoryMcpIngestMode.SMALL_DOCS
    small_doc_max_chars: int = 50_000
    transport: McpTransport = McpTransport.STDIO

    def __post_init__(self) -> None:
        if self.max_token_budget < self.min_token_budget:
            raise ValueError("max_token_budget must be >= min_token_budget")

    @property
    def sanitized_api_url(self) -> str:
        return self.api_url.rstrip("/")

    @property
    def writes_enabled(self) -> bool:
        return self.allow_writes and self.write_mode != MemoryMcpWriteMode.OFF

    @property
    def deletes_enabled(self) -> bool:
        return self.allow_deletes and self.delete_mode != MemoryMcpDeleteMode.OFF

    @property
    def ingest_enabled(self) -> bool:
        return self.writes_enabled and self.ingest_mode != MemoryMcpIngestMode.OFF


def load_settings(env: Mapping[str, str] | None = None) -> MemoryMcpSettings:
    values = env or os.environ
    token = _get(values, "MEMORY_MCP_AUTH_TOKEN") or _get(values, "MEMORY_SERVICE_TOKEN")
    write_mode = _write_mode(values)
    delete_mode = _delete_mode(values)
    return MemoryMcpSettings(
        api_url=_get(values, "MEMORY_MCP_API_URL", "http://127.0.0.1:7788").rstrip("/"),
        auth_token=token,
        default_space_slug=_get(values, "MEMORY_MCP_DEFAULT_SPACE_SLUG", "default"),
        default_profile_external_ref=_get(
            values, "MEMORY_MCP_DEFAULT_PROFILE_EXTERNAL_REF", "default"
        ),
        default_thread_external_ref=_empty_to_none(
            _get(values, "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF")
        ),
        agent_name=_get(values, "MEMORY_MCP_AGENT_NAME", "mcp-agent"),
        source_type=_get(values, "MEMORY_MCP_SOURCE_TYPE", "ai_response"),
        request_timeout_seconds=_positive_float(
            _get(values, "MEMORY_MCP_REQUEST_TIMEOUT_SECONDS", "10"),
            "MEMORY_MCP_REQUEST_TIMEOUT_SECONDS",
        ),
        max_tool_text_chars=_positive_int(
            _get(values, "MEMORY_MCP_MAX_TOOL_TEXT_CHARS", "20000"),
            "MEMORY_MCP_MAX_TOOL_TEXT_CHARS",
        ),
        min_token_budget=_positive_int(
            _get(values, "MEMORY_MCP_MIN_TOKEN_BUDGET", "256"),
            "MEMORY_MCP_MIN_TOKEN_BUDGET",
        ),
        max_token_budget=_positive_int(
            _get(values, "MEMORY_MCP_MAX_TOKEN_BUDGET", "6000"),
            "MEMORY_MCP_MAX_TOKEN_BUDGET",
        ),
        max_search_items=_positive_int(
            _get(values, "MEMORY_MCP_MAX_SEARCH_ITEMS", "50"),
            "MEMORY_MCP_MAX_SEARCH_ITEMS",
        ),
        write_mode=write_mode,
        delete_mode=delete_mode,
        ingest_mode=MemoryMcpIngestMode(
            _get(values, "MEMORY_MCP_INGEST_MODE", MemoryMcpIngestMode.SMALL_DOCS.value)
        ),
        small_doc_max_chars=_positive_int(
            _get(values, "MEMORY_MCP_SMALL_DOC_MAX_CHARS", "50000"),
            "MEMORY_MCP_SMALL_DOC_MAX_CHARS",
        ),
        transport=McpTransport(_get(values, "MEMORY_MCP_TRANSPORT", McpTransport.STDIO.value)),
    )


def _get(values: Mapping[str, str], key: str, default: str | None = None) -> str:
    value = values.get(key)
    if value is None:
        return "" if default is None else default
    return value.strip()


def _empty_to_none(value: str) -> str | None:
    return value or None


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _write_mode(values: Mapping[str, str]) -> MemoryMcpWriteMode:
    value = _get(values, "MEMORY_MCP_WRITE_MODE", MemoryMcpWriteMode.SUGGEST.value)
    return MemoryMcpWriteMode(value)


def _delete_mode(values: Mapping[str, str]) -> MemoryMcpDeleteMode:
    value = _get(values, "MEMORY_MCP_DELETE_MODE", MemoryMcpDeleteMode.OFF.value)
    return MemoryMcpDeleteMode(value)
