from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
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
    first_capture = payload["local_experience"]["first_capture"]
    assert first_capture["surface"] == "visual_memory_browser"
    assert first_capture["tab"] == "Capture"
    assert first_capture["supports"] == ["text_note", "file_evidence"]
    assert first_capture["visual_memory_tabs"] == [
        "Capture",
        "Overview",
        "Graph",
        "Review",
        "Operations",
        "Timeline",
    ]
    assert payload["local_experience"]["readiness"]["score"] == 4.0
    start_step = payload["local_experience"]["one_minute_path"][0]
    assert start_step["id"] == "start_runtime"
    assert start_step["label"] == "Start Runtime"
    assert start_step["status"] == "todo"
    assert start_step["command"] == "infinity-context up --lite"
    assert start_step["blocked_by"] == "local_runtime_not_started"
    assert start_step["description"] == "Start the local API, worker and storage services."
    assert payload["local_experience"]["one_minute_path"][3]["url"] == (
        "http://127.0.0.1:7788/ui/#capture"
    )
    assert payload["local_experience"]["one_minute_path"][4]["url"] == (
        "http://127.0.0.1:7788/ui/#review"
    )
    assert payload["mcp_configs"][0]["agent"] == "codex"
    assert payload["mcp_configs"][0]["token_included"] is False
    assert config.service_token not in captured.out
    mcp_text = mcp_path.read_text(encoding="utf-8")
    mcp_payload = json.loads(mcp_text)
    mcp_env = mcp_payload["infinity-context"]["env"]
    assert config.service_token not in mcp_text
    assert "${MEMORY_MCP_AUTH_TOKEN}" not in mcp_text
    assert "MEMORY_MCP_AUTH_TOKEN_FILE" in mcp_text
    assert mcp_env["MEMORY_MCP_AUTH_TOKEN_FILE"] == str(home / ".env")
    assert str(home / ".env") in "\n".join(payload["next_steps"])
    assert "Add the generated MCP config path to your agent." in "\n".join(
        payload["next_steps"]
    )
    assert "infinity-context ui --open" in "\n".join(payload["next_steps"])


def test_cli_quickstart_human_output_shows_first_use_path(
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
        ]
    )

    captured = capsys.readouterr()
    config = load_config(home)

    assert exit_code == 0
    assert "experience: configured_not_started" in captured.out
    assert "first_use_score: 4.0/10" in captured.out
    assert "capture_supports: text_note, file_evidence" in captured.out
    assert "visual_previews: capture_preview, source_quote" in captured.out
    assert "first_use_path:" in captured.out
    assert "  - [todo] start_runtime: infinity-context up --lite" in captured.out
    assert "  - [todo] open_visual_memory: infinity-context ui --open" in captured.out
    assert (
        "  - [done] connect_agent_mcp: "
        "MEMORY_API_URL=http://127.0.0.1:7788 "
        "infinity-context mcp-config --agent codex --write"
    ) in captured.out
    assert "  - [blocked] save_first_memory: Capture" in captured.out
    assert config.service_token not in captured.out


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


def test_cli_mcp_config_write_initializes_missing_token_file(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    monkeypatch.setenv("INFINITY_CONTEXT_REPO_ROOT", str(repo))
    monkeypatch.setenv("MEMORY_API_URL", "http://127.0.0.1:17788")

    exit_code = cli.main(["mcp-config", "--agent", "codex", "--write"])

    captured = capsys.readouterr()
    config = load_config(home)
    generated = Path(captured.out.strip())
    generated_text = generated.read_text(encoding="utf-8")

    assert exit_code == 0
    assert generated == home / "generated" / "codex-mcp.json"
    assert config.env_path.exists()
    assert "MEMORY_SERVICE_TOKEN=" in config.env_path.read_text(encoding="utf-8")
    assert "MEMORY_MCP_AUTH_TOKEN_FILE" in generated_text
    assert "http://127.0.0.1:17788" in generated_text
    assert config.service_token not in generated_text


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

    capabilities = {
        "capture": {"enabled": True},
        "suggestions": {"review_tool_supported": True},
        "context": {"answer_support_supported": True},
        "extraction": {
            "profiles_v2": [
                {
                    "name": "standard_local",
                    "enabled": True,
                    "status": "ok",
                    "input_modalities": [
                        "text",
                        "document",
                        "image",
                        "timed_text",
                        "audio_metadata",
                        "video_metadata",
                    ],
                },
                {
                    "name": "media_api",
                    "enabled": True,
                    "status": "blocked",
                    "input_modalities": ["audio", "video"],
                },
            ]
        },
    }
    statuses = [
        {"ok": False, "api_url": "http://127.0.0.1:7788", "error": "ConnectError"},
        {
            "ok": True,
            "api_url": "http://127.0.0.1:7788",
            "capabilities": {"status_code": 200, "data": capabilities},
        },
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
    assert payload["local_experience"]["readiness"]["score"] == 10.0
    assert payload["local_experience"]["first_capture"]["review_supported"] is True
    assert payload["local_experience"]["first_capture"]["active_modalities"] == [
        "audio_metadata",
        "document",
        "image",
        "text",
        "timed_text",
        "video_metadata",
    ]
    assert "image_or_screenshot" in payload["local_experience"]["first_capture"]["supports"]
    assert "audio_transcription" not in payload["local_experience"]["first_capture"]["supports"]
    assert payload["local_experience"]["one_minute_path"][3]["status"] == "next"
    assert raw_secret not in captured.out
    assert "[redacted]" in payload["runtime"]["stdout"]


def test_cli_runtime_payload_preserves_empty_output_without_fake_error() -> None:
    result = RuntimeResult(
        ok=True,
        command=("docker", "compose", "up", "-d"),
        returncode=0,
        stdout="",
        stderr="",
    )

    payload = cli._runtime_payload(result)

    assert payload["stdout"] == ""
    assert payload["stderr"] == ""


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


def test_cli_status_payload_requires_visual_memory_browser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, path: str) -> httpx.Response:
            if path == "/v1/health":
                return httpx.Response(200, json={"status": "ok"})
            if path == "/v1/capabilities":
                return httpx.Response(200, json={"capture": {"enabled": True}})
            if path == "/ui/":
                return httpx.Response(200, text="<title>Wrong App</title>")
            raise AssertionError(path)

    monkeypatch.setattr(cli.httpx, "Client", FakeClient)

    payload = cli._status_payload(config)

    assert payload["ok"] is False
    assert payload["ui"] == {
        "status_code": 200,
        "title_present": False,
        "path": "/ui/",
    }


def test_cli_status_payload_suggests_docker_published_url_on_connect_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            raise httpx.ConnectError("configured API is not reachable")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(cli.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        cli,
        "docker_compose_published_server_urls",
        lambda _config: ["http://127.0.0.1:17788"],
    )

    payload = cli._status_payload(config)

    assert payload["ok"] is False
    assert payload["error"] == "ConnectError"
    assert payload["docker_published_api_urls"] == ["http://127.0.0.1:17788"]
    assert payload["suggested_api_url"] == "http://127.0.0.1:17788"
