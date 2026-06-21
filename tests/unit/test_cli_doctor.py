from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from infinity_context_cli import doctor
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
                    json={"adapters": {}, "auth_token": config.service_token},
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
                return httpx.Response(200, json={"adapters": {}})
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
    assert payload["local_experience"]["first_capture"]["supports"] == [
        "text_note",
        "file_evidence",
    ]
    assert config.service_token not in rendered
