import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from infinity_context_server_harness import run_infinity_context_server
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "infinity-context-agent-plugin"
CURSOR_WORKSPACE_PLUGIN_ROOT = (
    PROJECT_ROOT / "plugins" / "infinity-context-agent-plugin-cursor-workspace"
)
GEMINI_HOOK_PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "infinity-context-agent-plugin-gemini-hooks"
DOCTOR_PLUGIN_ROOTS = (PLUGIN_ROOT, CURSOR_WORKSPACE_PLUGIN_ROOT, GEMINI_HOOK_PLUGIN_ROOT)
NO_DEFAULT_THREAD_SENTINEL = "__INFINITY_CONTEXT_NO_DEFAULT_THREAD__"


def test_generated_plugin_package_manifests_reference_existing_artifacts() -> None:
    manifests = [
        PLUGIN_ROOT / ".codex-plugin" / "plugin.json",
        PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
        PLUGIN_ROOT / ".cursor-plugin" / "plugin.json",
    ]
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["name"] == "infinity-context-agent-plugin"
        mcp_path = PLUGIN_ROOT / manifest["mcpServers"]
        assert mcp_path.exists(), f"{manifest_path} references missing {mcp_path}"
        skills_relpath = manifest.get("skills")
        if skills_relpath is not None:
            skills_path = PLUGIN_ROOT / skills_relpath
            assert skills_path.exists(), f"{manifest_path} references missing {skills_path}"
            assert (skills_path / "memory" / "SKILL.md").exists()


def test_generated_plugin_inventory_matches_existing_outputs() -> None:
    assert _generated_outputs(PLUGIN_ROOT) == {
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
        ".cursor-plugin/plugin.json",
        ".mcp.json",
        ".opencode/skills/memory/SKILL.md",
        "GENERATED.md",
        "gemini-extension.json",
        "hooks/hooks.json",
        "opencode.json",
        "skills/memory/SKILL.md",
    }
    assert _generated_outputs(CURSOR_WORKSPACE_PLUGIN_ROOT) == {
        ".cursor/mcp.json",
        "GENERATED.md",
    }
    assert _generated_outputs(GEMINI_HOOK_PLUGIN_ROOT) == {
        "GENERATED.md",
        "gemini-extension.json",
        "hooks/hooks.json",
        "skills/memory/SKILL.md",
    }


def test_generated_memory_agent_plugin_mcp_status_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        asyncio.run(
            _run_generated_plugin_status(
                plugin_root=PLUGIN_ROOT,
                config_relpath=".mcp.json",
                base_url=server.base_url,
                token=server.token,
                space_slug="plugin-e2e",
                agent_name="plugin-e2e-agent",
                workspace_root=PLUGIN_ROOT,
                cwd=PLUGIN_ROOT,
            )
        )


def test_generated_package_agent_mcp_surfaces_status_e2e(tmp_path: Path) -> None:
    generated_configs = [
        ("gemini-extension.json", "plugin-gemini-e2e", "plugin-gemini-agent"),
        ("opencode.json", "plugin-opencode-e2e", "plugin-opencode-agent"),
    ]
    with run_infinity_context_server(tmp_path) as server:
        for config_relpath, space_slug, agent_name in generated_configs:
            asyncio.run(
                _run_generated_plugin_status(
                    plugin_root=PLUGIN_ROOT,
                    config_relpath=config_relpath,
                    base_url=server.base_url,
                    token=server.token,
                    space_slug=space_slug,
                    agent_name=agent_name,
                    workspace_root=PLUGIN_ROOT,
                    cwd=PLUGIN_ROOT,
                )
            )


def test_generated_gemini_hook_plugin_mcp_surfaces_status_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        asyncio.run(
            _run_generated_plugin_status(
                plugin_root=GEMINI_HOOK_PLUGIN_ROOT,
                config_relpath="gemini-extension.json",
                base_url=server.base_url,
                token=server.token,
                space_slug="plugin-gemini-hooks-e2e",
                agent_name="plugin-gemini-hooks-agent",
                workspace_root=GEMINI_HOOK_PLUGIN_ROOT,
                cwd=GEMINI_HOOK_PLUGIN_ROOT,
            )
        )


def test_generated_plugin_hook_retrieves_memory_context_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        _remember_fact(
            base_url=server.base_url,
            token=server.token,
            space_slug="plugin-hook-e2e",
            memory_scope_ref="default",
            text="The Infinity Context hook e2e marker color is teal.",
        )
        env = os.environ.copy()
        env.update(
            {
                "MEMORY_MCP_API_URL": server.base_url,
                "MEMORY_MCP_AUTH_TOKEN": server.token,
                "MEMORY_MCP_DEFAULT_SPACE_SLUG": "plugin-hook-e2e",
                "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
                "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF": NO_DEFAULT_THREAD_SENTINEL,
                "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "UserPromptSubmit",
            }
        )
        completed = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "infinity-context-plugin-hook"), "UserPromptSubmit"],
            cwd=PLUGIN_ROOT,
            env=env,
            input=json.dumps({"prompt": "What is the hook e2e marker color?"}),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    output = f"{completed.stdout}\n{completed.stderr}"
    assert '<memory_context source="infinity-context" event="UserPromptSubmit">' in completed.stdout
    assert "teal" in completed.stdout
    assert server.token not in output
    assert NO_DEFAULT_THREAD_SENTINEL not in output


def test_generated_gemini_hook_plugin_before_agent_context_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        _remember_fact(
            base_url=server.base_url,
            token=server.token,
            space_slug="plugin-gemini-hook-e2e",
            memory_scope_ref="default",
            text="The Gemini hook e2e marker database is Neo4j.",
        )
        env = os.environ.copy()
        env.update(
            {
                "MEMORY_MCP_API_URL": server.base_url,
                "MEMORY_MCP_AUTH_TOKEN": server.token,
                "MEMORY_MCP_DEFAULT_SPACE_SLUG": "plugin-gemini-hook-e2e",
                "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
                "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF": NO_DEFAULT_THREAD_SENTINEL,
                "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "BeforeAgent",
            }
        )
        completed = subprocess.run(
            [
                str(GEMINI_HOOK_PLUGIN_ROOT / "bin" / "infinity-context-plugin-hook"),
                "GeminiBeforeAgent",
            ],
            cwd=GEMINI_HOOK_PLUGIN_ROOT,
            env=env,
            input=json.dumps(
                {
                    "session_id": "s",
                    "hook_event_name": "BeforeAgent",
                    "prompt": "Which database backs the Gemini hook marker?",
                }
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    output = f"{completed.stdout}\n{completed.stderr}"
    payload = json.loads(completed.stdout)
    hook_output = payload["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "BeforeAgent"
    assert "Treat retrieved memory as evidence" in hook_output["additionalContext"]
    assert "Neo4j" in hook_output["additionalContext"]
    assert "<memory_context" not in completed.stdout
    assert server.token not in output
    assert NO_DEFAULT_THREAD_SENTINEL not in output


def test_generated_plugin_hook_writes_capture_to_memory_server_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(
        tmp_path,
        extra_env={
            "MEMORY_CAPTURE_MODE": "suggest",
            "MEMORY_CAPTURE_DEFAULT_CONSOLIDATE": "true",
        },
    ) as server:
        env = os.environ.copy()
        env.update(
            {
                "MEMORY_MCP_API_URL": server.base_url,
                "MEMORY_MCP_AUTH_TOKEN": server.token,
                "MEMORY_MCP_DEFAULT_SPACE_SLUG": "plugin-hook-capture-e2e",
                "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
                "MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF": NO_DEFAULT_THREAD_SENTINEL,
                "MEMORY_MCP_AGENT_NAME": "plugin-hook-capture-e2e-agent",
                "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "",
                "MEMORY_CAPTURE_MODE": "suggest",
                "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": "UserPromptSubmit",
            }
        )
        completed = subprocess.run(
            [str(PLUGIN_ROOT / "bin" / "infinity-context-plugin-hook"), "UserPromptSubmit"],
            cwd=PLUGIN_ROOT,
            env=env,
            input=json.dumps(
                {"prompt": "Remember: HOOK_CAPTURE_E2E_MARKER Graphiti is the temporal graph."}
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        headers = {"Authorization": f"Bearer {server.token}"}
        listed = httpx.get(
            f"{server.base_url}/v1/captures",
            params={
                "space_slug": "plugin-hook-capture-e2e",
                "memory_scope_external_ref": "default",
                "status": "accepted",
            },
            headers=headers,
            timeout=10,
        )
        listed.raise_for_status()
        capture = listed.json()["data"][0]
        consolidated = httpx.post(
            f"{server.base_url}/v1/captures/{capture['id']}/consolidate",
            json={},
            headers=headers,
            timeout=10,
        )
        consolidated.raise_for_status()
        suggestions = httpx.get(
            f"{server.base_url}/v1/suggestions",
            params={
                "space_slug": "plugin-hook-capture-e2e",
                "memory_scope_external_ref": "default",
                "status": "pending",
            },
            headers=headers,
            timeout=10,
        )
        suggestions.raise_for_status()

    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.stdout == ""
    assert "capture accepted" not in completed.stderr
    assert completed.stderr == ""
    assert server.token not in output
    assert NO_DEFAULT_THREAD_SENTINEL not in output
    assert capture["consolidation_status"] == "pending"
    assert "HOOK_CAPTURE_E2E_MARKER" in capture["text_preview"]
    assert "raw_payload" not in capture
    assert consolidated.json()["data"]["created_suggestions"] == 1
    suggestion = suggestions.json()["data"][0]
    assert suggestion["created_from_capture_id"] == capture["id"]
    assert "HOOK_CAPTURE_E2E_MARKER" in suggestion["candidate_text"]


def test_generated_plugin_hook_fails_open_without_leaking_token() -> None:
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_MCP_API_URL": "http://127.0.0.1:9",
            "MEMORY_MCP_AUTH_TOKEN": "hook-secret-token",
            "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "UserPromptSubmit",
        }
    )
    completed = subprocess.run(
        [str(PLUGIN_ROOT / "bin" / "infinity-context-plugin-hook"), "UserPromptSubmit"],
        cwd=PLUGIN_ROOT,
        env=env,
        input=json.dumps({"prompt": "Can memory respond?"}),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0
    assert completed.stdout == ""
    assert "context unavailable" in completed.stderr
    assert "hook-secret-token" not in output


def test_generated_plugin_hooks_reference_existing_runner() -> None:
    hooks_path = PLUGIN_ROOT / "hooks" / "hooks.json"
    parsed = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands = {
        command["command"]
        for entries in parsed["hooks"].values()
        for entry in entries
        for command in entry["hooks"]
        if command["type"] == "command"
    }
    assert commands == {
        "./bin/infinity-context-plugin-hook UserPromptSubmit",
        "./bin/infinity-context-plugin-hook Stop",
    }
    assert (PLUGIN_ROOT / "bin" / "infinity-context-plugin-hook").exists()


def test_generated_gemini_hook_plugin_hooks_reference_existing_runner() -> None:
    hooks_path = GEMINI_HOOK_PLUGIN_ROOT / "hooks" / "hooks.json"
    parsed = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands = {
        command["command"]
        for entries in parsed["hooks"].values()
        for entry in entries
        for command in entry["hooks"]
        if command["type"] == "command"
    }
    assert commands == {
        "${extensionPath}${/}bin${/}infinity-context-plugin-hook GeminiSessionStart",
        "${extensionPath}${/}bin${/}infinity-context-plugin-hook GeminiBeforeAgent",
        "${extensionPath}${/}bin${/}infinity-context-plugin-hook GeminiAfterAgent",
        "${extensionPath}${/}bin${/}infinity-context-plugin-hook GeminiSessionEnd",
    }
    assert (GEMINI_HOOK_PLUGIN_ROOT / "bin" / "infinity-context-plugin-hook").exists()


def test_materialized_gemini_hook_wrapper_resolves_source_root_marker(
    tmp_path: Path,
) -> None:
    materialized_root = (
        tmp_path / "materialized" / "gemini" / "infinity-context-agent-plugin-gemini-hooks"
    )
    shutil.copytree(GEMINI_HOOK_PLUGIN_ROOT, materialized_root)
    (materialized_root / ".infinity-context-source-root").write_text(
        f"{PROJECT_ROOT}\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "",
            "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": "",
        }
    )

    completed = subprocess.run(
        [str(materialized_root / "bin" / "infinity-context-plugin-hook"), "GeminiSessionEnd"],
        cwd=PROJECT_ROOT,
        env=env,
        input=json.dumps({"session_id": "s", "hook_event_name": "SessionEnd"}),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert json.loads(completed.stdout) == {}
    assert "Infinity Context packages not found" not in completed.stderr


def test_generated_cursor_workspace_plugin_mcp_status_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        asyncio.run(
            _run_generated_plugin_status(
                plugin_root=CURSOR_WORKSPACE_PLUGIN_ROOT,
                config_relpath=".cursor/mcp.json",
                base_url=server.base_url,
                token=server.token,
                space_slug="plugin-cursor-workspace-e2e",
                agent_name="plugin-cursor-workspace-e2e-agent",
                workspace_root=PROJECT_ROOT,
                cwd=PROJECT_ROOT,
            )
        )


def test_memory_agent_plugin_doctors_do_not_echo_token_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        for plugin_root in DOCTOR_PLUGIN_ROOTS:
            env = os.environ.copy()
            env.update(
                {
                    "MEMORY_MCP_API_URL": server.base_url,
                    "MEMORY_MCP_AUTH_TOKEN": server.token,
                }
            )
            completed = subprocess.run(
                [str(plugin_root / "bin" / "infinity-context-mcp-doctor")],
                cwd=plugin_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = f"{completed.stdout}\n{completed.stderr}"
            assert "Infinity Context MCP plugin is ready" in output
            assert server.token not in output


def test_memory_agent_plugin_doctors_accept_service_token_fallback_e2e(tmp_path: Path) -> None:
    with run_infinity_context_server(tmp_path) as server:
        for plugin_root in DOCTOR_PLUGIN_ROOTS:
            env = os.environ.copy()
            env.pop("MEMORY_MCP_AUTH_TOKEN", None)
            env.update(
                {
                    "MEMORY_MCP_API_URL": server.base_url,
                    "MEMORY_SERVICE_TOKEN": server.token,
                }
            )
            completed = subprocess.run(
                [str(plugin_root / "bin" / "infinity-context-mcp-doctor")],
                cwd=plugin_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = f"{completed.stdout}\n{completed.stderr}"
            assert "Infinity Context MCP plugin is ready" in output
            assert server.token not in output


def test_memory_agent_plugin_doctors_redact_failed_url_diagnostics_e2e() -> None:
    secrets = {
        "doctor-user",
        "doctor-password",
        "port-secret",
        "query-secret",
        "fragment-secret",
        "doctor-secret-token",
    }
    for plugin_root in DOCTOR_PLUGIN_ROOTS:
        env = os.environ.copy()
        env.update(
            {
                "MEMORY_MCP_API_URL": (
                    "http://doctor-user:doctor-password@127.0.0.1:port-secret"
                    "/memory?api_key=query-secret#fragment-secret"
                ),
                "MEMORY_MCP_AUTH_TOKEN": "doctor-secret-token",
            }
        )
        completed = subprocess.run(
            [str(plugin_root / "bin" / "infinity-context-mcp-doctor")],
            cwd=plugin_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        assert completed.returncode != 0
        assert "<redacted>" in output
        for secret in secrets:
            assert secret not in output


def test_agent_install_live_smoke_strict_agent_cli_failures_are_hard_gate(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-agent-bin"
    fake_bin.mkdir()
    for command in ("claude", "opencode", "codex"):
        _write_fake_agent_cli(fake_bin / command, "printf 'memory_status_checked\\n'\n")
    _write_fake_agent_cli(fake_bin / "gemini", "sleep 30\n")

    with run_infinity_context_server(tmp_path) as server:
        env = os.environ.copy()
        env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
        env["MEMORY_MCP_AUTH_TOKEN"] = server.token
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/agent_install_verification.py",
                "live-smoke",
                "--api-url",
                server.base_url,
                "--run-agent-cli",
                "--strict-agent-cli",
                "--agent-timeout-seconds",
                "2",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["generated_mcp_failures"] == []
    assert payload["agent_cli_failures"] == ["gemini"]
    assert payload["failures"] == ["agent_cli:gemini"]
    assert payload["checks"]["agent_cli"]["claude"]["status"] == "ok"
    assert payload["checks"]["agent_cli"]["gemini"]["status"] == "blocked"


def test_agent_install_doctor_plugin_kit_failure_is_hard_gate(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-plugin-kit-bin"
    fake_bin.mkdir()
    _write_fake_agent_cli(
        fake_bin / "plugin-kit-ai",
        """
if [ "$1" = "integrations" ] && [ "$2" = "list" ]; then
  printf 'ok\\n'
  exit 0
fi
if [ "$1" = "integrations" ] && [ "$2" = "doctor" ]; then
  printf 'doctor failed\\n' >&2
  exit 17
fi
exit 99
""",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "installations": [
                    {
                        "integration_id": "infinity-context-agent-plugin",
                        "targets": {
                            "claude": _target("installed"),
                            "cursor": _target("installed"),
                            "opencode": _target("installed"),
                            "codex": _target("installed"),
                        },
                    },
                    {
                        "integration_id": "infinity-context-agent-plugin-gemini-hooks",
                        "targets": {"gemini": _target("installed")},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.pop("PLUGIN_KIT_AI", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["PLUGIN_KIT_AI_STATE_PATH"] = str(state_path)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/agent_install_verification.py",
            "install-doctor",
            "--skip-cli-lists",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["checks"]["plugin_kit_ai_list"] is True
    assert payload["checks"]["plugin_kit_ai_doctor"] is False
    assert payload["failures"] == ["plugin-kit-ai integrations doctor failed"]


async def _run_generated_plugin_status(
    *,
    plugin_root: Path,
    config_relpath: str,
    base_url: str,
    token: str,
    space_slug: str,
    agent_name: str,
    workspace_root: Path,
    cwd: Path,
) -> None:
    command_template, args, server_env = _load_generated_mcp_server(plugin_root, config_relpath)
    command = _resolve_command(command_template, plugin_root, workspace_root)
    assert server_env["MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF"] == NO_DEFAULT_THREAD_SENTINEL
    assert _command_exists(command, cwd)
    env = os.environ.copy()
    env.update(server_env)
    env.update(
        {
            "MEMORY_MCP_API_URL": base_url,
            "MEMORY_MCP_AUTH_TOKEN": token,
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": space_slug,
            "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
            "MEMORY_MCP_AGENT_NAME": agent_name,
            "MEMORY_MCP_TRANSPORT": "stdio",
        }
    )
    params = StdioServerParameters(
        command=command,
        args=args,
        env=env,
        cwd=str(cwd),
    )

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}
        assert "memory_status" in tool_names
        assert "memory_search" in tool_names
        assert "memory_insights" in tool_names
        result = await session.call_tool("memory_status", {})
        assert result.isError is False
        payload = _structured(result)
        assert payload["ok"] is True
        assert payload["data"]["default_scope"]["space_slug"] == space_slug
        assert payload["data"]["default_scope"]["memory_scope_external_ref"] == "default"
        assert payload["data"]["default_scope"].get("thread_external_ref") is None
        dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert token not in dumped
        assert NO_DEFAULT_THREAD_SENTINEL not in dumped


def _load_generated_mcp_server(
    plugin_root: Path, config_relpath: str
) -> tuple[str, list[str], dict[str, str]]:
    path = plugin_root / config_relpath
    assert path.exists(), f"Run plugin-kit-ai generate {plugin_root} first"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    if "mcp" in parsed:
        servers = parsed["mcp"]
        env_key = "environment"
    else:
        servers = parsed.get("mcpServers", parsed)
        env_key = "env"

    assert isinstance(servers, dict)
    assert "infinity-context" in servers
    server = servers["infinity-context"]
    assert isinstance(server, dict)
    command_value = server["command"]
    if isinstance(command_value, list):
        assert command_value
        command = str(command_value[0])
        args = [str(arg) for arg in command_value[1:]]
    else:
        command = str(command_value)
        args = [str(arg) for arg in server.get("args", [])]
    server_env = {str(key): str(value) for key, value in server.get(env_key, {}).items()}
    return command, args, server_env


def _remember_fact(
    *,
    base_url: str,
    token: str,
    space_slug: str,
    memory_scope_ref: str,
    text: str,
) -> None:
    response = httpx.post(
        f"{base_url}/v1/facts",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "plugin-hook-e2e-fact",
        },
        json={
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_ref,
            "text": text,
            "kind": "note",
            "classification": "internal",
            "source_refs": [
                {
                    "source_type": "manual",
                    "source_id": "plugin-hook-e2e",
                    "quote_preview": text,
                }
            ],
        },
        timeout=10,
    )
    response.raise_for_status()


def _resolve_command(command: str, plugin_root: Path, workspace_root: Path) -> str:
    return (
        command.replace("${package.root}", str(plugin_root))
        .replace("${workspaceFolder}", str(workspace_root))
        .replace("${extensionPath}", str(plugin_root))
        .replace("${/}", os.sep)
    )


def _command_exists(command: str, cwd: Path) -> bool:
    command_path = Path(command)
    if command_path.is_absolute():
        return command_path.exists()
    return (cwd / command_path).exists()


def _generated_outputs(plugin_root: Path) -> set[str]:
    generated = plugin_root / "GENERATED.md"
    relpaths: set[str] = set()
    for line in generated.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- `") or not stripped.endswith("`"):
            continue
        relpath = stripped[3:-1]
        if relpath in {"CLAUDE.md", "AGENTS.md"}:
            continue
        assert (plugin_root / relpath).exists(), f"{generated} lists missing {relpath}"
        relpaths.add(relpath)
    return relpaths


def _write_fake_agent_cli(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _target(state: str, *, activation_state: str = "not_required") -> dict[str, object]:
    return {
        "state": state,
        "activation_state": activation_state,
        "delivery_kind": "test",
        "owned_native_objects": [],
    }


def _structured(result: Any) -> dict[str, Any]:
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)
