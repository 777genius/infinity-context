"""Validated runtime settings for agent lifecycle hooks."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from infinity_context_mcp.workspace_binding import HookProjectScopeMode

NO_DEFAULT_THREAD_SENTINEL = "__INFINITY_CONTEXT_NO_DEFAULT_THREAD__"
NO_DEFAULT_THREAD_SENTINELS = frozenset({NO_DEFAULT_THREAD_SENTINEL})


class HookCaptureMode(StrEnum):
    OFF = "off"
    EPISODES = "episodes"
    CAPTURES = "captures"


class HookMemoryMode(StrEnum):
    OFF = "off"
    RETRIEVE_ONLY = "retrieve_only"
    CAPTURE_ONLY = "capture_only"
    SUGGEST = "suggest"
    AUTO_APPLY_SAFE = "auto_apply_safe"


@dataclass(frozen=True)
class HookSettings:
    api_url: str
    auth_token: str | None
    default_space_slug: str
    default_memory_scope_external_ref: str
    default_thread_external_ref: str | None
    agent_name: str
    enabled: bool
    fail_closed: bool
    request_timeout_seconds: float
    token_budget: int
    max_facts: int
    max_chunks: int
    max_input_chars: int
    max_output_chars: int
    context_events: frozenset[str]
    ingest_events: frozenset[str]
    capture_mode: HookCaptureMode
    source_type: str
    transcript_tail_mode: str
    transcript_tail_max_chars: int
    verbose: bool
    project_scope_mode: HookProjectScopeMode
    project_repository_id: str | None
    project_bindings_file: str | None
    project_git_remote: str | None

    def __post_init__(self) -> None:
        if (
            self.project_scope_mode is HookProjectScopeMode.AUTO_LOCKED
            and self.capture_mode is HookCaptureMode.EPISODES
        ):
            raise ValueError(
                "AUTO_LOCKED project scope requires repository-aware captures; "
                "episode capture is not supported"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> HookSettings:
        values = os.environ if env is None else env
        file_values = _env_file_values(_get(values, "MEMORY_MCP_AUTH_TOKEN_FILE"))

        def setting(
            key: str,
            default: str | None = None,
            *,
            allow_empty: bool = False,
        ) -> str:
            direct = _get(values, key)
            if direct or (allow_empty and key in values):
                return direct
            file_value = file_values.get(key, "").strip()
            if file_value or (allow_empty and key in file_values):
                return file_value
            return "" if default is None else default

        auto_memory_mode = setting("MEMORY_AUTO_MEMORY_MODE")
        memory_mode = _hook_memory_mode(
            auto_memory_mode or setting("MEMORY_CAPTURE_MODE", "retrieve_only"),
            name=("MEMORY_AUTO_MEMORY_MODE" if auto_memory_mode else "MEMORY_CAPTURE_MODE"),
        )
        return cls(
            api_url=setting("MEMORY_MCP_API_URL", "http://127.0.0.1:7788").rstrip("/"),
            auth_token=setting("MEMORY_MCP_AUTH_TOKEN") or setting("MEMORY_SERVICE_TOKEN") or None,
            default_space_slug=setting("MEMORY_MCP_DEFAULT_SPACE_SLUG", "default"),
            default_memory_scope_external_ref=setting(
                "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF", "default"
            ),
            default_thread_external_ref=_thread_ref(
                setting("MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF")
            ),
            agent_name=setting("MEMORY_MCP_AGENT_NAME", "agent"),
            enabled=_bool(setting("MEMORY_PLUGIN_HOOKS_ENABLED", "true")),
            fail_closed=_bool(setting("MEMORY_PLUGIN_HOOK_FAIL_CLOSED", "false")),
            request_timeout_seconds=_positive_float(
                setting("MEMORY_PLUGIN_HOOK_TIMEOUT_SECONDS", "5"),
                "MEMORY_PLUGIN_HOOK_TIMEOUT_SECONDS",
            ),
            token_budget=_positive_int(
                setting("MEMORY_PLUGIN_HOOK_TOKEN_BUDGET", "1800"),
                "MEMORY_PLUGIN_HOOK_TOKEN_BUDGET",
            ),
            max_facts=_non_negative_int(
                setting("MEMORY_PLUGIN_HOOK_MAX_FACTS", "12"),
                "MEMORY_PLUGIN_HOOK_MAX_FACTS",
            ),
            max_chunks=_non_negative_int(
                setting("MEMORY_PLUGIN_HOOK_MAX_CHUNKS", "8"),
                "MEMORY_PLUGIN_HOOK_MAX_CHUNKS",
            ),
            max_input_chars=_positive_int(
                setting("MEMORY_PLUGIN_HOOK_MAX_INPUT_CHARS", "12000"),
                "MEMORY_PLUGIN_HOOK_MAX_INPUT_CHARS",
            ),
            max_output_chars=_positive_int(
                setting("MEMORY_PLUGIN_HOOK_MAX_OUTPUT_CHARS", "6000"),
                "MEMORY_PLUGIN_HOOK_MAX_OUTPUT_CHARS",
            ),
            context_events=frozenset(
                _csv(
                    setting(
                        "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS",
                        "SessionStart,UserPromptSubmit,BeforeAgent",
                        allow_empty=True,
                    )
                )
            ),
            ingest_events=frozenset(_csv(setting("MEMORY_PLUGIN_HOOK_INGEST_EVENTS"))),
            capture_mode=_hook_capture_mode(
                explicit_value=setting("MEMORY_PLUGIN_HOOK_CAPTURE_MODE"),
                memory_mode=memory_mode,
            ),
            source_type=setting("MEMORY_PLUGIN_HOOK_SOURCE_TYPE", "agent_hook"),
            transcript_tail_mode=_transcript_tail_mode(
                setting("MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MODE", "off")
            ),
            transcript_tail_max_chars=_positive_int(
                setting("MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MAX_CHARS", "4000"),
                "MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MAX_CHARS",
            ),
            verbose=_bool(setting("MEMORY_PLUGIN_HOOK_VERBOSE", "false")),
            project_scope_mode=_project_scope_mode(
                setting("MEMORY_PLUGIN_PROJECT_SCOPE_MODE", "explicit")
            ),
            project_repository_id=(setting("MEMORY_PLUGIN_PROJECT_REPOSITORY_ID") or None),
            project_bindings_file=(setting("MEMORY_PLUGIN_PROJECT_BINDINGS_FILE") or None),
            project_git_remote=setting("MEMORY_PLUGIN_GIT_REMOTE") or None,
        )


def _get(values: Mapping[str, str], key: str, default: str = "") -> str:
    value = values.get(key)
    if value is None:
        return default
    return value.strip()


def _env_file_values(path: str) -> dict[str, str]:
    """Read simple KEY=VALUE settings without executing the env file."""

    if not path:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip("'\"")
    return values


def _thread_ref(value: str) -> str | None:
    if not value or value in NO_DEFAULT_THREAD_SENTINELS:
        return None
    return value


def _bool(value: str) -> bool:
    return value.lower() not in {"0", "false", "no", "off"}


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _transcript_tail_mode(value: str) -> str:
    mode = value.strip().lower() or "off"
    if mode not in {"off", "claude"}:
        raise ValueError("MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MODE must be off or claude")
    return mode


def _hook_memory_mode(
    value: str,
    *,
    name: str = "MEMORY_CAPTURE_MODE",
) -> HookMemoryMode:
    mode = value.strip().lower() or HookMemoryMode.RETRIEVE_ONLY.value
    try:
        return HookMemoryMode(mode)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be off, retrieve_only, capture_only, suggest, or auto_apply_safe"
        ) from exc


def _hook_capture_mode(*, explicit_value: str, memory_mode: HookMemoryMode) -> HookCaptureMode:
    if explicit_value:
        try:
            return HookCaptureMode(explicit_value.strip().lower())
        except ValueError as exc:
            raise ValueError(
                "MEMORY_PLUGIN_HOOK_CAPTURE_MODE must be off, episodes, or captures"
            ) from exc
    if memory_mode in {
        HookMemoryMode.CAPTURE_ONLY,
        HookMemoryMode.SUGGEST,
        HookMemoryMode.AUTO_APPLY_SAFE,
    }:
        return HookCaptureMode.CAPTURES
    return HookCaptureMode.OFF


def _project_scope_mode(value: str) -> HookProjectScopeMode:
    try:
        return HookProjectScopeMode(value.strip().lower())
    except ValueError as exc:
        raise ValueError(
            "MEMORY_PLUGIN_PROJECT_SCOPE_MODE must be explicit, shadow, or auto_locked"
        ) from exc


def _positive_float(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _positive_int(value: str, name: str) -> int:
    parsed = _non_negative_int(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _non_negative_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed
