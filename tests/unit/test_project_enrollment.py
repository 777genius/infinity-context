"""Project enrollment tests use only temporary Git repositories."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from infinity_context_mcp import project_enrollment
from infinity_context_mcp.workspace_binding import (
    GitRepositoryIdentityProbe,
    JsonProjectScopeBindingStore,
    code_scope_for_probe,
)


def test_enrollment_registers_hashed_evidence_and_writes_private_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = tmp_path / "repository"
    bindings_file = tmp_path / "config" / "bindings.json"
    _init_repository(repository)
    requests: list[dict[str, object]] = []

    def fake_post(_url: str, *, token: str, payload: dict[str, object]):
        assert token == "admin-token"
        requests.append(payload)
        scope = code_scope_for_probe(
            "repository-1",
            GitRepositoryIdentityProbe().probe(str(repository)),
        )
        return {
            "data": {
                "repository_id": "repository-1",
                "binding_id": "binding-1",
                "binding_version": 1,
                "binding_grant": "wg_test-binding-grant",
                "initial_code_scope": {
                    "authorization_id": "scope-authorization-1",
                    "code_scope_id": scope.code_scope_id,
                    "scope_level": scope.scope_level.value,
                    "status": "active",
                },
            }
        }

    monkeypatch.setattr(project_enrollment, "_post_json", fake_post)

    result = project_enrollment.enroll_project(
        cwd=str(repository),
        api_url="http://memory.invalid",
        admin_token="admin-token",
        space_id="space-1",
        space_slug="project-space",
        memory_scope_external_ref="architecture",
        bindings_file=str(bindings_file),
        safe_label="test-repository",
    )

    assert result["repository_id"] == "repository-1"
    assert str(result["code_scope_id"]).startswith("code-scope-v1-")
    assert requests[0]["initial_code_scope"]["scope_level"] == "branch"
    assert requests[0]["initial_code_scope"]["branch"] == "main"
    assert requests[0]["initial_code_scope"]["commit_sha"] is None
    assert bindings_file.stat().st_mode & 0o077 == 0
    payload = json.loads(bindings_file.read_text(encoding="utf-8"))
    serialized = json.dumps((payload, requests), sort_keys=True)
    assert str(repository) not in serialized
    assert "github.com" not in serialized
    evidence = GitRepositoryIdentityProbe().probe(str(repository)).evidence
    binding = JsonProjectScopeBindingStore(str(bindings_file)).resolve(evidence)
    assert binding is not None
    assert binding.repository_id == "repository-1"


def _init_repository(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / "README.md").write_text("test repository\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(
        path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "test: init",
    )
    _git(path, "remote", "add", "origin", "git@github.com:org/repository.git")


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-C", str(path), *args),
        check=True,
        capture_output=True,
        text=True,
    )
