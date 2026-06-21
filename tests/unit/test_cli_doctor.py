from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from infinity_context_cli import cli, doctor
from infinity_context_cli.config import init_local_config
from infinity_context_cli.mcp_config import write_mcp_config


def test_doctor_reports_generated_mcp_configs(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)
    write_mcp_config(agent="codex", config=config)

    check = doctor._mcp_generated_config_check(config)
    rendered = json.dumps(check.details, sort_keys=True)

    assert check.ok is True
    assert check.name == "mcp_generated_configs"
    assert check.details["agents"] == ["codex"]
    assert check.details["ready_agents"] == ["codex"]
    assert check.details["configs"][0]["auth_source"] == "token_file"
    assert check.details["configs"][0]["token_file_exists"] is True
    assert check.details["configs"][0]["token_included"] is False
    assert config.service_token not in rendered


def test_doctor_reports_generated_mcp_config_with_unresolved_token_placeholder(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)
    generated = home / "generated"
    generated.mkdir()
    (generated / "codex-mcp.json").write_text(
        json.dumps(
            {
                "infinity-context": {
                    "command": "infinity-context-mcp",
                    "env": {
                        "MEMORY_MCP_AUTH_TOKEN": "${MEMORY_MCP_AUTH_TOKEN}",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    check = doctor._mcp_generated_config_check(config)
    rendered = json.dumps(check.details, sort_keys=True)

    assert check.ok is False
    assert check.details["agents"] == ["codex"]
    assert check.details["ready_agents"] == []
    assert check.details["configs"][0]["auth_source"] == "unresolved_env_placeholder"
    assert config.service_token not in rendered


def test_api_checks_include_visual_memory_browser_without_secret_leak(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.headers = kwargs["headers"]

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, path: str) -> httpx.Response:
            assert self.headers["Authorization"] == f"Bearer {config.service_token}"
            if path == "/v1/health":
                return httpx.Response(
                    200,
                    json={"status": "ok", "token": config.service_token},
                )
            if path == "/v1/capabilities":
                return httpx.Response(
                    200,
                    json={
                        "adapters": {},
                        "auth_token": config.service_token,
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
                                    ],
                                }
                            ]
                        },
                    },
                )
            if path == "/ui/":
                return httpx.Response(200, text="<title>Infinity Context Browser</title>")
            raise AssertionError(path)

    monkeypatch.setattr(doctor.httpx, "Client", FakeClient)

    checks = doctor._api_checks(config, timeout=1.0)
    by_name = {check.name: check for check in checks}
    rendered = json.dumps([check.details for check in checks], sort_keys=True)

    assert by_name["api_health"].ok is True
    assert by_name["api_capabilities"].ok is True
    assert by_name["ui_browser"].ok is True
    assert by_name["ui_browser"].details["title_present"] is True
    assert config.service_token not in rendered


def test_doctor_payload_includes_local_experience_without_secret_leak(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    config = init_local_config(home=home, repo_dir=repo)
    write_mcp_config(agent="codex", config=config)
    monkeypatch.setattr(doctor, "docker_available", lambda: True)
    monkeypatch.setattr(doctor, "docker_compose_available", lambda: True)

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
                return httpx.Response(
                    200,
                    json={
                        "adapters": {},
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
                                        "audio_metadata",
                                    ],
                                }
                            ]
                        },
                    },
                )
            if path == "/ui/":
                return httpx.Response(200, text="<title>Infinity Context Browser</title>")
            raise AssertionError(path)

    monkeypatch.setattr(doctor.httpx, "Client", FakeClient)

    payload = doctor.doctor_payload(config, doctor.run_doctor(config))
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["local_experience"]["status"] == "ready"
    assert payload["local_experience"]["ui_url"] == "http://127.0.0.1:7788/ui/"
    assert payload["local_experience"]["visual_memory_ready"] is True
    assert payload["local_experience"]["mcp_ready"] is True
    assert payload["local_experience"]["ready_agents"] == ["codex"]
    first_capture = payload["local_experience"]["first_capture"]
    assert first_capture["supports"] == [
        "text_note",
        "file_evidence",
        "audio_metadata_file",
        "document_file",
        "image_or_screenshot",
    ]
    assert first_capture["review_supported"] is True
    assert payload["local_experience"]["readiness"]["score"] == 10.0
    assert payload["local_experience"]["one_minute_path"][1]["status"] == "done"
    assert payload["local_experience"]["one_minute_path"][3]["status"] == "next"
    assert payload["local_experience"]["one_minute_path"][3]["url"] == (
        "http://127.0.0.1:7788/ui/#capture"
    )
    assert payload["local_experience"]["one_minute_path"][4]["url"] == (
        "http://127.0.0.1:7788/ui/#review"
    )
    assert config.service_token not in rendered


def test_doctor_payload_mcp_next_action_preserves_current_api_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    config = init_local_config(
        home=home,
        repo_dir=repo,
        api_url="http://127.0.0.1:17788",
    )
    monkeypatch.setattr(doctor, "docker_available", lambda: True)
    monkeypatch.setattr(doctor, "docker_compose_available", lambda: True)

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
                return httpx.Response(
                    200,
                    json={
                        "suggestions": {"review_tool_supported": True},
                        "context": {"answer_support_supported": True},
                    },
                )
            if path == "/ui/":
                return httpx.Response(200, text="<title>Infinity Context Browser</title>")
            raise AssertionError(path)

    monkeypatch.setattr(doctor.httpx, "Client", FakeClient)

    payload = doctor.doctor_payload(config, doctor.run_doctor(config))

    assert payload["local_experience"]["status"] == "mcp_config_not_ready"
    assert payload["local_experience"]["next_actions"] == [
        "Generate an MCP config with: MEMORY_API_URL=http://127.0.0.1:17788 "
        "infinity-context mcp-config --agent codex --write"
    ]
    assert payload["local_experience"]["one_minute_path"][2]["command"] == (
        "MEMORY_API_URL=http://127.0.0.1:17788 "
        "infinity-context mcp-config --agent codex --write"
    )


def test_doctor_payload_does_not_mark_ready_when_capabilities_auth_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    config = init_local_config(home=home, repo_dir=repo)
    write_mcp_config(agent="codex", config=config)
    monkeypatch.setattr(doctor, "docker_available", lambda: True)
    monkeypatch.setattr(doctor, "docker_compose_available", lambda: True)

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
                return httpx.Response(
                    401,
                    json={"error": "invalid token", "token": config.service_token},
                )
            if path == "/ui/":
                return httpx.Response(200, text="<title>Infinity Context Browser</title>")
            raise AssertionError(path)

    monkeypatch.setattr(doctor.httpx, "Client", FakeClient)

    payload = doctor.doctor_payload(config, doctor.run_doctor(config))
    capabilities_check = next(
        check for check in payload["checks"] if check["name"] == "api_capabilities"
    )

    assert payload["ok"] is False
    assert capabilities_check["details"]["status_code"] == 401
    assert "token" not in capabilities_check["details"]
    assert payload["local_experience"]["status"] == "runtime_not_ready"
    assert payload["local_experience"]["readiness"]["score"] == 6.0
    assert payload["local_experience"]["next_actions"] == [
        "API is reachable but auth is rejected; align the MCP token file with the "
        "running server token or restart the local runtime after updating the token file."
    ]


def test_doctor_payload_suggests_docker_published_url_when_api_url_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    config = init_local_config(home=home, repo_dir=repo)
    write_mcp_config(agent="codex", config=config)
    monkeypatch.setattr(doctor, "docker_available", lambda: True)
    monkeypatch.setattr(doctor, "docker_compose_available", lambda: True)
    monkeypatch.setattr(
        doctor,
        "docker_compose_published_server_urls",
        lambda _config: ["http://127.0.0.1:17788"],
    )

    class FakeClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeClient:
            raise httpx.ConnectError("configured API is not reachable")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(doctor.httpx, "Client", FakeClient)

    payload = doctor.doctor_payload(config, doctor.run_doctor(config))
    api_check = next(check for check in payload["checks"] if check["name"] == "api")

    assert payload["ok"] is False
    assert api_check["details"]["suggested_api_url"] == "http://127.0.0.1:17788"
    assert payload["local_experience"]["status"] == "runtime_not_ready"
    assert payload["local_experience"]["suggested_api_url"] == "http://127.0.0.1:17788"
    assert payload["local_experience"]["docker_published_api_urls"] == [
        "http://127.0.0.1:17788"
    ]
    assert payload["local_experience"]["next_actions"] == [
        "Configured API is unreachable; try the detected Docker URL with: "
        "MEMORY_API_URL=http://127.0.0.1:17788 infinity-context status",
        "Open and verify visual memory with: infinity-context ui --open --check",
    ]


def test_cli_status_human_output_is_first_use_summary_not_raw_capabilities(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    init_local_config(home=home, repo_dir=repo)

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
                return httpx.Response(
                    200,
                    json={
                        "very_verbose_marker": "should_not_render_in_human_status",
                        "suggestions": {"review_tool_supported": True},
                        "context": {"answer_support_supported": True},
                        "extraction": {
                            "profiles_v2": [
                                {
                                    "name": "standard_local",
                                    "enabled": True,
                                    "status": "ok",
                                    "input_modalities": ["text", "document", "image"],
                                }
                            ]
                        },
                    },
                )
            if path == "/ui/":
                return httpx.Response(200, text="<title>Infinity Context Browser</title>")
            raise AssertionError(path)

    monkeypatch.setattr(cli.httpx, "Client", FakeClient)

    exit_code = cli.main(["status"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "visual_memory: ready (http://127.0.0.1:7788/ui/)" in captured.out
    assert "capabilities: ready (HTTP 200)" in captured.out
    assert "capture_supports: text_note, file_evidence, document_file, image_or_screenshot" in (
        captured.out
    )
    assert "first_use_next: Capture (http://127.0.0.1:7788/ui/#capture)" in captured.out
    assert "review: ready (http://127.0.0.1:7788/ui/#review)" in captured.out
    assert "very_verbose_marker" not in captured.out
    assert "capabilities: {'" not in captured.out
    assert "status_code':" not in captured.out


def test_cli_doctor_human_output_is_concise_and_keeps_check_messages(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    config = init_local_config(home=home, repo_dir=repo)
    write_mcp_config(agent="codex", config=config)
    monkeypatch.setattr(doctor, "docker_available", lambda: True)
    monkeypatch.setattr(doctor, "docker_compose_available", lambda: True)

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
                return httpx.Response(
                    200,
                    json={
                        "very_verbose_marker": "should_not_render_in_human_doctor",
                        "suggestions": {"review_tool_supported": True},
                        "context": {"answer_support_supported": True},
                        "extraction": {
                            "profiles_v2": [
                                {
                                    "name": "standard_local",
                                    "enabled": True,
                                    "status": "ok",
                                    "input_modalities": ["text", "document"],
                                }
                            ]
                        },
                    },
                )
            if path == "/ui/":
                return httpx.Response(200, text="<title>Infinity Context Browser</title>")
            raise AssertionError(path)

    monkeypatch.setattr(doctor.httpx, "Client", FakeClient)

    exit_code = cli.main(["doctor"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "experience: ready" in captured.out
    assert "first_use_score: 10.0/10" in captured.out
    assert "next_actions:" in captured.out
    assert "checks:" in captured.out
    assert "  - [ok] repo_root: repo root resolved" in captured.out
    assert "  - [ok] api_capabilities: capabilities endpoint reachable" in captured.out
    assert "very_verbose_marker" not in captured.out
    assert "details':" not in captured.out
    assert "checks: [{'name'" not in captured.out
