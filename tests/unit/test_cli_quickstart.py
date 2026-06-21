from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from infinity_context_cli import cli
from infinity_context_cli.config import init_local_config, load_config
from infinity_context_cli.runtime import RuntimeResult


def test_cli_quickstart_initializes_and_writes_redacted_mcp_config(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))

    exit_code = cli.main(
        [
            "quickstart",
            "--home",
            str(home),
            "--repo-dir",
            str(repo),
            "--no-start",
            "--agent",
            "codex",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    config = load_config(home)
    mcp_path = Path(payload["mcp_configs"][0]["path"])

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["runtime"] is None
    assert payload["opened_ui"] is False
    assert payload["ui_url"] == "http://127.0.0.1:7788/ui/"
    assert payload["local_experience"]["status"] == "configured_not_started"
    assert payload["local_experience"]["visual_memory_ready"] is False
    assert payload["local_experience"]["mcp_ready"] is True
    assert payload["local_experience"]["ready_agents"] == ["codex"]
    assert payload["local_experience"]["mcp_config_paths"] == [str(mcp_path)]
    assert payload["local_experience"]["first_capture"] == {
        "surface": "visual_memory_browser",
        "tab": "Capture",
        "supports": ["text_note", "file_evidence"],
    }
    assert payload["mcp_configs"][0]["agent"] == "codex"
    assert payload["mcp_configs"][0]["token_included"] is False
    assert config.service_token not in captured.out
    mcp_text = mcp_path.read_text(encoding="utf-8")
    assert config.service_token not in mcp_text
    assert "${MEMORY_MCP_AUTH_TOKEN}" not in mcp_text
    assert "MEMORY_MCP_AUTH_TOKEN_FILE" in mcp_text
    assert str(home / ".env") in mcp_text
    assert str(home / ".env") in "\n".join(payload["next_steps"])
    assert "Add the generated MCP config path to your agent." in "\n".join(
        payload["next_steps"]
    )
    assert "infinity-context ui --open" in "\n".join(payload["next_steps"])


def test_cli_quickstart_can_open_visual_memory(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)

    exit_code = cli.main(
        [
            "quickstart",
            "--home",
            str(home),
            "--repo-dir",
            str(repo),
            "--no-start",
            "--open-ui",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["opened_ui"] is True
    assert opened == ["http://127.0.0.1:7788/ui/"]
    assert "Visual memory opened with: infinity-context ui --open" in "\n".join(
        payload["next_steps"]
    )


def test_cli_quickstart_starts_runtime_waits_for_status_and_redacts_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    raw_secret = "sk-proj-secretvalue1234567890"
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    init_local_config(home=home, repo_dir=repo)
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))

    class FakeRuntime:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def up(self, compose_profile: str) -> RuntimeResult:
            return RuntimeResult(
                ok=True,
                command=("docker", "compose", "--profile", compose_profile, "up", "-d"),
                returncode=0,
                stdout=f"started with {raw_secret}",
                stderr="",
            )

    statuses = [
        {"ok": False, "api_url": "http://127.0.0.1:7788", "error": "ConnectError"},
        {"ok": True, "api_url": "http://127.0.0.1:7788"},
    ]

    def fake_status(_config) -> dict[str, Any]:
        return statuses.pop(0) if statuses else {"ok": True, "api_url": "http://127.0.0.1:7788"}

    monkeypatch.setattr(cli, "DockerComposeRuntime", FakeRuntime)
    monkeypatch.setattr(cli, "_status_payload", fake_status)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)

    exit_code = cli.main(
        [
            "quickstart",
            "--home",
            str(home),
            "--repo-dir",
            str(repo),
            "--wait-seconds",
            "1",
            "--agent",
            "codex",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["runtime"]["ok"] is True
    assert payload["status"]["ok"] is True
    assert payload["local_experience"]["status"] == "ready"
    assert payload["local_experience"]["visual_memory_ready"] is True
    assert payload["local_experience"]["mcp_ready"] is True
    assert raw_secret not in captured.out
    assert "[redacted]" in payload["runtime"]["stdout"]


def test_cli_ui_prints_url_and_can_open_browser(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    init_local_config(home=home, repo_dir=repo, api_url="http://127.0.0.1:18888")
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    opened: list[str] = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url) or True)

    exit_code = cli.main(["ui", "--open", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ui_url"] == "http://127.0.0.1:18888/ui/"
    assert payload["opened"] is True
    assert opened == ["http://127.0.0.1:18888/ui/"]


def test_cli_ui_check_returns_unready_status(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    init_local_config(home=home, repo_dir=repo)
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    monkeypatch.setattr(
        cli,
        "_status_payload",
        lambda _config: {"ok": False, "api_url": "http://127.0.0.1:7788"},
    )

    exit_code = cli.main(["ui", "--check"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "http://127.0.0.1:7788/ui/" in captured.out
    assert "warning: local API is not ready" in captured.err
