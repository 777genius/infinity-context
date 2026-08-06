from __future__ import annotations

from pathlib import Path

import pytest

from e2e.canonical import E2EVerificationError
from e2e.lifecycle import (
    PINNED_DOCKER_HOST,
    DockerAdapterLifecycle,
    require_pinned_docker_host,
)


@pytest.mark.parametrize(
    "value",
    [None, "", "unix:///var/run/docker.sock", "unix:///run/user/994/docker.sock"],
)
def test_lifecycle_rejects_missing_or_unpinned_docker_host(monkeypatch, value) -> None:
    if value is None:
        monkeypatch.delenv("DOCKER_HOST", raising=False)
    else:
        monkeypatch.setenv("DOCKER_HOST", value)
    with pytest.raises(ValueError, match="e2e_docker_host_invalid"):
        require_pinned_docker_host()


def test_lifecycle_accepts_only_reviewed_dedicated_daemon_socket(
    tmp_path: Path, monkeypatch
) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    monkeypatch.setenv("DOCKER_HOST", PINNED_DOCKER_HOST)
    lifecycle = DockerAdapterLifecycle(
        compose_file=compose,
        project_name="mem0-v5-e2e-review",
    )
    assert lifecycle is not None


def test_lifecycle_rechecks_docker_host_before_each_subprocess(tmp_path: Path, monkeypatch) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n")
    monkeypatch.setenv("DOCKER_HOST", PINNED_DOCKER_HOST)
    lifecycle = DockerAdapterLifecycle(
        compose_file=compose,
        project_name="mem0-v5-e2e-review",
    )
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.setattr(
        "e2e.lifecycle.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("subprocess must not run for an unpinned daemon"),
    )
    with pytest.raises(E2EVerificationError, match="e2e_docker_host_invalid"):
        lifecycle._run(["docker", "compose", "version"])
