"""Trusted workspace routing without making Git evidence canonical domain identity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat as stat_module
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from infinity_context_core.features.code_identity.public import (
    CodeScope,
    CodeScopeLevel,
    CodeWorktreeState,
    RepositoryEvidenceKind,
    RepositoryIdentityEvidence,
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class HookProjectScopeMode(StrEnum):
    EXPLICIT = "explicit"
    SHADOW = "shadow"
    AUTO_LOCKED = "auto_locked"


class WorkspaceProbeStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class WorkspaceProbeResult:
    status: WorkspaceProbeStatus
    evidence: tuple[RepositoryIdentityEvidence, ...] = ()
    branch: str | None = None
    commit_sha: str | None = None
    worktree_state: CodeWorktreeState = CodeWorktreeState.UNKNOWN
    safe_reason: str = ""


@dataclass(frozen=True, slots=True)
class ProjectScopeBinding:
    binding_id: str
    binding_version: int
    space_slug: str
    memory_scope_external_ref: str
    repository_id: str
    evidence: tuple[RepositoryIdentityEvidence, ...]
    drift_status: str = "stable"
    binding_grant: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "space_slug",
            "memory_scope_external_ref",
            "repository_id",
            "drift_status",
        ):
            _require_safe_identifier(field_name, getattr(self, field_name))
        if self.binding_version < 1:
            raise ValueError("binding_version must be positive")
        if not self.evidence:
            raise ValueError("Project binding requires evidence")
        if self.binding_grant is not None:
            _require_binding_grant(self.binding_grant)


@dataclass(frozen=True, slots=True)
class ResolvedAgentScope:
    space_slug: str
    memory_scope_external_ref: str
    thread_external_ref: str | None
    repository_id: str | None
    code_scope_id: str | None
    binding_id: str | None
    binding_version: int | None
    resolution_method: str
    drift_status: str = "stable"
    branch: str | None = None
    commit_sha: str | None = None
    worktree_state: CodeWorktreeState = CodeWorktreeState.UNKNOWN
    binding_grant: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for field_name in (
            "space_slug",
            "memory_scope_external_ref",
            "resolution_method",
            "drift_status",
        ):
            _require_safe_identifier(field_name, getattr(self, field_name))
        if self.thread_external_ref is not None:
            _require_safe_identifier("thread_external_ref", self.thread_external_ref)
        if self.repository_id is not None:
            _require_safe_identifier("repository_id", self.repository_id)
        if self.code_scope_id is not None:
            _require_safe_identifier("code_scope_id", self.code_scope_id)
            if self.repository_id is None:
                raise ValueError("code_scope_id requires repository_id")
        if self.binding_id is not None:
            _require_safe_identifier("binding_id", self.binding_id)
        if self.binding_version is not None and self.binding_version < 1:
            raise ValueError("binding_version must be positive")
        if self.branch is not None:
            _require_safe_identifier("branch", self.branch)
        if self.commit_sha is not None and not re.fullmatch(r"[0-9a-fA-F]{7,64}", self.commit_sha):
            raise ValueError("commit_sha must be a 7-64 character hex digest")
        object.__setattr__(self, "worktree_state", CodeWorktreeState(self.worktree_state))
        if self.binding_grant is not None:
            _require_binding_grant(self.binding_grant)

    @property
    def idempotency_namespace(self) -> str:
        repository = self.repository_id or "no-repository"
        binding = self.binding_id or "explicit"
        code_scope = self.code_scope_id or "no-code-scope"
        revision = self.commit_sha or "no-commit"
        return (
            f"{self.space_slug}:{self.memory_scope_external_ref}:{repository}:"
            f"{code_scope}:{revision}:{self.worktree_state.value}:{binding}"
        )


class RepositoryIdentityProbePort(Protocol):
    def probe(self, cwd: str) -> WorkspaceProbeResult:
        """Return only sanitized/hash evidence for one workspace."""


class ProjectScopeBindingStorePort(Protocol):
    def resolve(
        self,
        evidence: tuple[RepositoryIdentityEvidence, ...],
    ) -> ProjectScopeBinding | None:
        """Resolve a trusted local binding or return None on ambiguity/unresolved state."""


class AgentScopeResolverPort(Protocol):
    def resolve(self, *, cwd: str) -> ResolvedAgentScope | None:
        """Resolve one immutable scope result for an entire hook event."""


@dataclass(frozen=True, slots=True)
class ProjectScopeResolver:
    mode: HookProjectScopeMode
    explicit_space_slug: str
    explicit_memory_scope_external_ref: str
    explicit_thread_external_ref: str | None
    probe: RepositoryIdentityProbePort | None = None
    bindings: ProjectScopeBindingStorePort | None = None
    explicit_repository_id: str | None = None

    def resolve(self, *, cwd: str) -> ResolvedAgentScope | None:
        explicit = ResolvedAgentScope(
            space_slug=self.explicit_space_slug,
            memory_scope_external_ref=self.explicit_memory_scope_external_ref,
            thread_external_ref=self.explicit_thread_external_ref,
            repository_id=self.explicit_repository_id,
            code_scope_id=None,
            binding_id=None,
            binding_version=None,
            resolution_method="explicit",
        )
        mode = HookProjectScopeMode(self.mode)
        if mode is HookProjectScopeMode.EXPLICIT:
            return explicit
        if self.probe is None or self.bindings is None:
            return explicit if mode is HookProjectScopeMode.SHADOW else None
        probe = self.probe.probe(cwd)
        if probe.status is not WorkspaceProbeStatus.RESOLVED:
            return explicit if mode is HookProjectScopeMode.SHADOW else None
        binding = self.bindings.resolve(probe.evidence)
        if (
            binding is None
            or binding.drift_status != "stable"
            or (mode is HookProjectScopeMode.AUTO_LOCKED and binding.binding_grant is None)
        ):
            return explicit if mode is HookProjectScopeMode.SHADOW else None
        if mode is HookProjectScopeMode.SHADOW:
            return ResolvedAgentScope(
                space_slug=explicit.space_slug,
                memory_scope_external_ref=explicit.memory_scope_external_ref,
                thread_external_ref=explicit.thread_external_ref,
                repository_id=binding.repository_id,
                code_scope_id=code_scope_id_for_probe(binding.repository_id, probe),
                binding_id=binding.binding_id,
                binding_version=binding.binding_version,
                resolution_method="shadow",
                drift_status=binding.drift_status,
                branch=probe.branch,
                commit_sha=probe.commit_sha,
                worktree_state=probe.worktree_state,
                binding_grant=binding.binding_grant,
            )
        return ResolvedAgentScope(
            space_slug=binding.space_slug,
            memory_scope_external_ref=binding.memory_scope_external_ref,
            thread_external_ref=self.explicit_thread_external_ref,
            repository_id=binding.repository_id,
            code_scope_id=code_scope_id_for_probe(binding.repository_id, probe),
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            resolution_method="trusted_binding",
            drift_status=binding.drift_status,
            branch=probe.branch,
            commit_sha=probe.commit_sha,
            worktree_state=probe.worktree_state,
            binding_grant=binding.binding_grant,
        )


class InMemoryProjectScopeBindingStore:
    def __init__(self, bindings: tuple[ProjectScopeBinding, ...] = ()) -> None:
        self._bindings = bindings

    def resolve(
        self,
        evidence: tuple[RepositoryIdentityEvidence, ...],
    ) -> ProjectScopeBinding | None:
        matches = tuple(
            binding
            for binding in self._bindings
            if _binding_matches_evidence(binding.evidence, evidence)
        )
        return matches[0] if len(matches) == 1 else None


class JsonProjectScopeBindingStore:
    """Read trusted local bindings; malformed or overly permissive files fail unresolved."""

    def __init__(self, path: str) -> None:
        self._path = Path(path).expanduser()

    def resolve(
        self,
        evidence: tuple[RepositoryIdentityEvidence, ...],
    ) -> ProjectScopeBinding | None:
        bindings = self._load()
        return InMemoryProjectScopeBindingStore(bindings).resolve(evidence)

    def _load(self) -> tuple[ProjectScopeBinding, ...]:
        try:
            stat = self._path.stat()
            if stat.st_size > 1_000_000 or stat_module.S_IMODE(stat.st_mode) != 0o600:
                return ()
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ()
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return ()
        raw_bindings = payload.get("bindings")
        if not isinstance(raw_bindings, list):
            return ()
        try:
            return tuple(_binding_from_json(item) for item in raw_bindings)
        except (KeyError, TypeError, ValueError):
            return ()


@dataclass(frozen=True, slots=True)
class GitRepositoryIdentityProbe:
    remote_name: str | None = None
    allow_path_fallback: bool = True

    def probe(self, cwd: str) -> WorkspaceProbeResult:
        workspace = Path(cwd).resolve()
        common_dir = _git(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if common_dir is None:
            if not self.allow_path_fallback:
                return WorkspaceProbeResult(
                    status=WorkspaceProbeStatus.UNRESOLVED,
                    safe_reason="not_git",
                )
            return WorkspaceProbeResult(
                status=WorkspaceProbeStatus.RESOLVED,
                evidence=(_evidence(RepositoryEvidenceKind.PATH_FALLBACK, str(workspace)),),
                safe_reason="path_fallback",
            )
        evidence: list[RepositoryIdentityEvidence] = [
            _evidence(RepositoryEvidenceKind.GIT_COMMON_DIR, common_dir)
        ]
        remote = _select_remote(workspace, configured=self.remote_name)
        if remote.status is WorkspaceProbeStatus.AMBIGUOUS:
            return remote
        if remote.evidence:
            evidence.extend(remote.evidence)
        branch = _git(workspace, "symbolic-ref", "--quiet", "--short", "HEAD")
        commit = _git(workspace, "rev-parse", "--verify", "HEAD")
        if branch is None and commit is None:
            return WorkspaceProbeResult(
                status=WorkspaceProbeStatus.UNRESOLVED,
                evidence=tuple(evidence),
                safe_reason="git_head_unresolved",
            )
        dirty = _git(workspace, "status", "--porcelain", "--untracked-files=no")
        return WorkspaceProbeResult(
            status=WorkspaceProbeStatus.RESOLVED,
            evidence=tuple(evidence),
            branch=branch,
            commit_sha=commit,
            worktree_state=(
                CodeWorktreeState.UNKNOWN
                if dirty is None
                else CodeWorktreeState.DIRTY
                if dirty
                else CodeWorktreeState.CLEAN
            ),
            safe_reason="git_evidence",
        )


def normalize_git_remote(value: str) -> str:
    """Normalize transport spelling while removing credentials and query data."""

    candidate = value.strip()
    if not candidate or len(candidate) > 2048 or _CONTROL_RE.search(candidate):
        raise ValueError("Git remote is invalid")
    if "://" not in candidate and re.fullmatch(r"[^@\s]+@[^:\s]+:.+", candidate):
        _user, host_path = candidate.split("@", 1)
        host, path = host_path.split(":", 1)
        candidate = f"ssh://{host}/{path}"
    parsed = urllib.parse.urlsplit(candidate)
    if not parsed.hostname:
        raise ValueError("Git remote host is required")
    host = parsed.hostname.casefold()
    port = f":{parsed.port}" if parsed.port is not None else ""
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path or path == "/":
        raise ValueError("Git remote repository path is required")
    return f"{host}{port}/{path.lstrip('/')}"


def code_scope_for_probe(repository_id: str, probe: WorkspaceProbeResult) -> CodeScope:
    """Build the canonical scope identity from one immutable Git probe result."""

    if probe.branch is not None:
        return CodeScope(
            repository_id=repository_id,
            scope_level=CodeScopeLevel.BRANCH,
            branch=probe.branch,
            commit_sha=probe.commit_sha,
            worktree_state=probe.worktree_state,
        )
    elif probe.commit_sha is not None:
        return CodeScope(
            repository_id=repository_id,
            scope_level=CodeScopeLevel.COMMIT,
            commit_sha=probe.commit_sha,
            worktree_state=probe.worktree_state,
        )
    return CodeScope(
        repository_id=repository_id,
        scope_level=CodeScopeLevel.REPOSITORY,
        worktree_state=probe.worktree_state,
    )


def code_scope_id_for_probe(repository_id: str, probe: WorkspaceProbeResult) -> str:
    return code_scope_for_probe(repository_id, probe).code_scope_id


def _select_remote(workspace: Path, *, configured: str | None) -> WorkspaceProbeResult:
    remotes_raw = _git(workspace, "remote")
    remotes = tuple(
        sorted(line.strip() for line in (remotes_raw or "").splitlines() if line.strip())
    )
    if configured:
        selected = configured if configured in remotes else None
    elif "origin" in remotes:
        selected = "origin"
    elif len(remotes) == 1:
        selected = remotes[0]
    elif len(remotes) > 1:
        return WorkspaceProbeResult(
            status=WorkspaceProbeStatus.AMBIGUOUS,
            safe_reason="multiple_remotes",
        )
    else:
        selected = None
    if selected is None:
        return WorkspaceProbeResult(status=WorkspaceProbeStatus.RESOLVED)
    remote_url = _git(workspace, "remote", "get-url", selected)
    if remote_url is None:
        return WorkspaceProbeResult(
            status=WorkspaceProbeStatus.UNRESOLVED,
            safe_reason="remote_unreadable",
        )
    try:
        normalized = normalize_git_remote(remote_url)
    except ValueError:
        return WorkspaceProbeResult(
            status=WorkspaceProbeStatus.UNRESOLVED,
            safe_reason="remote_invalid",
        )
    return WorkspaceProbeResult(
        status=WorkspaceProbeStatus.RESOLVED,
        evidence=(_evidence(RepositoryEvidenceKind.NORMALIZED_REMOTE, normalized),),
    )


def _git(workspace: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", "-C", str(workspace), *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
            shell=False,
            env={
                "PATH": os.environ.get("PATH", os.defpath),
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _evidence(kind: RepositoryEvidenceKind, value: str) -> RepositoryIdentityEvidence:
    return RepositoryIdentityEvidence(
        kind=kind,
        digest=hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest(),
    )


def _binding_from_json(value: object) -> ProjectScopeBinding:
    if not isinstance(value, dict):
        raise ValueError("Project binding must be an object")
    raw_evidence = value["evidence"]
    if not isinstance(raw_evidence, list):
        raise ValueError("Project binding evidence must be a list")
    evidence = tuple(
        RepositoryIdentityEvidence(
            kind=RepositoryEvidenceKind(item["kind"]),
            digest=str(item["digest"]),
        )
        for item in raw_evidence
        if isinstance(item, dict)
    )
    return ProjectScopeBinding(
        binding_id=str(value["binding_id"]),
        binding_version=int(value["binding_version"]),
        space_slug=str(value["space_slug"]),
        memory_scope_external_ref=str(value["memory_scope_external_ref"]),
        repository_id=str(value["repository_id"]),
        evidence=evidence,
        drift_status=str(value.get("drift_status", "stable")),
        binding_grant=str(value["binding_grant"]),
    )


def _binding_matches_evidence(
    bound: tuple[RepositoryIdentityEvidence, ...],
    observed: tuple[RepositoryIdentityEvidence, ...],
) -> bool:
    bound_set = set(bound)
    observed_set = set(observed)
    remote_kind = RepositoryEvidenceKind.NORMALIZED_REMOTE
    bound_remotes = {item for item in bound_set if item.kind is remote_kind}
    observed_remotes = {item for item in observed_set if item.kind is remote_kind}
    if bound_remotes or observed_remotes:
        return bool(bound_remotes.intersection(observed_remotes))
    return bool(bound_set.intersection(observed_set))


def _require_safe_identifier(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if "://" in value or "\\" in value or value.startswith("/") or "@" in value:
        raise ValueError(f"{field_name} cannot contain raw path or remote credentials")


def _require_binding_grant(value: str) -> None:
    if not value.startswith("wg_") or len(value) > 160 or not value.isascii():
        raise ValueError("binding_grant is invalid")


__all__ = (
    "AgentScopeResolverPort",
    "GitRepositoryIdentityProbe",
    "HookProjectScopeMode",
    "InMemoryProjectScopeBindingStore",
    "JsonProjectScopeBindingStore",
    "ProjectScopeBinding",
    "ProjectScopeBindingStorePort",
    "ProjectScopeResolver",
    "RepositoryIdentityProbePort",
    "ResolvedAgentScope",
    "WorkspaceProbeResult",
    "WorkspaceProbeStatus",
    "code_scope_for_probe",
    "code_scope_id_for_probe",
    "normalize_git_remote",
)
