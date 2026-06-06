import importlib.util
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
SCRIPT_PATH = ROOT / "scripts" / "agent_install_verification.py"
PLUGIN_SKILL_PATHS = (
    ROOT / "plugins" / "memo-stack-agent-plugin" / "skills" / "memory" / "SKILL.md",
    ROOT / "plugins" / "memo-stack-agent-plugin" / "plugin" / "skills" / "memory" / "SKILL.md",
    ROOT
    / "plugins"
    / "memo-stack-agent-plugin"
    / ".opencode"
    / "skills"
    / "memory"
    / "SKILL.md",
)


def test_agent_install_verifier_accepts_codex_activation_pending(tmp_path, monkeypatch) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "installations": [
                    {
                        "integration_id": "memo-stack-agent-plugin",
                        "targets": {
                            "claude": _target("installed"),
                            "cursor": _target("installed"),
                            "opencode": _target("installed"),
                            "codex": _target(
                                "activation_pending",
                                activation_state="native_activation_pending",
                            ),
                        },
                    },
                    {
                        "integration_id": "memo-stack-agent-plugin-gemini-hooks",
                        "targets": {"gemini": _target("installed")},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))

    installation = module.load_plugin_installation()
    targets = installation["targets"]

    assert module.target_state(targets, "claude")["state"] == "installed"
    assert module.target_state(targets, "codex")["state"] == "activation_pending"


def test_agent_install_verifier_redacts_secret_values(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("MEMORY_OPENAI_API_KEY", "sk-proj-unit-secret-value")
    monkeypatch.setenv("MEMORY_MCP_AUTH_TOKEN", "unit-mcp-token-secret")

    rendered = json.dumps(
        module.redact_payload(
            {
                "stdout": "sk-proj-unit-secret-value unit-mcp-token-secret",
                "OPENAI_API_KEY": "sk-proj-unit-secret-value",
                "Authorization": "Bearer unit-bearer-token-secret",
            }
        )
    )

    assert "sk-proj-unit-secret-value" not in rendered
    assert "unit-mcp-token-secret" not in rendered
    assert "unit-bearer-token-secret" not in rendered
    assert "<redacted>" in rendered


def test_agent_install_verifier_accepts_gemini_json_on_stderr(monkeypatch) -> None:
    module = _load_script()

    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/gemini")
    monkeypatch.setattr(
        module,
        "run_command",
        lambda *_args, **_kwargs: {
            "ok": True,
            "stdout": "",
            "stderr": json.dumps([{"name": "memo-stack-agent-plugin-gemini-hooks"}]),
        },
    )

    assert module.check_gemini_extension_list() == {"status": "ok", "found": True}


def test_gemini_runtime_config_blocks_mismatched_installed_api_url(monkeypatch) -> None:
    module = _load_script()

    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/gemini")
    monkeypatch.setattr(
        module,
        "run_command",
        lambda *_args, **_kwargs: {
            "ok": True,
            "stdout": json.dumps(
                [
                    {
                        "name": "memo-stack-agent-plugin-gemini-hooks",
                        "mcpServers": {
                            "memo-stack": {
                                "env": {
                                    "MEMORY_MCP_API_URL": "http://127.0.0.1:7788",
                                    "MEMORY_MCP_AUTH_TOKEN": "unit-token",
                                }
                            }
                        },
                    }
                ]
            ),
            "stderr": "",
        },
    )

    result = module.check_gemini_extension_runtime_config(
        expected_api_url="http://127.0.0.1:17788",
        expected_auth_token="unit-token",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == (
        "gemini installed extension targets "
        "http://127.0.0.1:7788, not http://127.0.0.1:17788"
    )
    assert result["configured_api_url"] == "http://127.0.0.1:7788"
    assert "unit-token" not in json.dumps(result)


def test_gemini_runtime_config_accepts_runtime_override_for_installed_mismatch(
    monkeypatch,
) -> None:
    module = _load_script()

    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/gemini")
    monkeypatch.setattr(
        module,
        "run_command",
        lambda *_args, **_kwargs: {
            "ok": True,
            "stdout": json.dumps(
                [
                    {
                        "name": "memo-stack-agent-plugin-gemini-hooks",
                        "mcpServers": {
                            "memo-stack": {
                                "env": {
                                    "MEMORY_MCP_API_URL": "http://127.0.0.1:7788",
                                    "MEMORY_MCP_AUTH_TOKEN": "old-token",
                                }
                            }
                        },
                    }
                ]
            ),
            "stderr": "",
        },
    )

    result = module.check_gemini_extension_runtime_config(
        expected_api_url="http://127.0.0.1:17788",
        expected_auth_token="unit-token",
        runtime_override_api_url="http://127.0.0.1:17788",
        runtime_override_auth_token_present=True,
    )

    assert result == {
        "status": "ok",
        "configured_api_url": "http://127.0.0.1:7788",
        "configured_auth_token": "<set>",
        "runtime_override_api_url": "http://127.0.0.1:17788",
        "runtime_override_auth_token": "<set>",
    }
    assert "unit-token" not in json.dumps(result)
    assert "old-token" not in json.dumps(result)


def test_gemini_runtime_config_accepts_matching_or_inherited_env(monkeypatch) -> None:
    module = _load_script()

    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/gemini")
    monkeypatch.setattr(
        module,
        "run_command",
        lambda *_args, **_kwargs: {
            "ok": True,
            "stdout": json.dumps(
                [
                    {
                        "name": "memo-stack-agent-plugin-gemini-hooks",
                        "mcpServers": {"memo-stack": {"env": {}}},
                    }
                ]
            ),
            "stderr": "",
        },
    )

    result = module.check_gemini_extension_runtime_config(
        expected_api_url="http://127.0.0.1:17788",
        expected_auth_token="unit-token",
    )

    assert result == {
        "status": "ok",
        "configured_api_url": "<inherits-process-env>",
        "configured_auth_token": "<inherits-process-env>",
        "runtime_override_api_url": "<not-set>",
        "runtime_override_auth_token": "<not-set>",
    }


def test_agent_install_verifier_uses_structured_state_not_home_history_scan() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert ".plugin-kit-ai" in source
    assert "state.json" in source
    assert ".codex/archived_sessions" not in source
    assert ".claude/projects" not in source
    assert '"rg"' not in source


def test_agent_install_live_smoke_does_not_accept_auth_token_cli_arg() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--auth-token" not in source
    assert "MEMORY_MCP_AUTH_TOKEN" in source
    assert "MEMORY_SERVICE_TOKEN" in source


def test_agent_install_doctor_fails_when_plugin_kit_doctor_fails(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "installations": [
                    {
                        "integration_id": "memo-stack-agent-plugin",
                        "targets": {
                            "claude": _target("installed"),
                            "cursor": _target("installed"),
                            "opencode": _target("installed"),
                            "codex": _target("installed"),
                        },
                    },
                    {
                        "integration_id": "memo-stack-agent-plugin-gemini-hooks",
                        "targets": {"gemini": _target("installed")},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))

    def fake_run_command(argv: list[str], *, timeout: float) -> dict[str, object]:
        if argv[-1] == "doctor":
            return {"ok": False, "stdout": "", "stderr": "doctor failed"}
        return {"ok": True, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(module, "run_command", fake_run_command)
    monkeypatch.setattr(module, "check_claude_plugin_list", lambda: {"status": "ok"})
    monkeypatch.setattr(module, "check_gemini_extension_list", lambda: {"status": "ok"})

    result = module.run_install_doctor(strict_codex=False, skip_cli_lists=False)

    assert result["ok"] is False
    assert result["checks"]["plugin_kit_ai_list"] is True
    assert result["checks"]["plugin_kit_ai_doctor"] is False
    assert result["failures"] == ["plugin-kit-ai integrations doctor failed"]


def test_memory_agent_skill_does_not_make_status_first_default() -> None:
    for skill_path in PLUGIN_SKILL_PATHS:
        text = skill_path.read_text(encoding="utf-8").casefold()

        assert "call `memory_status` first" not in text
        assert "call memory_status first" not in text
        assert "call `memory_search` before relying on memory" in text
        assert "call `memory_status` only" in text


def test_agent_command_timeout_terminates_process_group(monkeypatch) -> None:
    module = _load_script()
    popen_kwargs: dict[str, Any] = {}
    killed: list[tuple[int, int]] = []

    class FakeProcess:
        pid = 12345
        returncode = None

        def __init__(self) -> None:
            self.communicate_calls = 0
            self.wait_calls = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(cmd=["agent"], timeout=timeout)
            return ("", "")

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(cmd=["agent"], timeout=timeout)
            self.returncode = -signal.SIGKILL
            return self.returncode

    def fake_popen(*args: Any, **kwargs: Any) -> FakeProcess:
        popen_kwargs.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    result = module.run_agent_command(
        "unit-agent",
        [sys.executable, "-c", "print('never')"],
        timeout=0.01,
        expected_marker="unit-agent-ok",
    )

    assert result == {
        "status": "blocked",
        "reason": "unit-agent timed out after 0.01s",
        "stdout_tail": "",
        "stderr_tail": "",
    }
    assert popen_kwargs["start_new_session"] is True
    assert killed == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]


def test_agent_cli_smokes_run_agent_commands_in_parallel(monkeypatch) -> None:
    module = _load_script()
    calls: dict[str, list[str]] = {}
    seen_env: dict[str, dict[str, str]] = {}

    def fake_run_agent_command(
        name: str,
        _argv: list[str],
        *,
        timeout: float,
        expected_marker: str,
        extra_env: dict[str, str],
    ) -> dict[str, str]:
        calls[name] = _argv
        seen_env[name] = extra_env
        assert expected_marker == "memory_status_checked"
        time.sleep(0.2)
        return {"status": "blocked", "reason": f"{name} blocked"}

    monkeypatch.setattr(module, "run_agent_command", fake_run_agent_command)
    monkeypatch.setattr(
        module,
        "check_gemini_extension_runtime_config",
        lambda **kwargs: {
            "status": "ok",
            "configured_api_url": kwargs["expected_api_url"],
            "configured_auth_token": "<set>",
            "runtime_override_api_url": kwargs["runtime_override_api_url"],
            "runtime_override_auth_token": "<set>",
        },
    )

    started_at = time.monotonic()
    result = module.run_agent_cli_smokes(
        api_url="http://127.0.0.1:17788",
        auth_token="unit-live-token",
        timeout=1,
    )
    elapsed = time.monotonic() - started_at

    assert set(result) == {"claude", "gemini", "opencode", "codex"}
    assert set(calls) == {"claude", "gemini", "opencode", "codex"}
    assert "--allowed-mcp-server-names" in calls["gemini"]
    assert module.GEMINI_HOOK_INTEGRATION_ID in calls["gemini"]
    assert "memo-stack" in calls["gemini"]
    assert "--output-format" in calls["gemini"]
    assert "mcp_memo-stack_memory_status" in " ".join(calls["gemini"])
    assert "--plugin-dir" in calls["claude"]
    assert f'mcp_servers.memo-stack.command="{module.PLUGIN_ROOT / "bin" / "memo-stack-mcp"}"' in (
        calls["codex"]
    )
    assert "unit-live-token" not in " ".join(calls["codex"])
    assert "MEMORY_MCP_AUTH_TOKEN" not in " ".join(calls["codex"])
    assert "MEMORY_MCP_RUNTIME_AUTH_TOKEN" not in " ".join(calls["codex"])
    assert seen_env["gemini"]["MEMORY_MCP_API_URL"] == "http://127.0.0.1:17788"
    assert seen_env["gemini"]["MEMORY_MCP_AUTH_TOKEN"] == "unit-live-token"
    assert seen_env["gemini"]["MEMORY_MCP_RUNTIME_API_URL"] == "http://127.0.0.1:17788"
    assert seen_env["gemini"]["MEMORY_MCP_RUNTIME_AUTH_TOKEN"] == "unit-live-token"
    assert seen_env["codex"]["MEMORY_MCP_RUNTIME_API_URL"] == "http://127.0.0.1:17788"
    assert seen_env["codex"]["MEMORY_MCP_RUNTIME_AUTH_TOKEN"] == "unit-live-token"
    assert (
        seen_env["gemini"]["MEMORY_MCP_RUNTIME_DEFAULT_THREAD_EXTERNAL_REF"]
        == module.NO_DEFAULT_THREAD_SENTINEL
    )
    assert (
        seen_env["claude"]["MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF"]
        == module.NO_DEFAULT_THREAD_SENTINEL
    )
    assert elapsed < 0.6


def test_agent_cli_smokes_blocks_gemini_when_installed_extension_points_elsewhere(
    monkeypatch,
) -> None:
    module = _load_script()
    calls: dict[str, list[str]] = {}

    def fake_run_agent_command(
        name: str,
        _argv: list[str],
        *,
        timeout: float,
        expected_marker: str,
        extra_env: dict[str, str],
    ) -> dict[str, str]:
        calls[name] = _argv
        return {"status": "ok", "stdout": expected_marker}

    monkeypatch.setattr(module, "run_agent_command", fake_run_agent_command)
    monkeypatch.setattr(
        module,
        "check_gemini_extension_runtime_config",
        lambda **_kwargs: {
            "status": "blocked",
            "reason": (
                "gemini installed extension targets "
                "http://127.0.0.1:7788, not http://127.0.0.1:17788"
            ),
            "configured_api_url": "http://127.0.0.1:7788",
        },
    )

    result = module.run_agent_cli_smokes(
        api_url="http://127.0.0.1:17788",
        auth_token="unit-live-token",
        timeout=1,
    )

    assert result["gemini"]["status"] == "blocked"
    assert result["gemini"]["reason"] == (
        "gemini installed extension targets "
        "http://127.0.0.1:7788, not http://127.0.0.1:17788"
    )
    assert "gemini" not in calls
    assert set(calls) == {"claude", "opencode", "codex"}


def test_agent_cli_smokes_keep_json_when_one_agent_check_raises(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setenv("MEMORY_MCP_AUTH_TOKEN", "unit-agent-secret-token")

    def fake_run_agent_command(
        name: str,
        _argv: list[str],
        *,
        timeout: float,
        expected_marker: str,
        extra_env: dict[str, str],
    ) -> dict[str, str]:
        if name == "gemini":
            raise RuntimeError("failed with unit-agent-secret-token")
        return {"status": "ok", "stdout": expected_marker}

    monkeypatch.setattr(module, "run_agent_command", fake_run_agent_command)
    monkeypatch.setattr(
        module,
        "check_gemini_extension_runtime_config",
        lambda **kwargs: {
            "status": "ok",
            "configured_api_url": kwargs["expected_api_url"],
            "configured_auth_token": "<set>",
            "runtime_override_api_url": kwargs["runtime_override_api_url"],
            "runtime_override_auth_token": "<set>",
        },
    )

    result = module.run_agent_cli_smokes(timeout=1)

    assert result["claude"]["status"] == "ok"
    assert result["gemini"]["status"] == "blocked"
    assert "unit-agent-secret-token" not in result["gemini"]["reason"]
    assert "<redacted>" in result["gemini"]["reason"]


def test_agent_command_detects_marker_before_stdout_tail(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/agent")
    monkeypatch.setattr(
        module,
        "run_bounded_command",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "stdout": "memory_status_checked\n" + ("x" * 3000),
            "stderr": "",
            "timed_out": False,
        },
    )

    result = module.run_agent_command(
        "unit-agent",
        ["agent"],
        timeout=1,
        expected_marker="memory_status_checked",
    )

    assert result["status"] == "ok"
    assert result["expected_marker_seen"] is True
    assert "memory_status_checked" not in result["stdout"]


def test_agent_command_blocks_success_exit_without_expected_marker(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/agent")
    monkeypatch.setattr(
        module,
        "run_bounded_command",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "stdout": "",
            "stderr": "Token refresh failed: 401",
            "timed_out": False,
        },
    )

    result = module.run_agent_command(
        "opencode",
        ["opencode"],
        timeout=1,
        expected_marker="opencode_auth_ok",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "agent auth blocked: token refresh failed"


def test_agent_command_blocks_success_marker_with_mcp_tool_error(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(module.shutil, "which", lambda _: "/bin/agent")
    monkeypatch.setattr(
        module,
        "run_bounded_command",
        lambda *_args, **_kwargs: {
            "returncode": 0,
            "stdout": "memory_status_checked\n",
            "stderr": "Error executing tool mcp_memo-stack_memory_status",
            "timed_out": False,
        },
    )

    result = module.run_agent_command(
        "gemini",
        ["gemini"],
        timeout=1,
        expected_marker="memory_status_checked",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "agent MCP tool blocked: tool execution error"
    assert result["expected_marker_seen"] is True


def test_agent_block_reason_detects_auth_failures() -> None:
    module = _load_script()

    assert (
        module.agent_block_reason("Failed to authenticate. API Error: 401", "")
        == "agent auth blocked: invalid authentication credentials"
    )
    assert (
        module.agent_block_reason("", "Token refresh failed: 401")
        == "agent auth blocked: token refresh failed"
    )
    assert (
        module.agent_block_reason(
            "",
            "MCP tool 'memory_status' reported an error.",
        )
        == "agent MCP tool blocked: memory tool reported an error"
    )


def test_plain_agent_auth_doctor_is_advisory_by_default(monkeypatch) -> None:
    module = _load_script()
    seen_markers: dict[str, str] = {}
    seen_argv: dict[str, list[str]] = {}

    def fake_run_agent_command(
        name: str,
        _argv: list[str],
        *,
        timeout: float,
        expected_marker: str,
        extra_env: dict[str, str],
    ) -> dict[str, str]:
        seen_markers[name] = expected_marker
        seen_argv[name] = _argv
        if name == "claude":
            return {"status": "blocked", "reason": "agent auth blocked"}
        return {"status": "ok", "stdout": expected_marker}

    monkeypatch.setattr(module, "run_agent_command", fake_run_agent_command)

    result = module.run_agent_auth_doctor(timeout=1, strict=False)

    assert result["ok"] is True
    assert result["failures"] == ["claude"]
    assert seen_markers == {
        "claude": "claude_auth_ok",
        "gemini": "gemini_auth_ok",
        "opencode": "opencode_auth_ok",
        "codex": "codex_auth_ok",
    }
    assert "--extensions" in seen_argv["gemini"]
    assert "" in seen_argv["gemini"]


def test_plain_agent_auth_doctor_strict_fails_on_blocked_agent(monkeypatch) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "run_plain_agent_auth_checks",
        lambda *, timeout: {
            "opencode": {"status": "blocked", "reason": "token refresh failed"}
        },
    )

    result = module.run_agent_auth_doctor(timeout=1, strict=True)

    assert result["ok"] is False
    assert result["strict"] is True
    assert result["failures"] == ["opencode"]


def test_live_smoke_strict_agent_cli_failures_make_result_not_ok(monkeypatch) -> None:
    module = _load_script()

    async def fake_generated_status(**kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "tool_count": 16,
            "space_slug": kwargs["space_slug"],
            "profile_external_ref": "default",
        }

    monkeypatch.setattr(module, "run_generated_mcp_status", fake_generated_status)
    monkeypatch.setattr(
        module,
        "run_agent_cli_smokes",
        lambda *, api_url, auth_token, timeout: {
            "claude": {"status": "ok", "stdout": "memory_status_checked"},
            "gemini": {"status": "blocked", "reason": "gemini timed out after 1s"},
        },
    )

    result = module.asyncio.run(
        module.run_live_smoke(
            api_url="http://127.0.0.1:7788",
            auth_token="unit-token",
            run_agent_cli=True,
            strict_agent_cli=True,
            agent_timeout_seconds=1,
        )
    )

    assert result["ok"] is False
    assert result["generated_mcp_failures"] == []
    assert result["agent_cli_failures"] == ["gemini"]
    assert result["failures"] == ["agent_cli:gemini"]


def test_live_smoke_non_strict_agent_cli_failures_are_advisory(monkeypatch) -> None:
    module = _load_script()

    async def fake_generated_status(**kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "tool_count": 16,
            "space_slug": kwargs["space_slug"],
            "profile_external_ref": "default",
        }

    monkeypatch.setattr(module, "run_generated_mcp_status", fake_generated_status)
    monkeypatch.setattr(
        module,
        "run_agent_cli_smokes",
        lambda *, api_url, auth_token, timeout: {
            "gemini": {"status": "blocked", "reason": "gemini timed out after 1s"},
        },
    )

    result = module.asyncio.run(
        module.run_live_smoke(
            api_url="http://127.0.0.1:7788",
            auth_token="unit-token",
            run_agent_cli=True,
            strict_agent_cli=False,
            agent_timeout_seconds=1,
        )
    )

    assert result["ok"] is True
    assert result["agent_cli_failures"] == ["gemini"]
    assert result["failures"] == []


def _target(state: str, *, activation_state: str = "not_required") -> dict[str, object]:
    return {
        "state": state,
        "activation_state": activation_state,
        "delivery_kind": "test",
        "owned_native_objects": [],
    }


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "agent_install_verification_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
