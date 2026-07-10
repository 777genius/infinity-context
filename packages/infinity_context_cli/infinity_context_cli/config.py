"""Local CLI configuration."""

from __future__ import annotations

import json
import os
import secrets
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOME = Path("~/.infinity-context").expanduser()
DEFAULT_API_URL = "http://127.0.0.1:7788"
DEFAULT_SERVICE_TOKEN = "local-dev-token"
DEFAULT_SPACE_SLUG = "default"
DEFAULT_MEMORY_SCOPE_EXTERNAL_REF = "default"


@dataclass(frozen=True)
class InfinityContextCliConfig:
    home: Path
    repo_dir: Path
    api_url: str
    service_token: str
    default_space_slug: str
    default_memory_scope_external_ref: str
    runtime_compose_profile: str
    compose_project_name: str

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    @property
    def env_path(self) -> Path:
        return self.home / ".env"


def load_config(home: Path | None = None) -> InfinityContextCliConfig:
    resolved_home = Path(
        os.environ.get("INFINITY_CONTEXT_HOME") or str(home or DEFAULT_HOME)
    ).expanduser()
    data = _read_toml(resolved_home / "config.toml")
    local = data.get("local", {}) if isinstance(data.get("local"), dict) else {}
    runtime = data.get("runtime", {}) if isinstance(data.get("runtime"), dict) else {}
    repo_dir = Path(
        os.environ.get("INFINITY_CONTEXT_REPO_ROOT")
        or str(local.get("repo_dir") or _default_repo_dir(resolved_home))
    ).expanduser()
    return InfinityContextCliConfig(
        home=resolved_home,
        repo_dir=repo_dir,
        api_url=str(
            os.environ.get("MEMORY_MCP_API_URL")
            or os.environ.get("MEMORY_API_URL")
            or local.get("api_url")
            or DEFAULT_API_URL
        ).rstrip("/"),
        service_token=str(
            os.environ.get("MEMORY_MCP_AUTH_TOKEN")
            or os.environ.get("MEMORY_SERVICE_TOKEN")
            or local.get("service_token")
            or _env_file_token(resolved_home / ".env")
            or DEFAULT_SERVICE_TOKEN
        ),
        default_space_slug=str(
            os.environ.get("MEMORY_MCP_DEFAULT_SPACE_SLUG")
            or os.environ.get("MEMORY_DEFAULT_SPACE_SLUG")
            or local.get("default_space_slug")
            or DEFAULT_SPACE_SLUG
        ),
        default_memory_scope_external_ref=str(
            os.environ.get("MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF")
            or os.environ.get("MEMORY_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF")
            or local.get("default_memory_scope_external_ref")
            or DEFAULT_MEMORY_SCOPE_EXTERNAL_REF
        ),
        runtime_compose_profile=str(
            runtime.get("compose_profile") or runtime.get("memory_scope") or "lite"
        ),
        compose_project_name=str(runtime.get("compose_project_name") or "infinity_context"),
    )


def init_local_config(
    *,
    home: Path,
    repo_dir: Path,
    api_url: str = DEFAULT_API_URL,
    force: bool = False,
) -> InfinityContextCliConfig:
    home = home.expanduser()
    repo_dir = repo_dir.expanduser()
    home.mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    (home / "run").mkdir(parents=True, exist_ok=True)
    config_path = home / "config.toml"
    env_path = home / ".env"
    if force or not config_path.exists():
        config_path.write_text(
            _config_text(home=home, repo_dir=repo_dir, api_url=api_url),
            encoding="utf-8",
        )
    if force or not env_path.exists():
        token = f"mst_{secrets.token_urlsafe(32)}"
        env_path.write_text(
            "\n".join(
                [
                    f"MEMORY_SERVICE_TOKEN={token}",
                    "MEMORY_POLICY_MODE=active_context",
                    "MEMORY_DEFAULT_SPACE_SLUG=default",
                    "MEMORY_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF=default",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        with suppress(OSError):
            env_path.chmod(0o600)
    return load_config(home)


def _read_toml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    with path.open("rb") as stream:
        loaded = tomllib.load(stream)
    return loaded if isinstance(loaded, dict) else {}


def _default_repo_dir(home: Path) -> Path:
    env_root = os.environ.get("INFINITY_CONTEXT_REPO_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    source_root = _source_repo_root()
    if source_root is not None:
        return source_root
    return home / "src"


def _source_repo_root() -> Path | None:
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / "docker-compose.yml").exists() and (parent / "pyproject.toml").exists():
            return parent
    return None


def _env_file_token(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MEMORY_SERVICE_TOKEN="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def _config_text(*, home: Path, repo_dir: Path, api_url: str) -> str:
    return "\n".join(
        [
            "[local]",
            f"home = {_toml_string(home)}",
            f"repo_dir = {_toml_string(repo_dir)}",
            f"api_url = {_toml_string(api_url.rstrip('/'))}",
            'default_space_slug = "default"',
            'default_memory_scope_external_ref = "default"',
            "",
            "[runtime]",
            'mode = "docker_compose"',
            'compose_profile = "lite"',
            'compose_project_name = "infinity_context"',
            "",
            "[mcp]",
            'write_mode = "suggest"',
            'delete_mode = "off"',
            'ingest_mode = "small_docs"',
            "",
        ]
    )


def _toml_string(value: object) -> str:
    return json.dumps(str(value))
