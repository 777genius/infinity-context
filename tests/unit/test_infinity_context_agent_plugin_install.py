from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[2]
SCRIPT_PATH = ROOT / "scripts" / "install_memory_agent_plugin.py"


def test_memory_agent_plugin_install_detects_managed_state(tmp_path, monkeypatch) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"installations": [{"integration_id": "infinity-context-agent-plugin"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))

    assert module.is_managed() is True
    assert module.is_managed("missing-plugin") is False


def test_memory_agent_plugin_install_plans_only_selected_agents(
    tmp_path, monkeypatch, capsys
) -> None:
    module = _load_script()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or SimpleNamespace(returncode=0),
    )

    assert (
        module.main(
            [
                "--agent",
                "codex",
                "--agent",
                "gemini",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert calls == []
    assert payload["selected_agents"] == ["codex", "gemini"]
    assert [item["status"] for item in payload["integrations"]] == ["planned", "planned"]
    assert [item["agent"] for item in payload["integrations"]] == ["codex", "gemini"]
    assert payload["integrations"][0]["auto_memory"] == {
        "mode": "suggest",
        "capture_mode": "suggest",
        "mcp_write_mode": "suggest",
        "mcp_ingest_mode": "small_docs",
        "review_gated": True,
        "auto_apply": False,
        "ingest_events": ["UserPromptSubmit", "Stop"],
        "capture_status": "review_gated_capture",
        "raw_tool_capture": False,
    }
    assert payload["integrations"][1]["auto_memory"]["ingest_events"] == [
        "AfterAgent",
        "SessionEnd",
    ]


def test_memory_agent_plugin_install_materializes_safe_runtime_config(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script()
    materialized_root = tmp_path / "materialized"
    integration_root = materialized_root / "codex" / module.INTEGRATION_ID
    integration_root.mkdir(parents=True)
    (integration_root / ".mcp.json").write_text(
        json.dumps(
            {
                "infinity-context": {
                    "command": "./bin/infinity-context-mcp",
                    "env": {
                        "MEMORY_MCP_API_URL": "http://127.0.0.1:7788",
                        "MEMORY_MCP_AUTH_TOKEN": "local-dev-token",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    token_file = tmp_path / "home" / ".env"
    token_file.parent.mkdir()
    token_file.write_text("MEMORY_SERVICE_TOKEN=unit-secret-token-123456\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setenv("PLUGIN_KIT_AI_MATERIALIZED_ROOT", str(materialized_root))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command) or SimpleNamespace(returncode=0),
    )

    assert (
        module.main(
            [
                "--agent",
                "codex",
                "--auth-token-file",
                str(token_file),
                "--api-url",
                "http://127.0.0.1:17788",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    mcp_payload = json.loads((integration_root / ".mcp.json").read_text(encoding="utf-8"))
    env = mcp_payload["infinity-context"]["env"]
    runtime_env = (integration_root / module.RUNTIME_ENV_MARKER).read_text(encoding="utf-8")

    assert calls == [
        [str(module.PLUGIN_KIT), "add", str(module.PLUGIN_ROOT), "--target", "codex"]
    ]
    assert payload["integrations"][0]["status"] == "installed"
    assert payload["integrations"][0]["installed"] is True
    assert env["MEMORY_MCP_AUTH_TOKEN_FILE"] == str(token_file)
    assert "MEMORY_MCP_AUTH_TOKEN" not in env
    assert env["MEMORY_CAPTURE_MODE"] == "suggest"
    assert env["MEMORY_PLUGIN_HOOK_INGEST_EVENTS"] == "UserPromptSubmit,Stop"
    assert "local-dev-token" not in (integration_root / ".mcp.json").read_text(encoding="utf-8")
    assert "unit-secret-token-123456" not in runtime_env
    assert f"MEMORY_MCP_AUTH_TOKEN_FILE={token_file}" in runtime_env
    assert (integration_root / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert "unit-secret-token-123456" not in json.dumps(payload)


def test_memory_agent_plugin_install_reports_unverified_without_materialized_config(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script()
    token_file = tmp_path / ".env"
    token_file.write_text("MEMORY_SERVICE_TOKEN=unit-secret-token-123456\n", encoding="utf-8")
    monkeypatch.setenv("PLUGIN_KIT_AI_MATERIALIZED_ROOT", str(tmp_path / "materialized"))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda _command, **_kwargs: SimpleNamespace(returncode=0),
    )

    assert module.main(["--agent", "codex", "--auth-token-file", str(token_file), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    report = payload["integrations"][0]
    assert report["status"] == "unverified"
    assert report["installed"] is False
    assert "unit-secret-token-123456" not in json.dumps(payload)


def test_memory_agent_plugin_install_reports_missing_dependency_without_running_command(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script()
    token_file = tmp_path / ".env"
    token_file.write_text("MEMORY_SERVICE_TOKEN=unit-secret-token-123456\n", encoding="utf-8")
    monkeypatch.setattr(module, "PLUGIN_KIT", tmp_path / "missing-plugin-kit-ai")
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert module.main(["--agent", "codex", "--auth-token-file", str(token_file), "--json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["integrations"] == [
        {
            "agent": "codex",
            "integration_id": module.INTEGRATION_ID,
            "action": "unavailable",
            "status": "unavailable",
            "installed": False,
            "configured": False,
            "reason": "plugin-kit-ai is unavailable; use the generated MCP config manually.",
            "auto_memory": {
                "mode": "suggest",
                "capture_mode": "suggest",
                "mcp_write_mode": "suggest",
                "mcp_ingest_mode": "small_docs",
                "review_gated": True,
                "auto_apply": False,
                "ingest_events": ["UserPromptSubmit", "Stop"],
                "capture_status": "review_gated_capture",
                "raw_tool_capture": False,
            },
            "materialized_paths": [],
        }
    ]


def test_memory_agent_plugin_install_resolves_path_plugin_kit_when_local_wrapper_is_absent(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_script()
    bundled = tmp_path / "prefix" / "bin" / "plugin-kit-ai"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(module, "PLUGIN_KIT", tmp_path / "missing-plugin-kit-ai-local")
    monkeypatch.setattr(module.shutil, "which", lambda _name: str(bundled))

    command, action = module.install_command(module.install_specs(("codex",))[0], dry_run=True)

    assert action == "add"
    assert command == [
        str(bundled),
        "add",
        str(module.PLUGIN_ROOT),
        "--target",
        "codex",
        "--dry-run",
    ]


def test_memory_agent_plugin_install_uses_update_when_managed(tmp_path, monkeypatch) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"installations": [{"integration_id": "infinity-context-agent-plugin"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))

    command, action = module.install_command(
        module.install_specs(("codex",))[0],
        dry_run=True,
    )

    assert action == "update"
    assert command == [
        str(module.PLUGIN_KIT),
        "update",
        "infinity-context-agent-plugin",
        "--dry-run",
    ]


def test_memory_agent_plugin_install_fails_closed_for_managed_target_expansion(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "installations": [
                    {
                        "integration_id": module.INTEGRATION_ID,
                        "targets": {"codex": {"target_id": "codex"}},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    token_file = tmp_path / ".env"
    token_file.write_text("MEMORY_SERVICE_TOKEN=unit-secret-token-123456\n", encoding="utf-8")
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    exit_code = module.main(
        ["--agent", "claude", "--auth-token-file", str(token_file), "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["integrations"][0]["status"] == "failed"
    assert payload["integrations"][0]["action"] == "unsupported_target_expansion"
    assert "claude" in payload["integrations"][0]["reason"]


def test_memory_agent_plugin_install_writes_materialized_source_root_markers(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_script()
    materialized_root = tmp_path / "materialized"
    primary_claude = materialized_root / "claude" / "infinity-context-agent-plugin"
    primary_claude.mkdir(parents=True)
    primary_nested = primary_claude / "plugins" / "infinity-context-agent-plugin"
    primary_nested.mkdir(parents=True)
    gemini_hooks = materialized_root / "gemini" / "infinity-context-agent-plugin-gemini-hooks"
    gemini_hooks.mkdir(parents=True)
    monkeypatch.setenv("PLUGIN_KIT_AI_MATERIALIZED_ROOT", str(materialized_root))

    for spec in module.install_specs():
        module.write_source_root_markers(spec)

    assert (primary_claude / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert (primary_claude / "bin" / "infinity-context-mcp").exists()
    assert (primary_nested / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert (primary_nested / "bin" / "infinity-context-plugin-hook").exists()
    assert (gemini_hooks / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert (gemini_hooks / "bin" / "infinity-context-plugin-hook").exists()


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "install_memory_agent_plugin_for_test",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
