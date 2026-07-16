from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import infinity_context_server.memory_comparison_codex_llm as codex_llm


def test_run_codex_cli_uses_isolated_runtime_env_and_cwd(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        args,
        *,
        input,
        text,
        capture_output,
        timeout,
        check,
        cwd,
        env,
    ):
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text("unit codex output\n", encoding="utf-8")
        env_paths = {
            name: Path(env[name])
            for name in (
                "TMPDIR",
                "TEMP",
                "TMP",
                "XDG_RUNTIME_DIR",
                "XDG_CACHE_HOME",
                "XDG_STATE_HOME",
                "XDG_DATA_HOME",
            )
        }
        captured.update(
            {
                "args": tuple(args),
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "timeout": timeout,
                "check": check,
                "cwd": Path(cwd),
                "env": dict(env),
                "env_paths_exist": {name: path.is_dir() for name, path in env_paths.items()},
                "output_parent_exists": output_path.parent.is_dir(),
                "runtime_root": output_path.parents[1],
            }
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("HOME", "/unit/home")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/unit/config")
    monkeypatch.setenv("XDG_CACHE_HOME", "/read-only/cache")
    monkeypatch.setattr(codex_llm.subprocess, "run", fake_run)

    result = codex_llm._run_codex_cli(
        codex_command="unit-codex",
        model="gpt-5.5",
        prompt="Answer from the evidence only.",
        timeout_seconds=12.0,
        cwd=None,
    )

    assert result == "unit codex output"
    assert captured["input"] == "Answer from the evidence only."
    assert captured["timeout"] == 12.0
    assert captured["text"] is True
    assert captured["capture_output"] is True
    assert captured["check"] is False
    assert captured["args"][:2] == ("unit-codex", "exec")
    assert "--sandbox" in captured["args"]
    assert "read-only" in captured["args"]
    env = captured["env"]
    assert env["HOME"] == "/unit/home"
    assert env["XDG_CONFIG_HOME"] == "/unit/config"
    assert env["XDG_CACHE_HOME"] != "/read-only/cache"
    assert all(captured["env_paths_exist"].values())
    assert captured["output_parent_exists"] is True
    assert captured["runtime_root"] in captured["cwd"].parents


def test_memory_comparison_llm_keeps_codex_lazy_exports() -> None:
    from infinity_context_server.memory_comparison_llm import CodexCliAnswerer

    assert CodexCliAnswerer is codex_llm.CodexCliAnswerer
