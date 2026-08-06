"""Workspace integration tests use only temporary Git repositories."""

from __future__ import annotations

import hmac
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from infinity_context_core.features.agent_authorization.public import (
    decode_workspace_scope_claim,
)
from infinity_context_mcp.plugin_hook import (
    HookEvent,
    HookSettings,
    MemoryHookGateway,
    MemoryPluginHookApp,
)
from infinity_context_mcp.workspace_binding import (
    GitRepositoryIdentityProbe,
    HookProjectScopeMode,
    InMemoryProjectScopeBindingStore,
    ProjectScopeBinding,
    ProjectScopeResolver,
    WorkspaceProbeStatus,
    normalize_git_remote,
)


def test_git_remote_normalization_removes_credentials_and_transport_spelling() -> None:
    assert normalize_git_remote("git@GitHub.com:Org/Repo.git") == "github.com/Org/Repo"
    assert (
        normalize_git_remote("https://token:secret@github.com/Org/Repo.git?x=1#fragment")
        == "github.com/Org/Repo"
    )


def test_worktrees_share_evidence_while_fork_with_other_origin_does_not(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    worktree = tmp_path / "worktree"
    fork = tmp_path / "fork"
    _init_repository(repository, remote="git@github.com:org/repository.git")
    _git(repository, "worktree", "add", "-b", "feature", str(worktree))
    _git(tmp_path, "clone", "--no-hardlinks", str(repository), str(fork))
    _git(fork, "remote", "set-url", "origin", "git@github.com:fork/repository.git")
    probe = GitRepositoryIdentityProbe()

    root_result = probe.probe(str(repository))
    worktree_result = probe.probe(str(worktree))
    fork_result = probe.probe(str(fork))

    assert root_result.status is WorkspaceProbeStatus.RESOLVED
    assert worktree_result.status is WorkspaceProbeStatus.RESOLVED
    assert set(root_result.evidence) == set(worktree_result.evidence)
    assert not set(root_result.evidence).intersection(fork_result.evidence)
    serialized = repr((root_result, worktree_result, fork_result))
    assert str(tmp_path) not in serialized
    assert "github.com" not in serialized


def test_auto_locked_never_falls_back_to_explicit_default() -> None:
    probe = GitRepositoryIdentityProbe()
    resolver = ProjectScopeResolver(
        mode=HookProjectScopeMode.AUTO_LOCKED,
        explicit_space_slug="default",
        explicit_memory_scope_external_ref="default",
        explicit_thread_external_ref=None,
        probe=probe,
        bindings=InMemoryProjectScopeBindingStore(),
    )

    assert resolver.resolve(cwd="/definitely/not/a/real/workspace") is None


def test_probe_fails_closed_when_git_head_cannot_be_resolved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from infinity_context_mcp import workspace_binding

    workspace = tmp_path / "transient-repository"
    workspace.mkdir()

    def fake_git(_workspace: Path, *args: str) -> str | None:
        if args[-1] == "--git-common-dir":
            return str(workspace / ".git")
        if args == ("remote",):
            return ""
        return None

    monkeypatch.setattr(workspace_binding, "_git", fake_git)

    result = GitRepositoryIdentityProbe().probe(str(workspace))

    assert result.status is WorkspaceProbeStatus.UNRESOLVED
    assert result.safe_reason == "git_head_unresolved"


def test_hook_uses_one_bound_scope_for_retrieval_and_capture(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _init_repository(repository, remote="git@github.com:org/repository.git")
    probe = GitRepositoryIdentityProbe()
    evidence = probe.probe(str(repository)).evidence
    binding = ProjectScopeBinding(
        binding_id="binding-1",
        binding_version=1,
        space_slug="project-space",
        memory_scope_external_ref="architecture",
        repository_id="repo-1",
        evidence=evidence,
        binding_grant="wg_test-binding-grant",
    )
    resolver = ProjectScopeResolver(
        mode=HookProjectScopeMode.AUTO_LOCKED,
        explicit_space_slug="default",
        explicit_memory_scope_external_ref="default",
        explicit_thread_external_ref=None,
        probe=probe,
        bindings=InMemoryProjectScopeBindingStore((binding,)),
    )
    settings = _settings()
    gateway = RecordingGateway(settings)
    app = MemoryPluginHookApp(
        settings=settings,
        gateway=gateway,
        scope_resolver=resolver,
    )

    result = app.run(
        HookEvent(
            name="UserPromptSubmit",
            payload={"prompt": "Remember this project decision."},
            raw_payload="",
            cwd=str(repository),
        )
    )

    assert result.exit_code == 0
    assert len(gateway.payloads) == 2
    assert {
        (payload["space_slug"], payload["memory_scope_external_ref"])
        for payload in gateway.payloads
    } == {("project-space", "architecture")}
    serialized = json.dumps(gateway.payloads, sort_keys=True)
    assert str(repository) not in serialized
    assert "github.com" not in serialized
    capture = next(payload for payload in gateway.payloads if "source_agent" in payload)
    context = next(payload for payload in gateway.payloads if "query" in payload)
    assert capture["metadata"]["repository_id"] == "repo-1"
    assert capture["metadata"]["code_scope_id"].startswith("code-scope-v1-")
    assert context["repository_id"] == "repo-1"
    assert context["code_scope_id"] == capture["metadata"]["code_scope_id"]
    assert "cwd" not in capture["metadata"]
    assert "cwd_hash" not in capture["metadata"]


def test_gateway_signs_short_lived_scope_from_trusted_binding(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _init_repository(repository, remote="git@github.com:org/repository.git")
    probe = GitRepositoryIdentityProbe()
    binding = ProjectScopeBinding(
        binding_id="binding-1",
        binding_version=3,
        space_slug="project-space",
        memory_scope_external_ref="architecture",
        repository_id="repo-1",
        evidence=probe.probe(str(repository)).evidence,
        binding_grant="wg_test-binding-grant",
    )
    scope = ProjectScopeResolver(
        mode=HookProjectScopeMode.AUTO_LOCKED,
        explicit_space_slug="default",
        explicit_memory_scope_external_ref="default",
        explicit_thread_external_ref=None,
        probe=probe,
        bindings=InMemoryProjectScopeBindingStore((binding,)),
    ).resolve(cwd=str(repository))
    assert scope is not None
    gateway = MemoryHookGateway(
        HookSettings.from_env(
            {
                "MEMORY_MCP_AUTH_TOKEN": "repository-token",
                "MEMORY_PLUGIN_PROJECT_SCOPE_MODE": "auto_locked",
            }
        )
    )

    headers = gateway._auth_header(scope)

    scheme, encoded, signature = headers["X-Infinity-Workspace-Claim"].split(".")
    assert scheme == "v1"
    assert hmac.compare_digest(
        signature,
        hmac.new(
            b"wg_test-binding-grant",
            f"v1.{encoded}".encode("ascii"),
            sha256,
        ).hexdigest(),
    )
    claim = decode_workspace_scope_claim(encoded)
    assert claim.repository_id == "repo-1"
    assert claim.code_scope_id == scope.code_scope_id
    assert claim.binding_id == "binding-1"
    assert claim.binding_version == 3


def _settings() -> HookSettings:
    return HookSettings.from_env(
        {
            "MEMORY_MCP_DEFAULT_SPACE_SLUG": "default",
            "MEMORY_MCP_DEFAULT_MEMORY_SCOPE_EXTERNAL_REF": "default",
            "MEMORY_PLUGIN_PROJECT_SCOPE_MODE": "auto_locked",
            "MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS": "UserPromptSubmit",
            "MEMORY_PLUGIN_HOOK_INGEST_EVENTS": "UserPromptSubmit",
            "MEMORY_PLUGIN_HOOK_CAPTURE_MODE": "captures",
            "MEMORY_MCP_AGENT_NAME": "test-agent",
        }
    )


class RecordingGateway(MemoryHookGateway):
    def __init__(self, settings: HookSettings) -> None:
        super().__init__(settings)
        self.payloads: list[dict[str, Any]] = []

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        *,
        scope=None,
    ) -> dict[str, Any]:
        if path == "/v1/capabilities":
            return {"captures": {"enabled": True, "api_version": 1, "mode": "suggest"}}
        self.payloads.append(payload)
        if path == "/v1/context":
            return {"data": {"rendered_text": "Project memory."}}
        return {"data": {"id": "capture-1"}}


def _init_repository(path: Path, *, remote: str) -> None:
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
    _git(path, "remote", "add", "origin", remote)


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-C", str(path), *args),
        check=True,
        capture_output=True,
        text=True,
    )
