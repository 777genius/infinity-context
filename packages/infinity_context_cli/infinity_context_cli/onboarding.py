"""Safe public onboarding presets and agent integration diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infinity_context_core.application.sensitive_text import redact_sensitive_text

from infinity_context_cli.config import InfinityContextCliConfig
from infinity_context_cli.local_experience import (
    build_first_capture_surface,
    build_one_minute_path,
    local_experience_score,
)

AUTO_MEMORY_MODES = ("suggest", "manual", "retrieve_only")
_HOOK_CAPTURE_AGENTS = frozenset({"codex", "claude", "gemini"})


@dataclass(frozen=True)
class AutoMemoryPreset:
    """A user-visible, non-destructive memory capture policy."""

    name: str
    capture_mode: str
    mcp_write_mode: str
    mcp_ingest_mode: str
    review_gated: bool
    auto_apply: bool
    description: str


_AUTO_MEMORY_PRESETS = {
    "suggest": AutoMemoryPreset(
        name="suggest",
        capture_mode="suggest",
        mcp_write_mode="suggest",
        mcp_ingest_mode="small_docs",
        review_gated=True,
        auto_apply=False,
        description="Redacted captures become pending suggestions for review.",
    ),
    "manual": AutoMemoryPreset(
        name="manual",
        capture_mode="off",
        mcp_write_mode="suggest",
        mcp_ingest_mode="small_docs",
        review_gated=True,
        auto_apply=False,
        description="Hooks keep recall, while memory changes require explicit MCP suggestions.",
    ),
    "retrieve_only": AutoMemoryPreset(
        name="retrieve_only",
        capture_mode="retrieve_only",
        mcp_write_mode="off",
        mcp_ingest_mode="off",
        review_gated=True,
        auto_apply=False,
        description="Hooks retrieve context only and never create captures.",
    ),
}


def auto_memory_preset(mode: str) -> AutoMemoryPreset:
    """Return one supported auto-memory preset without widening write privileges."""

    try:
        return _AUTO_MEMORY_PRESETS[mode]
    except KeyError as exc:
        allowed = ", ".join(AUTO_MEMORY_MODES)
        raise ValueError(f"Unsupported auto-memory mode: {mode}. Choose one of: {allowed}") from exc


def auto_memory_env(*, agent: str, mode: str) -> dict[str, str]:
    """Render bounded hook settings for an individual agent integration."""

    preset = auto_memory_preset(mode)
    events = ingest_events_for_agent(agent=agent, mode=mode)
    return {
        "MEMORY_MCP_WRITE_MODE": preset.mcp_write_mode,
        "MEMORY_MCP_INGEST_MODE": preset.mcp_ingest_mode,
        "MEMORY_CAPTURE_MODE": preset.capture_mode,
        "MEMORY_PLUGIN_HOOKS_ENABLED": "true",
        "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": ",".join(events),
        "MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MODE": "off",
    }


def ingest_events_for_agent(*, agent: str, mode: str) -> tuple[str, ...]:
    """Keep capture limited to durable lifecycle boundaries, never tool events."""

    if auto_memory_preset(mode).capture_mode != "suggest":
        return ()
    if agent in {"codex", "claude"}:
        return ("UserPromptSubmit", "Stop")
    if agent == "gemini":
        return ("AfterAgent", "SessionEnd")
    return ()


def auto_memory_diagnostics(*, agent: str, mode: str) -> dict[str, object]:
    """Return an explicit, token-free explanation of onboarding behavior."""

    preset = auto_memory_preset(mode)
    events = ingest_events_for_agent(agent=agent, mode=mode)
    lifecycle_capture_supported = agent in _HOOK_CAPTURE_AGENTS
    capture_enabled = preset.capture_mode == "suggest" and lifecycle_capture_supported
    if not lifecycle_capture_supported:
        capture_status = "mcp_suggestions_only"
    elif capture_enabled:
        capture_status = "review_gated_capture"
    else:
        capture_status = "disabled"
    return {
        "mode": preset.name,
        "capture_mode": preset.capture_mode,
        "mcp_write_mode": preset.mcp_write_mode,
        "mcp_ingest_mode": preset.mcp_ingest_mode,
        "review_gated": preset.review_gated,
        "auto_apply": preset.auto_apply,
        "ingest_events": list(events),
        "capture_status": capture_status,
        "raw_tool_capture": False,
        "transcript_tail": "off",
        "description": preset.description,
    }


def manual_agent_integration_reports(agents: list[str]) -> list[dict[str, object]]:
    """Represent the explicit manual route without implying an installation occurred."""

    return [
        {
            "agent": agent,
            "status": "manual",
            "installed": False,
            "configured": False,
            "reason": "Agent installation was skipped by --no-install-agents.",
        }
        for agent in agents
    ]


def install_agent_integrations(
    *,
    config: InfinityContextCliConfig,
    agents: list[str],
    auto_memory_mode: str,
) -> list[dict[str, object]]:
    """Run the installer once and return only structured, redacted status data.

    A failed or unavailable plugin-kit command is intentionally non-fatal to local
    runtime setup. The caller can show the generated MCP config as the manual
    fallback instead of claiming that an integration is active.
    """

    script_path = config.repo_dir / "scripts" / "install_memory_agent_plugin.py"
    if not script_path.is_file():
        return _unavailable_reports(agents, "Agent installer is not available in this checkout.")

    command = [
        sys.executable,
        str(script_path),
        "--json",
        "--auto-memory-mode",
        auto_memory_mode,
        "--api-url",
        config.api_url,
        "--auth-token-file",
        str(config.env_path),
        "--default-space",
        config.default_space_slug,
        "--default-memory-scope",
        config.default_memory_scope_external_ref,
    ]
    for agent in agents:
        command.extend(("--agent", agent))

    try:
        completed = subprocess.run(
            command,
            cwd=config.repo_dir,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _unavailable_reports(agents, "Agent installer could not be started.")

    payload = _installer_payload(completed.stdout)
    reports = payload.get("integrations") if isinstance(payload, dict) else None
    if not isinstance(reports, list):
        reason = "Agent installer returned no structured status."
        if completed.returncode != 0:
            reason = "Agent installer failed before confirming an integration."
        return _failed_reports(agents, reason)

    normalized = [report for report in reports if isinstance(report, dict)]
    by_agent = {str(report.get("agent")): report for report in normalized}
    result: list[dict[str, object]] = []
    for agent in agents:
        report = by_agent.get(agent)
        if report is None:
            result.append(
                {
                    "agent": agent,
                    "status": "unverified",
                    "installed": False,
                    "configured": False,
                    "reason": "Installer did not confirm this selected agent.",
                }
            )
            continue
        result.append(_redacted_report(report))
    return result


def integrated_agents(reports: list[dict[str, object]]) -> list[str]:
    """Return only integrations proven by the installer and materialized config check."""

    return [
        str(report["agent"])
        for report in reports
        if report.get("status") == "installed" and report.get("installed") is True
    ]


def _installer_payload(raw: object) -> dict[str, object]:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _redacted_report(report: dict[str, object]) -> dict[str, object]:
    """Limit installer diagnostics to the stable public report contract."""

    allowed = {
        "agent",
        "integration_id",
        "status",
        "installed",
        "configured",
        "action",
        "reason",
        "auto_memory",
        "materialized_paths",
    }
    return {
        key: _safe_report_value(value)
        for key, value in report.items()
        if key in allowed
    }


def _safe_report_value(value: object) -> object:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [_safe_report_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_report_value(item) for key, item in value.items()}
    return value


def _unavailable_reports(agents: list[str], reason: str) -> list[dict[str, object]]:
    return [
        {
            "agent": agent,
            "status": "unavailable",
            "installed": False,
            "configured": False,
            "reason": reason,
        }
        for agent in agents
    ]


def _failed_reports(agents: list[str], reason: str) -> list[dict[str, object]]:
    return [
        {
            "agent": agent,
            "status": "failed",
            "installed": False,
            "configured": False,
            "reason": reason,
        }
        for agent in agents
    ]


def quickstart_ok(
    *,
    runtime_result: object,
    status: dict[str, Any] | None,
    no_start: bool,
    agent_integrations: list[dict[str, object]] | None = None,
    require_agent_integrations: bool = False,
) -> bool:
    runtime_ok = no_start or bool(
        runtime_result is not None and runtime_result.ok and status and status.get("ok")
    )
    if not runtime_ok or not require_agent_integrations:
        return runtime_ok
    return agent_integrations_ok(agent_integrations or [])


def agent_integrations_ok(reports: list[dict[str, object]]) -> bool:
    return bool(reports) and all(
        report.get("status") == "installed"
        and report.get("installed") is True
        and report.get("configured") is True
        for report in reports
    )


def quickstart_next_steps(
    *,
    agents: list[str],
    home: Path,
    include_token: bool,
    no_start: bool,
    open_ui: bool,
    agent_integrations: list[dict[str, object]],
) -> list[str]:
    steps = []
    if no_start:
        steps.append("Start the local runtime with: infinity-context up --lite")
    steps.append("Check readiness with: infinity-context status")
    steps.append(
        "Visual memory opened with: infinity-context ui --open"
        if open_ui
        else "Open visual memory with: infinity-context ui --open"
    )
    if include_token:
        steps.append("Add the generated MCP config path to your agent.")
    else:
        steps.append(f"Generated MCP config reads its local token from: {home / '.env'}")
        steps.append("Add the generated MCP config path to your agent.")
    if agents:
        steps.append(f"Generated MCP config for: {', '.join(agents)}")
    installed = integrated_agents(agent_integrations)
    if len(installed) == len(agents):
        steps.append(f"Restart these agents to load Infinity Context: {', '.join(installed)}")
    elif installed:
        steps.append(f"Restart confirmed integrations: {', '.join(installed)}")
        steps.append(
            "Some selected integrations are not confirmed; use their MCP configs manually."
        )
    else:
        steps.append("Agent integration is not confirmed; use the generated MCP config manually.")
    return steps


def quickstart_local_experience(
    *,
    config: InfinityContextCliConfig,
    agents: list[str],
    mcp_configs: list[dict[str, Any]],
    agent_integrations: list[dict[str, object]],
    status: dict[str, Any] | None,
    no_start: bool,
    require_agent_integrations: bool,
) -> dict[str, Any]:
    runtime_ready = bool(status and status.get("ok"))
    mcp_paths = [item["path"] for item in mcp_configs if item.get("path")]
    capabilities = status.get("capabilities") if isinstance(status, dict) else None
    first_capture = build_first_capture_surface(capabilities=capabilities)
    visual_ready = runtime_ready
    mcp_ready = bool(mcp_paths)
    agent_connect_ok = (
        agent_integrations_ok(agent_integrations) if require_agent_integrations else True
    )
    return {
        "status": _quickstart_local_experience_status(
            no_start=no_start,
            runtime_ready=runtime_ready,
            mcp_ready=mcp_ready,
            agent_connect_ok=agent_connect_ok,
            require_agent_integrations=require_agent_integrations,
        ),
        "api_url": config.api_url,
        "ui_url": _ui_url(config.api_url),
        "visual_memory_ready": visual_ready,
        "mcp_ready": mcp_ready,
        "ready_agents": agents,
        "mcp_config_paths": mcp_paths,
        "agent_integrations": agent_integrations,
        "integrated_agents": integrated_agents(agent_integrations),
        "agent_connect_ok": agent_connect_ok,
        "agent_connect_required": require_agent_integrations,
        "first_capture": first_capture,
        "one_minute_path": build_one_minute_path(
            api_url=config.api_url,
            agents=agents,
            runtime_ready=runtime_ready,
            visual_ready=visual_ready,
            mcp_ready=mcp_ready,
            first_capture=first_capture,
        ),
        "readiness": local_experience_score(
            runtime_ready=runtime_ready,
            visual_ready=visual_ready,
            mcp_ready=mcp_ready,
            first_capture=first_capture,
        ),
    }


def _quickstart_local_experience_status(
    *,
    no_start: bool,
    runtime_ready: bool,
    mcp_ready: bool,
    agent_connect_ok: bool,
    require_agent_integrations: bool,
) -> str:
    if require_agent_integrations and not agent_connect_ok:
        return "agent_integration_not_ready"
    if no_start and mcp_ready:
        return "configured_not_started"
    if runtime_ready and mcp_ready:
        return "ready"
    if not runtime_ready:
        return "runtime_not_ready"
    return "mcp_config_not_ready"


def print_quickstart_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"ok: {payload['ok']}")
    print(f"home: {payload['home']}")
    print(f"api_url: {payload['api_url']}")
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        print(f"runtime: {'started' if runtime.get('ok') else 'failed'}")
        if not runtime.get("ok") and runtime.get("stderr"):
            print(f"runtime_error: {runtime['stderr']}", file=sys.stderr)
    else:
        print("runtime: skipped")
    status = payload.get("status")
    if isinstance(status, dict):
        print(f"status: {'ready' if status.get('ok') else 'not_ready'}")
    experience = payload.get("local_experience")
    if isinstance(experience, dict):
        print_local_experience_summary(experience)
    auto_memory = payload.get("auto_memory")
    if isinstance(auto_memory, dict):
        print(
            "auto_memory: "
            f"{auto_memory.get('mode')} "
            f"(review_gated={auto_memory.get('review_gated')}, "
            f"auto_apply={auto_memory.get('auto_apply')})"
        )
    print(f"ui: {'opened ' if payload.get('opened_ui') else ''}{payload.get('ui_url')}")
    for item in payload.get("mcp_configs", []):
        if isinstance(item, dict):
            token_note = (
                "private token included" if item.get("token_included") else "token redacted"
            )
            print(f"mcp_config[{item.get('agent')}]: {item.get('path')} ({token_note})")
    for item in payload.get("agent_integrations", []):
        if isinstance(item, dict):
            print(f"agent_integration[{item.get('agent')}]: {item.get('status')}")
            if item.get("reason"):
                print(f"agent_integration_note: {item.get('reason')}")
    print("next_steps:")
    for step in payload.get("next_steps", []):
        print(f"  - {step}")


def print_local_experience_summary(experience: dict[str, Any]) -> None:
    print(f"experience: {experience.get('status')}")
    print(
        "visual_memory: "
        f"{'ready' if experience.get('visual_memory_ready') else 'not_ready'} "
        f"({experience.get('ui_url')})"
    )
    ready_agents = experience.get("ready_agents") or []
    if ready_agents:
        print(f"mcp_ready_for: {', '.join(str(agent) for agent in ready_agents)}")
    integrated = experience.get("integrated_agents") or []
    if integrated:
        print(f"agent_integrated: {', '.join(str(agent) for agent in integrated)}")
    readiness = experience.get("readiness")
    if isinstance(readiness, dict):
        print(f"first_use_score: {readiness.get('score')}/{readiness.get('scale')}")
    first_capture = experience.get("first_capture")
    if isinstance(first_capture, dict):
        supports = first_capture.get("supports") or []
        if supports:
            print(f"capture_supports: {', '.join(str(item) for item in supports)}")
        artifact_previews = first_capture.get("artifact_previews") or []
        if artifact_previews:
            print(f"visual_previews: {', '.join(str(item) for item in artifact_previews)}")
    one_minute_path = experience.get("one_minute_path")
    if not isinstance(one_minute_path, list):
        return
    next_item = next(
        (
            item
            for item in one_minute_path
            if isinstance(item, dict) and item.get("status") in {"todo", "next"}
        ),
        None,
    )
    if isinstance(next_item, dict):
        print(f"first_use_next: {_local_experience_step_label(next_item)}")
    print("first_use_path:")
    for item in one_minute_path:
        if isinstance(item, dict):
            print(
                f"  - [{item.get('status')}] {item.get('id')}: "
                f"{_local_experience_step_label(item)}"
            )


def _local_experience_step_label(item: dict[str, Any]) -> str:
    label = str(item.get("command") or item.get("tab") or item.get("label") or item.get("id"))
    url = item.get("url")
    if url and url not in label:
        label = f"{label} ({url})"
    blocked_by = item.get("blocked_by")
    if blocked_by:
        label = f"{label} - blocked_by: {blocked_by}"
    degraded_reason = item.get("degraded_reason")
    if degraded_reason:
        label = f"{label} - degraded: {degraded_reason}"
    return label


def _ui_url(api_url: str) -> str:
    return f"{api_url.rstrip('/')}/ui/"
