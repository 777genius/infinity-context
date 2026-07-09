from __future__ import annotations

import json
import os
import stat
import tomllib
from pathlib import Path

from infinity_context_cli.config import _config_text, init_local_config, load_config
from infinity_context_cli.mcp_config import render_mcp_config, write_mcp_config


def test_cli_init_config_is_idempotent_and_keeps_token(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))

    first = init_local_config(home=home, repo_dir=repo)
    first_token = first.service_token
    second = init_local_config(home=home, repo_dir=repo)

    assert first_token.startswith("mst_")
    assert second.service_token == first_token
    assert second.config_path.exists()
    assert second.env_path.exists()
    assert "MEMORY_SERVICE_TOKEN=" in second.env_path.read_text(encoding="utf-8")


def test_cli_config_text_escapes_windows_paths() -> None:
    text = _config_text(
        home=Path("C:\\Users\\agent\\AppData\\Local\\Infinity Context"),
        repo_dir=Path("C:\\Users\\agent\\Projects\\infinity-context"),
        api_url="http://127.0.0.1:7788/",
    )

    data = tomllib.loads(text)

    assert data["local"]["home"] == "C:\\Users\\agent\\AppData\\Local\\Infinity Context"
    assert data["local"]["repo_dir"] == "C:\\Users\\agent\\Projects\\infinity-context"
    assert data["local"]["api_url"] == "http://127.0.0.1:7788"


def test_cli_load_config_supports_env_overrides(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    init_local_config(home=home, repo_dir=repo)
    monkeypatch.setenv("INFINITY_CONTEXT_HOME", str(home))
    monkeypatch.setenv("MEMORY_MCP_API_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("MEMORY_MCP_AUTH_TOKEN", "override-token")

    config = load_config()

    assert config.api_url == "http://127.0.0.1:9999"
    assert config.service_token == "override-token"


def test_mcp_config_redacts_token_by_default(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / "plugins" / "infinity-context-agent-plugin" / "bin").mkdir(parents=True)
    (
        repo / "plugins" / "infinity-context-agent-plugin" / "bin" / "infinity-context-mcp"
    ).write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    config = init_local_config(home=home, repo_dir=repo)

    rendered = render_mcp_config(agent="codex", config=config)
    written = write_mcp_config(agent="codex", config=config)
    rendered_env = json.loads(rendered)["infinity-context"]["env"]

    assert config.service_token not in rendered
    assert "${MEMORY_MCP_AUTH_TOKEN}" not in rendered
    assert "MEMORY_MCP_AUTH_TOKEN_FILE" in rendered
    assert rendered_env["MEMORY_MCP_AUTH_TOKEN_FILE"] == str(config.env_path)
    assert written.read_text(encoding="utf-8") == rendered + "\n"


def test_mcp_config_write_syncs_backing_token_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)
    config.env_path.write_text(
        "\n".join(
            [
                "MEMORY_SERVICE_TOKEN=stale-token",
                "MEMORY_POLICY_MODE=active_context",
                "",
            ]
        ),
        encoding="utf-8",
    )

    written = write_mcp_config(agent="codex", config=config)
    env_text = config.env_path.read_text(encoding="utf-8")

    assert f"MEMORY_SERVICE_TOKEN={config.service_token}" in env_text
    assert "MEMORY_POLICY_MODE=active_context" in env_text
    assert config.service_token not in written.read_text(encoding="utf-8")


def test_mcp_config_with_token_is_private(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    config = init_local_config(home=home, repo_dir=repo)

    written = write_mcp_config(agent="codex", config=config, include_token=True)

    assert config.service_token in written.read_text(encoding="utf-8")
    if os.name != "nt":
        assert stat.S_IMODE(written.stat().st_mode) == 0o600
