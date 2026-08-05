"""Install selected Infinity Context agent plugins with a truthful status report."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, NamedTuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "infinity-context-agent-plugin"
GEMINI_HOOK_PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "infinity-context-agent-plugin-gemini-hooks"
PLUGIN_KIT = PROJECT_ROOT / "scripts" / "plugin-kit-ai-local"
INTEGRATION_ID = "infinity-context-agent-plugin"
GEMINI_HOOK_INTEGRATION_ID = "infinity-context-agent-plugin-gemini-hooks"
PRIMARY_INSTALL_TARGETS = ("codex", "claude", "opencode", "cursor")
GEMINI_HOOK_INSTALL_TARGETS = ("gemini",)
SUPPORTED_AGENTS = (*PRIMARY_INSTALL_TARGETS, *GEMINI_HOOK_INSTALL_TARGETS)
AUTO_MEMORY_MODES = ("suggest", "manual", "retrieve_only")
InstallSpec = tuple[str, Path, tuple[str, ...]]
SOURCE_ROOT_MARKER = ".infinity-context-source-root"
RUNTIME_ENV_MARKER = ".infinity-context-runtime.env"


class RuntimeSettings(NamedTuple):
    api_url: str
    auth_token_file: Path
    default_space_slug: str
    default_memory_scope_external_ref: str
    auto_memory_mode: str


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    agents = _selected_agents(args)
    settings = RuntimeSettings(
        api_url=args.api_url.rstrip("/"),
        auth_token_file=Path(args.auth_token_file).expanduser(),
        default_space_slug=args.default_space,
        default_memory_scope_external_ref=args.default_memory_scope,
        auto_memory_mode=args.auto_memory_mode,
    )
    reports: list[dict[str, object]] = []
    for spec in install_specs(agents):
        reports.extend(_install_spec(spec, settings=settings, dry_run=args.dry_run))
    payload = {
        "ok": all(report.get("status") in {"installed", "planned"} for report in reports),
        "selected_agents": list(agents),
        "integrations": reports,
    }
    _print_payload(payload, as_json=args.json)
    return 0 if payload["ok"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or update selected Infinity Context plugins."
    )
    parser.add_argument("--agent", action="append", choices=SUPPORTED_AGENTS, default=None)
    parser.add_argument("--all-agents", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--api-url", default="http://127.0.0.1:7788")
    parser.add_argument(
        "--auth-token-file",
        default=str(Path("~/.infinity-context/.env").expanduser()),
        help="Path read by MCP and hook processes; never a token value.",
    )
    parser.add_argument("--default-space", default="default")
    parser.add_argument("--default-memory-scope", default="default")
    parser.add_argument("--auto-memory-mode", choices=AUTO_MEMORY_MODES, default="suggest")
    return parser


def _selected_agents(args: argparse.Namespace) -> tuple[str, ...]:
    if args.all_agents or not args.agent:
        return SUPPORTED_AGENTS
    return tuple(dict.fromkeys(args.agent))


def install_specs(agents: tuple[str, ...] = SUPPORTED_AGENTS) -> tuple[InstallSpec, ...]:
    primary = tuple(agent for agent in agents if agent in PRIMARY_INSTALL_TARGETS)
    gemini = tuple(agent for agent in agents if agent in GEMINI_HOOK_INSTALL_TARGETS)
    specs: list[InstallSpec] = []
    if primary:
        specs.append((INTEGRATION_ID, PLUGIN_ROOT, primary))
    if gemini:
        specs.append((GEMINI_HOOK_INTEGRATION_ID, GEMINI_HOOK_PLUGIN_ROOT, gemini))
    return tuple(specs)


def _install_spec(
    spec: InstallSpec,
    *,
    settings: RuntimeSettings,
    dry_run: bool,
) -> list[dict[str, object]]:
    integration_id, _plugin_root, targets = spec
    installed_targets = managed_targets(integration_id)
    if installed_targets is not None:
        missing_targets = tuple(target for target in targets if target not in installed_targets)
        if missing_targets:
            missing = ", ".join(missing_targets)
            reason = (
                "plugin-kit-ai 1.2.4 cannot add selected targets to an existing managed "
                f"integration: {missing}. No integration was changed."
            )
            return [
                _report(
                    agent=target,
                    integration_id=integration_id,
                    action="unsupported_target_expansion",
                    status="failed",
                    reason=reason,
                    auto_memory=runtime_auto_memory_diagnostics(
                        target, settings.auto_memory_mode
                    ),
                )
                for target in targets
            ]
    plugin_kit = resolve_plugin_kit()
    if plugin_kit is None:
        return [
            _unavailable_report(target, integration_id, settings.auto_memory_mode)
            for target in targets
        ]
    command, action = install_command(spec, dry_run=dry_run, plugin_kit=plugin_kit)
    if dry_run:
        return [
            _report(
                agent=target,
                integration_id=integration_id,
                action=action,
                status="planned",
                reason="Dry-run only; no agent integration was changed.",
                auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
            )
            for target in targets
        ]
    if not settings.auth_token_file.is_file():
        return [
            _report(
                agent=target,
                integration_id=integration_id,
                action="unavailable",
                status="unavailable",
                reason="The configured token file is unavailable; use a valid local env file.",
                auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
            )
            for target in targets
        ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [
            _unavailable_report(target, integration_id, settings.auto_memory_mode)
            for target in targets
        ]
    if completed.returncode != 0:
        return [
            _report(
                agent=target,
                integration_id=integration_id,
                action=action,
                status="failed",
                reason="plugin-kit-ai did not confirm this integration.",
                auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
            )
            for target in targets
        ]
    return [
        _materialize_target(
            target=target,
            integration_id=integration_id,
            plugin_root=spec[1],
            action=action,
            settings=settings,
        )
        for target in targets
    ]


def install_command(
    spec: InstallSpec,
    *,
    dry_run: bool,
    plugin_kit: str | None = None,
) -> tuple[list[str], str]:
    integration_id, plugin_root, targets = spec
    executable = plugin_kit or resolve_plugin_kit()
    if executable is None:
        raise RuntimeError("plugin-kit-ai is unavailable")
    if is_managed(integration_id):
        command = [executable, "update", integration_id]
        action = "update"
    else:
        command = [executable, "add", str(plugin_root)]
        for target in targets:
            command.extend(("--target", target))
        action = "add"
    if dry_run:
        command.append("--dry-run")
    return command, action


def resolve_plugin_kit() -> str | None:
    """Resolve an explicit, bundled, or PATH-provided plugin-kit-ai executable."""

    override = os.getenv("INFINITY_CONTEXT_PLUGIN_KIT")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)
    if PLUGIN_KIT.is_file():
        return str(PLUGIN_KIT)
    return shutil.which("plugin-kit-ai")


def _materialize_target(
    *,
    target: str,
    integration_id: str,
    plugin_root: Path,
    action: str,
    settings: RuntimeSettings,
) -> dict[str, object]:
    roots = materialized_runtime_roots(target, integration_id)
    if not roots:
        return _report(
            agent=target,
            integration_id=integration_id,
            action=action,
            status="unverified",
            reason="plugin-kit-ai exited successfully but no materialized integration was found.",
            auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
        )
    try:
        configured_roots = write_source_root_markers(
            (integration_id, plugin_root, (target,)),
            settings=settings,
        )
    except OSError:
        return _report(
            agent=target,
            integration_id=integration_id,
            action=action,
            status="unverified",
            reason="The materialized integration could not be configured safely.",
            auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
        )
    if not configured_roots:
        return _report(
            agent=target,
            integration_id=integration_id,
            action=action,
            status="unverified",
            reason="No structured MCP config was found in the materialized integration.",
            auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
        )
    return _report(
        agent=target,
        integration_id=integration_id,
        action=action,
        status="installed",
        reason="Installed and configured with a token file and review-gated memory policy.",
        auto_memory=runtime_auto_memory_diagnostics(target, settings.auto_memory_mode),
        materialized_paths=[str(root) for root in configured_roots],
    )


def write_source_root_markers(
    spec: InstallSpec,
    *,
    settings: RuntimeSettings | None = None,
) -> tuple[Path, ...]:
    """Write source markers and optional per-target structured runtime configuration."""

    integration_id, plugin_root, targets = spec
    configured: list[Path] = []
    for target in targets:
        for materialized_root in materialized_runtime_roots(target, integration_id):
            marker = materialized_root / SOURCE_ROOT_MARKER
            marker.write_text(f"{PROJECT_ROOT}\n", encoding="utf-8")
            sync_runtime_bin(plugin_root, materialized_root)
            if settings is None:
                continue
            runtime_env = runtime_env_for_agent(target=target, settings=settings)
            _write_runtime_env(materialized_root, runtime_env)
            if _patch_materialized_mcp_configs(materialized_root, runtime_env):
                configured.append(materialized_root)
    return tuple(configured)


def runtime_env_for_agent(*, target: str, settings: RuntimeSettings) -> dict[str, str]:
    retrieve_only = settings.auto_memory_mode == "retrieve_only"
    return {
        "MEMORY_MCP_AGENT_NAME": target,
        "MEMORY_MCP_API_URL": settings.api_url,
        "MEMORY_MCP_AUTH_TOKEN_FILE": str(settings.auth_token_file),
        "MEMORY_MCP_DEFAULT_SPACE_SLUG": settings.default_space_slug,
        "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": settings.default_memory_scope_external_ref,
        "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF": "__INFINITY_CONTEXT_NO_DEFAULT_THREAD__",
        "MEMORY_MCP_WRITE_MODE": "off" if retrieve_only else "suggest",
        "MEMORY_MCP_DELETE_MODE": "off",
        "MEMORY_MCP_INGEST_MODE": "off" if retrieve_only else "small_docs",
        "MEMORY_CAPTURE_MODE": capture_mode_for(settings.auto_memory_mode),
        "MEMORY_PLUGIN_HOOKS_ENABLED": "true",
        "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": ",".join(
            ingest_events_for_agent(target=target, mode=settings.auto_memory_mode)
        ),
        "MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MODE": "off",
    }


def capture_mode_for(mode: str) -> str:
    return {"suggest": "suggest", "manual": "off", "retrieve_only": "retrieve_only"}[mode]


def ingest_events_for_agent(*, target: str, mode: str) -> tuple[str, ...]:
    if mode != "suggest":
        return ()
    if target in {"codex", "claude"}:
        return ("UserPromptSubmit", "Stop")
    if target == "gemini":
        return ("AfterAgent", "SessionEnd")
    return ()


def runtime_auto_memory_diagnostics(target: str, mode: str) -> dict[str, object]:
    events = ingest_events_for_agent(target=target, mode=mode)
    capture_enabled = mode == "suggest" and target in {"codex", "claude", "gemini"}
    return {
        "mode": mode,
        "capture_mode": capture_mode_for(mode),
        "mcp_write_mode": "off" if mode == "retrieve_only" else "suggest",
        "mcp_ingest_mode": "off" if mode == "retrieve_only" else "small_docs",
        "review_gated": True,
        "auto_apply": False,
        "ingest_events": list(events),
        "capture_status": "review_gated_capture"
        if capture_enabled
        else "mcp_suggestions_only"
        if mode == "suggest"
        else "disabled",
        "raw_tool_capture": False,
    }


def _write_runtime_env(root: Path, values: dict[str, str]) -> None:
    path = root / RUNTIME_ENV_MARKER
    rendered = "\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n"
    path.write_text(rendered, encoding="utf-8")
    path.chmod(0o600)


def _patch_materialized_mcp_configs(root: Path, values: dict[str, str]) -> bool:
    patched = False
    for path in _mcp_config_paths(root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not _patch_mcp_envs(payload, values):
            continue
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        patched = True
    return patched


def _mcp_config_paths(root: Path) -> tuple[Path, ...]:
    names = {".mcp.json", "opencode.json", "gemini-extension.json", "mcp.json"}
    return tuple(path for path in root.rglob("*.json") if path.name in names)


def _patch_mcp_envs(value: dict[str, Any], values: dict[str, str]) -> bool:
    patched = False
    for key, item in value.items():
        if key in {"env", "environment"} and isinstance(item, dict):
            if any(str(env_key).startswith("MEMORY_MCP_") for env_key in item):
                item.pop("MEMORY_MCP_AUTH_TOKEN", None)
                item.pop("MEMORY_SERVICE_TOKEN", None)
                item.update(values)
                patched = True
        elif isinstance(item, dict):
            patched = _patch_mcp_envs(item, values) or patched
    return patched


def materialized_runtime_roots(target: str, integration_id: str) -> tuple[Path, ...]:
    materialized_root = materialized_plugin_root(target, integration_id)
    if not materialized_root.exists():
        return ()
    roots = [materialized_root]
    nested_plugin_root = materialized_root / "plugins" / integration_id
    if nested_plugin_root.exists():
        roots.append(nested_plugin_root)
    return tuple(roots)


def sync_runtime_bin(plugin_root: Path, materialized_root: Path) -> None:
    source_bin = plugin_root / "bin"
    if not source_bin.exists():
        return
    destination_bin = materialized_root / "bin"
    if destination_bin.exists():
        shutil.rmtree(destination_bin)
    shutil.copytree(source_bin, destination_bin)


def materialized_plugin_root(target: str, integration_id: str) -> Path:
    base = Path(
        os.getenv(
            "PLUGIN_KIT_AI_MATERIALIZED_ROOT",
            str(Path.home() / ".plugin-kit-ai" / "materialized"),
        )
    )
    return base / target / integration_id


def is_managed(integration_id: str = INTEGRATION_ID) -> bool:
    return managed_targets(integration_id) is not None


def managed_targets(integration_id: str = INTEGRATION_ID) -> frozenset[str] | None:
    state_path = Path(
        os.getenv("PLUGIN_KIT_AI_STATE_PATH", str(Path.home() / ".plugin-kit-ai" / "state.json"))
    )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    installations = state.get("installations")
    if not isinstance(installations, list):
        return None
    for item in installations:
        if not isinstance(item, dict) or item.get("integration_id") != integration_id:
            continue
        targets = item.get("targets")
        if isinstance(targets, dict):
            return frozenset(str(target) for target in targets)
        return frozenset()
    return None


def _unavailable_report(
    agent: str,
    integration_id: str,
    auto_memory_mode: str,
) -> dict[str, object]:
    return _report(
        agent=agent,
        integration_id=integration_id,
        action="unavailable",
        status="unavailable",
        reason="plugin-kit-ai is unavailable; use the generated MCP config manually.",
        auto_memory=runtime_auto_memory_diagnostics(agent, auto_memory_mode),
    )


def _report(
    *,
    agent: str,
    integration_id: str,
    action: str,
    status: str,
    reason: str,
    auto_memory: dict[str, object],
    materialized_paths: list[str] | None = None,
) -> dict[str, object]:
    return {
        "agent": agent,
        "integration_id": integration_id,
        "action": action,
        "status": status,
        "installed": status == "installed",
        "configured": status == "installed",
        "reason": reason,
        "auto_memory": auto_memory,
        "materialized_paths": materialized_paths or [],
    }


def _print_payload(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for report in payload.get("integrations", []):
        if not isinstance(report, dict):
            continue
        print(f"{report.get('agent')}: {report.get('status')} - {report.get('reason')}")


if __name__ == "__main__":
    raise SystemExit(main())
