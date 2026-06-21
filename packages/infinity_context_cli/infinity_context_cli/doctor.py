"""Doctor checks for local Infinity Context."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from infinity_context_cli.config import DEFAULT_SERVICE_TOKEN, InfinityContextCliConfig
from infinity_context_cli.local_experience import (
    build_first_capture_surface,
    build_one_minute_path,
    local_experience_score,
    mcp_config_command,
)
from infinity_context_cli.mcp_config import SUPPORTED_AGENTS
from infinity_context_cli.runtime import (
    docker_available,
    docker_compose_available,
    docker_compose_published_server_urls,
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


def run_doctor(config: InfinityContextCliConfig, *, timeout: float = 3.0) -> list[DoctorCheck]:
    checks = [
        DoctorCheck(
            name="repo_root",
            ok=(config.repo_dir / "docker-compose.yml").exists(),
            message=(
                "repo root resolved"
                if (config.repo_dir / "docker-compose.yml").exists()
                else "docker-compose.yml not found"
            ),
            details={"repo_dir": str(config.repo_dir)},
        ),
        DoctorCheck(
            name="docker",
            ok=docker_available(),
            message="docker command available" if docker_available() else "docker command missing",
        ),
        DoctorCheck(
            name="docker_compose",
            ok=docker_compose_available(),
            message=(
                "docker compose available"
                if docker_compose_available()
                else "docker compose unavailable"
            ),
        ),
        DoctorCheck(
            name="service_token",
            ok=bool(config.service_token),
            message=(
                "service token configured"
                if config.service_token and config.service_token != DEFAULT_SERVICE_TOKEN
                else "service token configured with default local token"
            ),
            details={"default_local_token": config.service_token == DEFAULT_SERVICE_TOKEN},
        ),
        _mcp_generated_config_check(config),
    ]
    checks.extend(_api_checks(config, timeout=timeout))
    return checks


def doctor_payload(config: InfinityContextCliConfig, checks: list[DoctorCheck]) -> dict[str, Any]:
    return {
        "ok": all(check.ok for check in checks),
        "api_url": config.api_url,
        "ui_url": _ui_url(config),
        "home": str(config.home),
        "repo_dir": str(config.repo_dir),
        "local_experience": _local_experience_payload(config, checks),
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "message": check.message,
                "details": check.details,
            }
            for check in checks
        ],
    }


def _local_experience_payload(
    config: InfinityContextCliConfig,
    checks: list[DoctorCheck],
) -> dict[str, Any]:
    by_name = {check.name: check for check in checks}
    api_health_ready = bool(by_name.get("api_health") and by_name["api_health"].ok)
    api_capabilities_ready = bool(
        by_name.get("api_capabilities") and by_name["api_capabilities"].ok
    )
    api_ready = api_health_ready and api_capabilities_ready
    visual_ready = bool(by_name.get("ui_browser") and by_name["ui_browser"].ok)
    mcp_check = by_name.get("mcp_generated_configs")
    mcp_details = mcp_check.details if mcp_check is not None else {}
    ready_agents = list(mcp_details.get("ready_agents") or [])
    mcp_paths = [
        entry.get("path")
        for entry in mcp_details.get("configs", [])
        if isinstance(entry, dict) and entry.get("ready") and entry.get("path")
    ]
    capabilities_check = by_name.get("api_capabilities")
    capabilities = capabilities_check.details if capabilities_check is not None else {}
    api_check = by_name.get("api")
    published_urls = (
        list(api_check.details.get("docker_published_api_urls", []))
        if api_check is not None
        else []
    )
    suggested_api_url = published_urls[0] if published_urls else None
    first_capture = build_first_capture_surface(capabilities=capabilities)
    mcp_ready = bool(ready_agents)
    payload = {
        "status": _local_experience_status(
            docker_ready=bool(by_name.get("docker") and by_name["docker"].ok),
            compose_ready=bool(by_name.get("docker_compose") and by_name["docker_compose"].ok),
            api_ready=api_ready,
            visual_ready=visual_ready,
            mcp_ready=mcp_ready,
        ),
        "api_url": config.api_url,
        "ui_url": _ui_url(config),
        "visual_memory_ready": visual_ready,
        "mcp_ready": mcp_ready,
        "ready_agents": ready_agents,
        "mcp_config_paths": mcp_paths,
        "first_capture": first_capture,
        "one_minute_path": build_one_minute_path(
            api_url=config.api_url,
            agents=ready_agents or ["codex"],
            runtime_ready=api_ready,
            visual_ready=visual_ready,
            mcp_ready=mcp_ready,
            first_capture=first_capture,
        ),
        "readiness": local_experience_score(
            runtime_ready=api_ready,
            visual_ready=visual_ready,
            mcp_ready=mcp_ready,
            first_capture=first_capture,
        ),
        "next_actions": _local_experience_next_actions(
            api_url=config.api_url,
            api_ready=api_ready,
            api_health_ready=api_health_ready,
            api_capabilities_status_code=_check_status_code(
                by_name.get("api_capabilities")
            ),
            visual_ready=visual_ready,
            mcp_ready=mcp_ready,
            suggested_api_url=suggested_api_url,
        ),
    }
    if published_urls:
        payload["docker_published_api_urls"] = published_urls
        payload["suggested_api_url"] = suggested_api_url
    return payload


def _local_experience_status(
    *,
    docker_ready: bool,
    compose_ready: bool,
    api_ready: bool,
    visual_ready: bool,
    mcp_ready: bool,
) -> str:
    if api_ready and visual_ready and mcp_ready:
        return "ready"
    if not docker_ready or not compose_ready:
        return "missing_runtime_prerequisites"
    if not api_ready:
        return "runtime_not_ready"
    if not visual_ready:
        return "visual_memory_not_ready"
    return "mcp_config_not_ready"


def _local_experience_next_actions(
    *,
    api_url: str,
    api_ready: bool,
    api_health_ready: bool,
    api_capabilities_status_code: int | None,
    visual_ready: bool,
    mcp_ready: bool,
    suggested_api_url: str | None = None,
) -> list[str]:
    actions: list[str] = []
    if not api_ready and api_health_ready and api_capabilities_status_code in {401, 403}:
        actions.append(
            "API is reachable but auth is rejected; align the MCP token file with the "
            "running server token or restart the local runtime after updating the token file."
        )
    elif not api_ready and suggested_api_url:
        actions.append(
            "Configured API is unreachable; try the detected Docker URL with: "
            f"MEMORY_API_URL={suggested_api_url} infinity-context status"
        )
    elif not api_ready:
        actions.append("Start the local runtime with: infinity-context up --lite")
    if not visual_ready:
        actions.append("Open and verify visual memory with: infinity-context ui --open --check")
    if not mcp_ready:
        command = mcp_config_command(api_url=api_url, agent="codex")
        actions.append(f"Generate an MCP config with: {command}")
    if api_ready and visual_ready and mcp_ready:
        actions.append("Open visual memory and save a Quick Note or File Evidence capture.")
    return actions


def _check_status_code(check: DoctorCheck | None) -> int | None:
    if check is None:
        return None
    status_code = check.details.get("status_code")
    return status_code if isinstance(status_code, int) else None


def _ui_url(config: InfinityContextCliConfig) -> str:
    return f"{config.api_url.rstrip('/')}/ui/"


def _api_checks(config: InfinityContextCliConfig, *, timeout: float) -> list[DoctorCheck]:
    headers = {"Authorization": f"Bearer {config.service_token}"}
    checks: list[DoctorCheck] = []
    try:
        with httpx.Client(base_url=config.api_url, timeout=timeout, headers=headers) as client:
            health = client.get("/v1/health")
            checks.append(
                DoctorCheck(
                    name="api_health",
                    ok=health.is_success,
                    message=(
                        "health endpoint reachable"
                        if health.is_success
                        else f"health returned HTTP {health.status_code}"
                    ),
                    details=_safe_json(health),
                )
            )
            capabilities = client.get("/v1/capabilities")
            checks.append(
                DoctorCheck(
                    name="api_capabilities",
                    ok=capabilities.is_success,
                    message=(
                        "capabilities endpoint reachable"
                        if capabilities.is_success
                        else f"capabilities returned HTTP {capabilities.status_code}"
                    ),
                    details=_safe_json(capabilities),
                )
            )
            ui = client.get("/ui/")
            title_present = "Infinity Context Browser" in ui.text
            checks.append(
                DoctorCheck(
                    name="ui_browser",
                    ok=ui.is_success and title_present,
                    message=(
                        "visual memory browser reachable"
                        if ui.is_success and title_present
                        else f"visual memory browser returned HTTP {ui.status_code}"
                    ),
                    details={
                        "status_code": ui.status_code,
                        "title_present": title_present,
                        "path": "/ui/",
                    },
                )
            )
    except httpx.HTTPError as exc:
        published_urls = docker_compose_published_server_urls(config)
        details: dict[str, Any] = {"error": exc.__class__.__name__}
        if published_urls:
            details["docker_published_api_urls"] = published_urls
            details["suggested_api_url"] = published_urls[0]
        checks.append(
            DoctorCheck(
                name="api",
                ok=False,
                message="api unreachable",
                details=details,
            )
        )
    return checks


def _mcp_generated_config_check(config: InfinityContextCliConfig) -> DoctorCheck:
    generated_dir = config.home / "generated"
    entries = []
    for agent in sorted(SUPPORTED_AGENTS):
        path = generated_dir / f"{agent}-mcp.json"
        if path.exists():
            entries.append(_mcp_generated_config_entry(agent=agent, path=path))
    ready_agents = [entry["agent"] for entry in entries if entry["ready"]]
    existing_agents = [entry["agent"] for entry in entries]
    return DoctorCheck(
        name="mcp_generated_configs",
        ok=bool(ready_agents),
        message=(
            f"generated MCP config ready for {', '.join(ready_agents)}"
            if ready_agents
            else (
                "generated MCP config found but auth is not ready for "
                f"{', '.join(existing_agents)}"
            )
            if existing_agents
            else "no generated MCP config found"
        ),
        details={
            "generated_dir": str(generated_dir),
            "agents": existing_agents,
            "ready_agents": ready_agents,
            "missing_agents": [
                agent for agent in sorted(SUPPORTED_AGENTS) if agent not in existing_agents
            ],
            "configs": entries,
        },
    )


def _mcp_generated_config_entry(*, agent: str, path: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "agent": agent,
        "path": str(path),
        "ready": False,
        "auth_source": "missing",
        "token_included": False,
        "token_file_exists": False,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        entry["error"] = exc.__class__.__name__
        return entry
    server = _mcp_server_config(payload)
    env = server.get("env") if isinstance(server, dict) else {}
    env = env if isinstance(env, dict) else {}
    raw_token = str(env.get("MEMORY_MCP_AUTH_TOKEN") or "").strip()
    token_file = str(env.get("MEMORY_MCP_AUTH_TOKEN_FILE") or "").strip()
    entry["env_keys"] = sorted(str(key) for key in env)
    if raw_token and not raw_token.startswith("${"):
        entry["ready"] = True
        entry["auth_source"] = "inline_token"
        entry["token_included"] = True
    elif token_file:
        token_path = Path(token_file).expanduser()
        entry["auth_source"] = "token_file"
        entry["token_file"] = str(token_path)
        entry["token_file_exists"] = token_path.exists()
        entry["ready"] = token_path.exists()
    elif raw_token.startswith("${") and (
        os.environ.get("MEMORY_MCP_AUTH_TOKEN") or os.environ.get("MEMORY_SERVICE_TOKEN")
    ):
        entry["ready"] = True
        entry["auth_source"] = "process_env"
    elif raw_token.startswith("${"):
        entry["auth_source"] = "unresolved_env_placeholder"
    return entry


def _mcp_server_config(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("infinity-context"), dict):
        return payload["infinity-context"]
    servers = payload.get("mcpServers")
    if isinstance(servers, dict) and isinstance(servers.get("infinity-context"), dict):
        return servers["infinity-context"]
    return {}


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"status_code": response.status_code}
    if isinstance(payload, dict):
        payload.pop("token", None)
        payload.pop("auth_token", None)
        payload.setdefault("status_code", response.status_code)
        return payload
    return {"status_code": response.status_code}
