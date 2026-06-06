import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
SCRIPT_PATH = ROOT / "scripts" / "install_memory_agent_plugin.py"


def test_memory_agent_plugin_install_detects_managed_state(tmp_path, monkeypatch) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"installations": [{"integration_id": "memo-stack-agent-plugin"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))

    assert module.is_managed() is True
    assert module.is_managed("missing-plugin") is False


def test_memory_agent_plugin_install_detects_missing_state(tmp_path, monkeypatch) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"installations": []}), encoding="utf-8")
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))

    assert module.is_managed() is False


def test_memory_agent_plugin_install_uses_update_when_managed(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"installations": [{"integration_id": "memo-stack-agent-plugin"}]}),
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))
    monkeypatch.setattr(module.subprocess, "call", lambda argv, cwd: calls.append(argv) or 0)
    monkeypatch.setattr(module.sys, "argv", ["install_memory_agent_plugin.py", "--dry-run"])

    assert module.main() == 0

    assert calls == [
        [str(module.PLUGIN_KIT), "update", "memo-stack-agent-plugin", "--dry-run"],
        [
            str(module.PLUGIN_KIT),
            "add",
            str(module.GEMINI_HOOK_PLUGIN_ROOT),
            "--target",
            "gemini",
            "--dry-run",
        ],
    ]
    stderr = capsys.readouterr().err
    assert "memo-stack-agent-plugin update" in stderr
    assert "memo-stack-agent-plugin-gemini-hooks add" in stderr


def test_memory_agent_plugin_install_uses_add_when_missing(tmp_path, monkeypatch) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"installations": []}), encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))
    monkeypatch.setattr(module.subprocess, "call", lambda argv, cwd: calls.append(argv) or 0)
    monkeypatch.setattr(module.sys, "argv", ["install_memory_agent_plugin.py"])

    assert module.main() == 0

    assert len(calls) == 2
    primary_command = calls[0]
    assert primary_command[:3] == [str(module.PLUGIN_KIT), "add", str(module.PLUGIN_ROOT)]
    primary_target_pairs = list(zip(primary_command[3::2], primary_command[4::2], strict=True))
    assert primary_target_pairs == [("--target", target) for target in module.INSTALL_TARGETS]
    assert ("--target", "gemini") not in primary_target_pairs

    gemini_command = calls[1]
    assert gemini_command == [
        str(module.PLUGIN_KIT),
        "add",
        str(module.GEMINI_HOOK_PLUGIN_ROOT),
        "--target",
        "gemini",
    ]


def test_memory_agent_plugin_install_stops_on_failed_primary_command(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_script()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"installations": []}), encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setenv("PLUGIN_KIT_AI_STATE_PATH", str(state_path))
    monkeypatch.setattr(module.subprocess, "call", lambda argv, cwd: calls.append(argv) or 17)
    monkeypatch.setattr(module.sys, "argv", ["install_memory_agent_plugin.py"])

    assert module.main() == 17
    assert len(calls) == 1


def test_memory_agent_plugin_install_writes_materialized_source_root_markers(
    tmp_path,
    monkeypatch,
) -> None:
    module = _load_script()
    materialized_root = tmp_path / "materialized"
    primary_claude = materialized_root / "claude" / "memo-stack-agent-plugin"
    primary_claude.mkdir(parents=True)
    primary_nested = primary_claude / "plugins" / "memo-stack-agent-plugin"
    primary_nested.mkdir(parents=True)
    gemini_hooks = materialized_root / "gemini" / "memo-stack-agent-plugin-gemini-hooks"
    gemini_hooks.mkdir(parents=True)
    monkeypatch.setenv("PLUGIN_KIT_AI_MATERIALIZED_ROOT", str(materialized_root))

    for spec in module.install_specs():
        module.write_source_root_markers(spec)

    assert (primary_claude / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert (primary_claude / "bin" / "memo-stack-mcp").exists()
    assert (primary_nested / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert (primary_nested / "bin" / "memo-stack-plugin-hook").exists()
    assert (gemini_hooks / module.SOURCE_ROOT_MARKER).read_text(encoding="utf-8") == (
        f"{module.PROJECT_ROOT}\n"
    )
    assert (gemini_hooks / "bin" / "memo-stack-plugin-hook").exists()


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
