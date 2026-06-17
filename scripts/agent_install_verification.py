"""Verify Memory Agent plugin install state and live MCP reachability.

This script is intentionally local and small. It reads plugin-kit-ai state as
JSON, runs bounded CLI checks, and never scans agent history directories.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from memo_stack_core.reporting import with_report_provenance

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "memo-stack-agent-plugin"
CURSOR_WORKSPACE_PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "memo-stack-agent-plugin-cursor-workspace"
GEMINI_HOOK_PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "memo-stack-agent-plugin-gemini-hooks"
NO_DEFAULT_THREAD_SENTINEL = "__MEMO_STACK_NO_DEFAULT_THREAD__"
MCP_SERVER_ALIAS = "memo-stack"
INTEGRATION_ID = "memo-stack-agent-plugin"
GEMINI_HOOK_INTEGRATION_ID = "memo-stack-agent-plugin-gemini-hooks"
DEFAULT_API_URL = "http://127.0.0.1:7788"
DEFAULT_AUTH_TOKEN = "local-dev-token"
AGENT_LIVE_SMOKE_SUITE = "memo-stack-agent-live-smoke"
SENSITIVE_KEY_RE = re.compile(
    r"(TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|DATABASE_URL|DB_URL|DSN)$",
    re.IGNORECASE,
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}\b"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|credential)\s*[:=]\s*['\"]?"
        r"[A-Za-z0-9_./+=-]{8,}"
    ),
)


class VerificationFailure(RuntimeError):
    pass


def live_smoke_auth_token() -> str:
    return (
        os.getenv("MEMORY_MCP_AUTH_TOKEN")
        or os.getenv("MEMORY_SERVICE_TOKEN")
        or DEFAULT_AUTH_TOKEN
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_doctor = subparsers.add_parser("install-doctor")
    install_doctor.add_argument("--strict-codex", action="store_true")
    install_doctor.add_argument("--skip-cli-lists", action="store_true")

    live_smoke = subparsers.add_parser("live-smoke")
    live_smoke.add_argument(
        "--api-url",
        default=os.getenv("MEMORY_MCP_API_URL", DEFAULT_API_URL),
    )
    live_smoke.add_argument("--run-agent-cli", action="store_true")
    live_smoke.add_argument(
        "--strict-agent-cli",
        action="store_true",
        default=_bool(os.getenv("MEMORY_AGENT_CLI_STRICT", "false")),
        help=(
            "Fail live-smoke when a requested real agent CLI check is blocked or fails. "
            "Generated MCP checks remain strict regardless of this flag."
        ),
    )
    live_smoke.add_argument(
        "--agent-timeout-seconds",
        type=float,
        default=float(os.getenv("MEMORY_AGENT_CLI_TIMEOUT_SECONDS", "90")),
    )

    auth_doctor = subparsers.add_parser("agent-auth-doctor")
    auth_doctor.add_argument(
        "--agent-timeout-seconds",
        type=float,
        default=float(os.getenv("MEMORY_AGENT_CLI_TIMEOUT_SECONDS", "90")),
    )
    auth_doctor.add_argument("--strict", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "install-doctor":
            payload = run_install_doctor(
                strict_codex=args.strict_codex,
                skip_cli_lists=args.skip_cli_lists,
            )
        elif args.command == "live-smoke":
            payload = asyncio.run(
                run_live_smoke(
                    api_url=args.api_url,
                    auth_token=live_smoke_auth_token(),
                    run_agent_cli=args.run_agent_cli,
                    strict_agent_cli=args.strict_agent_cli,
                    agent_timeout_seconds=args.agent_timeout_seconds,
                )
            )
        else:
            payload = run_agent_auth_doctor(
                timeout=args.agent_timeout_seconds,
                strict=args.strict,
            )
    except Exception as exc:
        payload = {"ok": False, "error": exc.__class__.__name__, "message": redact_text(str(exc))}
        print(
            json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(redact_payload(payload), ensure_ascii=False, sort_keys=True))
    return 0 if payload.get("ok") is True else 1


def run_install_doctor(*, strict_codex: bool, skip_cli_lists: bool) -> dict[str, Any]:
    plugin_kit_ai = os.getenv("PLUGIN_KIT_AI", "plugin-kit-ai")
    list_result = run_command([plugin_kit_ai, "integrations", "list"], timeout=30)
    doctor_result = run_command([plugin_kit_ai, "integrations", "doctor"], timeout=60)
    failures: list[str] = []
    warnings: list[str] = []
    if not list_result["ok"]:
        failures.append("plugin-kit-ai integrations list failed")
    if not doctor_result["ok"]:
        failures.append("plugin-kit-ai integrations doctor failed")

    installation = load_plugin_installation(INTEGRATION_ID)
    gemini_hook_installation = load_plugin_installation(GEMINI_HOOK_INTEGRATION_ID)
    targets = installation.get("targets", {})
    if not isinstance(targets, dict):
        raise VerificationFailure("memo-stack-agent-plugin targets must be an object")
    gemini_hook_targets = gemini_hook_installation.get("targets", {})
    if not isinstance(gemini_hook_targets, dict):
        raise VerificationFailure("memo-stack-agent-plugin-gemini-hooks targets must be an object")

    required_installed = ("claude", "cursor", "opencode")
    target_checks: dict[str, dict[str, Any]] = {}

    for target in required_installed:
        check = target_state(targets, target)
        target_checks[target] = check
        if check["state"] != "installed":
            failures.append(f"{target} is {check['state']}, expected installed")
        if check.get("owned_paths_missing"):
            failures.append(f"{target} has missing owned paths")

    gemini_check = target_state(gemini_hook_targets, "gemini")
    target_checks["gemini_hooks"] = gemini_check
    if gemini_check["state"] != "installed":
        failures.append(f"gemini_hooks is {gemini_check['state']}, expected installed")
    if gemini_check.get("owned_paths_missing"):
        failures.append("gemini_hooks has missing owned paths")

    codex_check = target_state(targets, "codex")
    target_checks["codex"] = codex_check
    if codex_check["state"] == "installed":
        pass
    elif codex_check["state"] == "activation_pending":
        message = (
            "codex native activation is pending: install memo-stack-agent-plugin from "
            "the Codex Plugin Directory and start a new Codex thread"
        )
        if strict_codex:
            failures.append(message)
        else:
            warnings.append(message)
    else:
        failures.append(
            f"codex is {codex_check['state']}, expected installed or activation_pending"
        )

    cli_checks: dict[str, Any] = {}
    if not skip_cli_lists:
        cli_checks["claude"] = check_claude_plugin_list()
        cli_checks["gemini"] = check_gemini_extension_list()
        for name, check in cli_checks.items():
            if check["status"] == "failed":
                failures.append(f"{name} package list check failed: {check['reason']}")
            elif check["status"] == "blocked":
                warnings.append(f"{name} package list blocked: {check['reason']}")

    return {
        "ok": not failures,
        "integration_ids": [INTEGRATION_ID, GEMINI_HOOK_INTEGRATION_ID],
        "checks": {
            "plugin_kit_ai_list": list_result["ok"],
            "plugin_kit_ai_doctor": doctor_result["ok"],
            "state_file": True,
            "targets": target_checks,
            "cli_packages": cli_checks,
        },
        "warnings": warnings,
        "failures": failures,
    }


async def run_live_smoke(
    *,
    api_url: str,
    auth_token: str,
    run_agent_cli: bool,
    strict_agent_cli: bool,
    agent_timeout_seconds: float,
) -> dict[str, Any]:
    mcp_checks = {
        "codex_claude_cursor_package": await run_generated_mcp_status(
            plugin_root=PLUGIN_ROOT,
            config_relpath=".mcp.json",
            workspace_root=PLUGIN_ROOT,
            cwd=PLUGIN_ROOT,
            api_url=api_url,
            auth_token=auth_token,
            space_slug="agent-live-package",
            agent_name="agent-live-package",
        ),
        "gemini": await run_generated_mcp_status(
            plugin_root=GEMINI_HOOK_PLUGIN_ROOT,
            config_relpath="gemini-extension.json",
            workspace_root=GEMINI_HOOK_PLUGIN_ROOT,
            cwd=GEMINI_HOOK_PLUGIN_ROOT,
            api_url=api_url,
            auth_token=auth_token,
            space_slug="agent-live-gemini",
            agent_name="agent-live-gemini",
        ),
        "opencode": await run_generated_mcp_status(
            plugin_root=PLUGIN_ROOT,
            config_relpath="opencode.json",
            workspace_root=PLUGIN_ROOT,
            cwd=PLUGIN_ROOT,
            api_url=api_url,
            auth_token=auth_token,
            space_slug="agent-live-opencode",
            agent_name="agent-live-opencode",
        ),
        "cursor_workspace": await run_generated_mcp_status(
            plugin_root=CURSOR_WORKSPACE_PLUGIN_ROOT,
            config_relpath=".cursor/mcp.json",
            workspace_root=PROJECT_ROOT,
            cwd=PROJECT_ROOT,
            api_url=api_url,
            auth_token=auth_token,
            space_slug="agent-live-cursor-workspace",
            agent_name="agent-live-cursor-workspace",
        ),
    }

    agent_cli: dict[str, Any] = {}
    if run_agent_cli:
        agent_cli = run_agent_cli_smokes(
            api_url=api_url,
            auth_token=auth_token,
            timeout=agent_timeout_seconds,
        )

    generated_mcp_failures = [
        name
        for name, check in mcp_checks.items()
        if not isinstance(check, dict) or check.get("ok") is not True
    ]
    agent_cli_failures = [
        name
        for name, check in agent_cli.items()
        if not isinstance(check, dict) or check.get("status") != "ok"
    ]
    failures = list(generated_mcp_failures)
    if strict_agent_cli:
        failures.extend(f"agent_cli:{name}" for name in agent_cli_failures)
    report = {
        "suite": AGENT_LIVE_SMOKE_SUITE,
        "ok": not failures,
        "api_url": api_url,
        "checks": {
            "generated_mcp": mcp_checks,
            "agent_cli": agent_cli,
        },
        "strict_agent_cli": strict_agent_cli,
        "generated_mcp_failures": generated_mcp_failures,
        "agent_cli_failures": agent_cli_failures,
        "failures": failures,
    }
    return with_report_provenance(
        report,
        generated_by="scripts/agent_install_verification.py",
        suite=AGENT_LIVE_SMOKE_SUITE,
        project="memo-stack",
        cwd=PROJECT_ROOT,
    )


async def run_generated_mcp_status(
    *,
    plugin_root: Path,
    config_relpath: str,
    workspace_root: Path,
    cwd: Path,
    api_url: str,
    auth_token: str,
    space_slug: str,
    agent_name: str,
) -> dict[str, Any]:
    command_template, args, server_env = load_generated_mcp_server(plugin_root, config_relpath)
    command = resolve_command(command_template, plugin_root, workspace_root)
    if server_env.get("MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF") != NO_DEFAULT_THREAD_SENTINEL:
        raise VerificationFailure(f"{config_relpath} missing no-thread sentinel")
    if not command_exists(command, cwd):
        raise VerificationFailure(f"{config_relpath} command does not exist: {command}")

    env = os.environ.copy()
    env.update(server_env)
    env.update(
        {
            "MEMORY_MCP_API_URL": api_url,
            "MEMORY_MCP_AUTH_TOKEN": auth_token,
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": space_slug,
            "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
            "MEMORY_MCP_AGENT_NAME": agent_name,
            "MEMORY_MCP_TRANSPORT": "stdio",
        }
    )
    params = StdioServerParameters(command=command, args=args, env=env, cwd=str(cwd))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        if "memory_status" not in tool_names:
            raise VerificationFailure(f"{config_relpath} missing memory_status")
        result = await session.call_tool("memory_status", {})
        if result.isError:
            raise VerificationFailure(f"{config_relpath} memory_status returned MCP error")
        payload = structured_payload(result)
        dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if auth_token in dumped or NO_DEFAULT_THREAD_SENTINEL in dumped:
            raise VerificationFailure(f"{config_relpath} leaked token or sentinel")
        return {
            "ok": payload.get("ok") is True,
            "tool_count": len(tool_names),
            "space_slug": payload.get("data", {})
            .get("default_scope", {})
            .get("space_slug"),
            "memory_scope_external_ref": payload.get("data", {})
            .get("default_scope", {})
            .get("memory_scope_external_ref"),
        }


def run_agent_cli_smokes(
    *,
    api_url: str = DEFAULT_API_URL,
    auth_token: str = DEFAULT_AUTH_TOKEN,
    timeout: float,
) -> dict[str, Any]:
    prompt = (
        "Call the Memo Stack MCP tool memory_status. "
        "Then reply with exactly: memory_status_checked."
    )
    gemini_prompt = (
        "Use the Gemini MCP tool named mcp_memo-stack_memory_status with empty args. "
        "Do not call shell tools, subagents, or file tools. "
        "After the MCP call succeeds, reply with exactly: memory_status_checked."
    )
    memory_mcp_bin = str(PLUGIN_ROOT / "bin" / "memo-stack-mcp")
    agent_env = {
        "MEMORY_MCP_API_URL": api_url,
        "MEMORY_MCP_AUTH_TOKEN": auth_token,
        "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
        "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF": NO_DEFAULT_THREAD_SENTINEL,
        "MEMORY_MCP_WRITE_MODE": "suggest",
        "MEMORY_MCP_DELETE_MODE": "off",
        "MEMORY_MCP_INGEST_MODE": "small_docs",
        "MEMORY_MCP_TRANSPORT": "stdio",
        "MEMORY_MCP_RUNTIME_API_URL": api_url,
        "MEMORY_MCP_RUNTIME_AUTH_TOKEN": auth_token,
        "MEMORY_MCP_RUNTIME_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
        "MEMORY_MCP_RUNTIME_DEFAULT_THREAD_EXTERNAL_REF": NO_DEFAULT_THREAD_SENTINEL,
        "MEMORY_MCP_RUNTIME_WRITE_MODE": "suggest",
        "MEMORY_MCP_RUNTIME_DELETE_MODE": "off",
        "MEMORY_MCP_RUNTIME_INGEST_MODE": "small_docs",
        "MEMORY_MCP_RUNTIME_TRANSPORT": "stdio",
    }
    commands = {
        "claude": [
            "claude",
            "-p",
            "--max-budget-usd",
            "0.20",
            "--plugin-dir",
            str(PLUGIN_ROOT),
            prompt,
        ],
        "gemini": [
            "gemini",
            "-p",
            gemini_prompt,
            "--extensions",
            GEMINI_HOOK_INTEGRATION_ID,
            "--allowed-mcp-server-names",
            "memo-stack",
            "--output-format",
            "json",
        ],
        "opencode": ["opencode", "run", prompt],
        "codex": [
            "codex",
            "-c",
            f'mcp_servers.memo-stack.command="{memory_mcp_bin}"',
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            prompt,
        ],
    }
    preflight_checks: dict[str, dict[str, Any]] = {
        "gemini": check_gemini_extension_runtime_config(
            expected_api_url=api_url,
            expected_auth_token=auth_token,
            runtime_override_api_url=api_url,
            runtime_override_auth_token_present=bool(auth_token),
            timeout=timeout,
        )
    }
    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
        futures = {
            name: executor.submit(
                run_agent_command,
                name,
                argv,
                timeout=timeout,
                expected_marker="memory_status_checked",
                extra_env={
                    **agent_env,
                    "MEMORY_MCP_DEFAULT_SPACE_SLUG": f"agent-live-{name}",
                    "MEMORY_MCP_AGENT_NAME": f"agent-live-{name}",
                    "MEMORY_MCP_RUNTIME_DEFAULT_SPACE_SLUG": f"agent-live-{name}",
                    "MEMORY_MCP_RUNTIME_AGENT_NAME": f"agent-live-{name}",
                },
            )
            for name, argv in commands.items()
            if preflight_checks.get(name, {}).get("status", "ok") == "ok"
        }
        checks = {
            name: (
                _agent_future_result(name, futures[name])
                if name in futures
                else preflight_checks[name]
            )
            for name in commands
        }

    for check in checks.values():
        marker_seen = check.get("expected_marker_seen") is True or (
            "memory_status_checked" in check.get("stdout", "")
        )
        if check["status"] == "ok" and not marker_seen:
            check["status"] = "blocked"
            check["reason"] = agent_block_reason(
                check.get("stdout", ""),
                check.get("stderr_tail", ""),
            )
            check["stdout_tail"] = check.get("stdout", "")[-2000:]
            check.pop("stdout", None)
        elif check["status"] == "ok":
            check.pop("expected_marker_seen", None)
    return checks


def run_agent_auth_doctor(*, timeout: float, strict: bool) -> dict[str, Any]:
    checks = run_plain_agent_auth_checks(timeout=timeout)
    failures = [
        name
        for name, check in checks.items()
        if not isinstance(check, dict) or check.get("status") != "ok"
    ]
    return {
        "ok": not failures if strict else True,
        "strict": strict,
        "checks": checks,
        "failures": failures,
    }


def run_plain_agent_auth_checks(*, timeout: float) -> dict[str, Any]:
    commands = {
        "claude": (
            ["claude", "-p", "--max-budget-usd", "0.05", "Reply exactly: claude_auth_ok"],
            "claude_auth_ok",
        ),
        "gemini": (
            [
                "gemini",
                "-p",
                "Reply exactly: gemini_auth_ok",
                "--extensions",
                "",
                "--output-format",
                "json",
            ],
            "gemini_auth_ok",
        ),
        "opencode": (
            ["opencode", "run", "Reply exactly: opencode_auth_ok"],
            "opencode_auth_ok",
        ),
        "codex": (
            [
                "codex",
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "Reply exactly: codex_auth_ok",
            ],
            "codex_auth_ok",
        ),
    }
    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
        futures = {
            name: executor.submit(
                run_agent_command,
                name,
                argv,
                timeout=timeout,
                expected_marker=marker,
                extra_env={},
            )
            for name, (argv, marker) in commands.items()
        }
        return {
            name: _agent_future_result(name, futures[name])
            for name in commands
        }


def _agent_future_result(name: str, future: Any) -> dict[str, Any]:
    try:
        return future.result()
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": f"{name} check failed: {redact_text(str(exc))}",
        }


def run_agent_command(
    name: str,
    argv: list[str],
    *,
    timeout: float,
    expected_marker: str,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if shutil.which(argv[0]) is None:
        return {"status": "blocked", "reason": f"{argv[0]} not found"}
    completed = run_bounded_command(argv, timeout=timeout, extra_env=extra_env)
    full_stdout = redact_text(completed["stdout"])
    stdout = full_stdout[-2000:]
    stderr = redact_text(completed["stderr"])[-2000:]
    expected_marker_seen = expected_marker in full_stdout
    if completed["timed_out"]:
        return {
            "status": "blocked",
            "reason": f"{name} timed out after {timeout:g}s",
            "stdout_tail": stdout,
            "stderr_tail": stderr,
        }
    if completed["returncode"] != 0:
        return {
            "status": "blocked",
            "reason": agent_block_reason(
                stdout,
                stderr,
                fallback=f"{name} exited {completed['returncode']}",
            ),
            "stdout_tail": stdout,
            "stderr_tail": stderr,
        }
    tool_error_reason = agent_tool_error_reason(stdout, stderr)
    if tool_error_reason:
        return {
            "status": "blocked",
            "reason": tool_error_reason,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
            "expected_marker_seen": expected_marker_seen,
        }
    if not expected_marker_seen:
        return {
            "status": "blocked",
            "reason": agent_block_reason(stdout, stderr),
            "stdout_tail": stdout,
            "stderr_tail": stderr,
        }
    return {
        "status": "ok",
        "stdout": stdout,
        "stderr_tail": stderr,
        "expected_marker_seen": expected_marker_seen,
    }


def agent_tool_error_reason(stdout: str, stderr: str) -> str | None:
    combined = f"{stdout}\n{stderr}".lower()
    if "error executing tool" in combined:
        return "agent MCP tool blocked: tool execution error"
    if "mcp tool" in combined and "reported an error" in combined:
        return "agent MCP tool blocked: memory tool reported an error"
    return None


def agent_block_reason(stdout: str, stderr: str, *, fallback: str | None = None) -> str:
    tool_error_reason = agent_tool_error_reason(stdout, stderr)
    if tool_error_reason:
        return tool_error_reason
    combined = f"{stdout}\n{stderr}".lower()
    if "failed to authenticate" in combined or "invalid authentication credentials" in combined:
        return "agent auth blocked: invalid authentication credentials"
    if "token refresh failed" in combined or " 401" in combined or "401 " in combined:
        return "agent auth blocked: token refresh failed"
    return fallback or "agent completed but did not provide the expected marker"


def check_claude_plugin_list() -> dict[str, Any]:
    if shutil.which("claude") is None:
        return {"status": "blocked", "reason": "claude not found"}
    result = run_command(["claude", "plugin", "list", "--json"], timeout=60)
    if not result["ok"]:
        return {"status": "blocked", "reason": "claude plugin list failed"}
    try:
        plugins = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return {"status": "blocked", "reason": "claude plugin list returned non-json"}
    found = any(str(item.get("id", "")).startswith(f"{INTEGRATION_ID}@") for item in plugins)
    return {"status": "ok" if found else "failed", "found": found}


def check_gemini_extension_list() -> dict[str, Any]:
    if shutil.which("gemini") is None:
        return {"status": "blocked", "reason": "gemini not found"}
    result = run_command(["gemini", "extensions", "list", "--output-format", "json"], timeout=60)
    if not result["ok"]:
        return {"status": "blocked", "reason": "gemini extensions list failed"}
    raw = result["stdout"].strip() or result["stderr"].strip()
    try:
        extensions = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "blocked", "reason": "gemini extensions list returned non-json"}
    found = any(str(item.get("name", "")) == GEMINI_HOOK_INTEGRATION_ID for item in extensions)
    return {"status": "ok" if found else "failed", "found": found}


def check_gemini_extension_runtime_config(
    *,
    expected_api_url: str,
    expected_auth_token: str,
    runtime_override_api_url: str | None = None,
    runtime_override_auth_token_present: bool = False,
    timeout: float = 60,
) -> dict[str, Any]:
    if shutil.which("gemini") is None:
        return {"status": "blocked", "reason": "gemini not found"}
    result = run_command(
        ["gemini", "extensions", "list", "--output-format", "json"],
        timeout=timeout,
    )
    if not result["ok"]:
        return {"status": "blocked", "reason": "gemini extensions list failed"}
    raw = result["stdout"].strip() or result["stderr"].strip()
    try:
        extensions = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "blocked", "reason": "gemini extensions list returned non-json"}
    for item in extensions:
        if str(item.get("name", "")) != GEMINI_HOOK_INTEGRATION_ID:
            continue
        mcp_servers = item.get("mcpServers") or {}
        server = mcp_servers.get(MCP_SERVER_ALIAS) or {}
        env = server.get("env") or {}
        actual_api_url = str(env.get("MEMORY_MCP_API_URL", "")).strip()
        actual_token = str(env.get("MEMORY_MCP_AUTH_TOKEN", ""))
        if (
            actual_api_url
            and actual_api_url != expected_api_url
            and runtime_override_api_url != expected_api_url
        ):
            return {
                "status": "blocked",
                "reason": (
                    "gemini installed extension targets "
                    f"{actual_api_url}, not {expected_api_url}"
                ),
                "configured_api_url": actual_api_url,
                "runtime_override_api_url": runtime_override_api_url or "<not-set>",
            }
        if (
            actual_token
            and actual_token != expected_auth_token
            and not runtime_override_auth_token_present
        ):
            return {
                "status": "blocked",
                "reason": (
                    "gemini installed extension auth token does not match "
                    "live-smoke token"
                ),
                "runtime_override_auth_token": "<not-set>",
            }
        return {
            "status": "ok",
            "configured_api_url": actual_api_url or "<inherits-process-env>",
            "configured_auth_token": "<set>" if actual_token else "<inherits-process-env>",
            "runtime_override_api_url": runtime_override_api_url or "<not-set>",
            "runtime_override_auth_token": (
                "<set>" if runtime_override_auth_token_present else "<not-set>"
            ),
        }
    return {
        "status": "blocked",
        "reason": "gemini memo-stack-agent-plugin-gemini-hooks extension not installed",
    }


def load_plugin_installation(integration_id: str = INTEGRATION_ID) -> dict[str, Any]:
    state_path = Path(
        os.getenv("PLUGIN_KIT_AI_STATE_PATH", str(Path.home() / ".plugin-kit-ai" / "state.json"))
    )
    if not state_path.exists():
        raise VerificationFailure(f"plugin-kit-ai state file not found: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    installations = state.get("installations")
    if not isinstance(installations, list):
        raise VerificationFailure("plugin-kit-ai state must contain installations list")
    for installation in installations:
        if installation.get("integration_id") == integration_id:
            return installation
    raise VerificationFailure(f"{integration_id} is not present in plugin-kit-ai state")


def target_state(targets: Mapping[str, Any], target: str) -> dict[str, Any]:
    raw = targets.get(target)
    if not isinstance(raw, dict):
        return {"state": "missing", "activation_state": "missing", "owned_paths_missing": []}
    missing_paths: list[str] = []
    for obj in raw.get("owned_native_objects") or []:
        if not isinstance(obj, dict):
            continue
        path = obj.get("path")
        if isinstance(path, str) and path and not Path(path).exists():
            missing_paths.append(path)
    return {
        "state": str(raw.get("state", "unknown")),
        "activation_state": str(raw.get("activation_state", "unknown")),
        "delivery_kind": str(raw.get("delivery_kind", "unknown")),
        "owned_paths_missing": missing_paths,
    }


def load_generated_mcp_server(
    plugin_root: Path,
    config_relpath: str,
) -> tuple[str, list[str], dict[str, str]]:
    path = plugin_root / config_relpath
    if not path.exists():
        raise VerificationFailure(f"generated MCP config is missing: {path}")
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if "mcp" in parsed:
        servers = parsed["mcp"]
        env_key = "environment"
    else:
        servers = parsed.get("mcpServers", parsed)
        env_key = "env"
    server = servers.get(MCP_SERVER_ALIAS)
    if not isinstance(server, dict):
        raise VerificationFailure(
            f"generated MCP config {config_relpath} is missing {MCP_SERVER_ALIAS}"
        )
    command_value = server["command"]
    if isinstance(command_value, list):
        command = str(command_value[0])
        args = [str(arg) for arg in command_value[1:]]
    else:
        command = str(command_value)
        args = [str(arg) for arg in server.get("args", [])]
    env = {str(key): str(value) for key, value in server.get(env_key, {}).items()}
    return command, args, env


def resolve_command(command: str, plugin_root: Path, workspace_root: Path) -> str:
    return (
        command.replace("${package.root}", str(plugin_root))
        .replace("${workspaceFolder}", str(workspace_root))
        .replace("${extensionPath}", str(plugin_root))
    )


def command_exists(command: str, cwd: Path) -> bool:
    command_path = Path(command)
    return command_path.exists() if command_path.is_absolute() else (cwd / command_path).exists()


def structured_payload(result: Any) -> dict[str, Any]:
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


def run_command(argv: list[str], *, timeout: float) -> dict[str, Any]:
    if shutil.which(argv[0]) is None:
        return {"ok": False, "stdout": "", "stderr": f"{argv[0]} not found"}
    completed = run_bounded_command(argv, timeout=timeout)
    if completed["timed_out"]:
        return {"ok": False, "stdout": "", "stderr": f"{argv[0]} timed out"}
    return {
        "ok": completed["returncode"] == 0,
        "stdout": redact_text(completed["stdout"]),
        "stderr": redact_text(completed["stderr"]),
    }


def run_bounded_command(
    argv: list[str],
    *,
    timeout: float,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    try:
        env = os.environ.copy()
        if extra_env:
            env.update({str(key): str(value) for key, value in extra_env.items()})
        process = subprocess.Popen(
            argv,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "", "timed_out": True}
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return {
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return {
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
        }


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                redacted["<redacted>"] = "<redacted>"
            else:
                redacted[str(key)] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, str):
        return redact_text(payload)
    return payload


def redact_text(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        if value and len(value) >= 8 and SENSITIVE_KEY_RE.search(key):
            redacted = redacted.replace(value, "<redacted>")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
