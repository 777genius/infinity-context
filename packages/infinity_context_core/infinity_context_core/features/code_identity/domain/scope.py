"""Repository-relative code scope attached to facts and retrieval queries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class CodeScopeEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"
    UNKNOWN = "unknown"


class CodeWorktreeState(StrEnum):
    CLEAN = "clean"
    DIRTY = "dirty"
    UNKNOWN = "unknown"


class CodeScopeLevel(StrEnum):
    GLOBAL = "global"
    REPOSITORY = "repository"
    BRANCH = "branch"
    PULL_REQUEST = "pull_request"
    COMMIT = "commit"
    PACKAGE = "package"
    FILE = "file"
    SYMBOL = "symbol"


@dataclass(frozen=True, slots=True)
class CodeScope:
    repository_id: str | None
    scope_level: CodeScopeLevel
    branch: str | None = None
    commit_sha: str | None = None
    pull_request_id: str | None = None
    package_name: str | None = None
    module_path: str | None = None
    file_path_glob: str | None = None
    environment: CodeScopeEnvironment = CodeScopeEnvironment.UNKNOWN
    worktree_state: CodeWorktreeState = CodeWorktreeState.UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_level", CodeScopeLevel(self.scope_level))
        object.__setattr__(self, "environment", CodeScopeEnvironment(self.environment))
        object.__setattr__(self, "worktree_state", CodeWorktreeState(self.worktree_state))
        if self.scope_level is not CodeScopeLevel.GLOBAL and not self.repository_id:
            raise ValueError("Non-global CodeScope requires repository_id")
        if self.repository_id is not None and not self.repository_id.strip():
            raise ValueError("repository_id cannot be blank")
        for field_name in ("branch", "pull_request_id", "package_name"):
            value = getattr(self, field_name)
            if value is not None:
                _require_safe_text(field_name, value)
        if self.commit_sha is not None:
            normalized = self.commit_sha.casefold()
            if not 7 <= len(normalized) <= 64 or any(
                character not in "0123456789abcdef" for character in normalized
            ):
                raise ValueError("commit_sha must be a 7-64 character hex digest")
            object.__setattr__(self, "commit_sha", normalized)
        for field_name in ("module_path", "file_path_glob"):
            value = getattr(self, field_name)
            if value is not None:
                _require_relative_path(field_name, value)
        _require_level_evidence(self)

    @property
    def code_scope_id(self) -> str:
        identity_fields: dict[str, str | None] = {
            "repository_id": self.repository_id,
            "scope_level": self.scope_level.value,
            "environment": self.environment.value,
        }
        if self.scope_level is CodeScopeLevel.BRANCH:
            identity_fields["branch"] = self.branch
        elif self.scope_level is CodeScopeLevel.PULL_REQUEST:
            identity_fields["pull_request_id"] = self.pull_request_id
        elif self.scope_level is CodeScopeLevel.COMMIT:
            identity_fields["commit_sha"] = self.commit_sha
        elif self.scope_level is CodeScopeLevel.PACKAGE:
            identity_fields["package_name"] = self.package_name
        elif self.scope_level in {CodeScopeLevel.FILE, CodeScopeLevel.SYMBOL}:
            identity_fields.update(
                {
                    "branch": self.branch,
                    "commit_sha": self.commit_sha,
                    "pull_request_id": self.pull_request_id,
                    "package_name": self.package_name,
                    "module_path": self.module_path,
                    "file_path_glob": self.file_path_glob,
                }
            )
        payload = json.dumps(
            identity_fields,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return f"code-scope-v1-{digest}"

    @property
    def authorization_evidence_digest(self) -> str:
        payload = f"code-scope-authorization-v1:{self.code_scope_id}"
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class CodeScopeDescriptor:
    """Repository-independent descriptor accepted at enrollment time."""

    scope_level: CodeScopeLevel
    branch: str | None = None
    commit_sha: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_level", CodeScopeLevel(self.scope_level))
        if self.scope_level not in {
            CodeScopeLevel.REPOSITORY,
            CodeScopeLevel.BRANCH,
            CodeScopeLevel.COMMIT,
        }:
            raise ValueError("Enrollment CodeScope descriptor must be repository, branch or commit")
        self.resolve("descriptor-validation")

    def resolve(self, repository_id: str) -> CodeScope:
        return CodeScope(
            repository_id=repository_id,
            scope_level=self.scope_level,
            branch=self.branch,
            commit_sha=self.commit_sha,
        )


def _require_level_evidence(scope: CodeScope) -> None:
    required = {
        CodeScopeLevel.BRANCH: scope.branch,
        CodeScopeLevel.PULL_REQUEST: scope.pull_request_id,
        CodeScopeLevel.COMMIT: scope.commit_sha,
        CodeScopeLevel.PACKAGE: scope.package_name,
        CodeScopeLevel.FILE: scope.file_path_glob,
        CodeScopeLevel.SYMBOL: scope.module_path or scope.file_path_glob,
    }.get(scope.scope_level, True)
    if not required:
        raise ValueError(f"{scope.scope_level.value} CodeScope lacks identifying evidence")


def _require_relative_path(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError(f"{field_name} must be repository-relative")


def _require_safe_text(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if len(value) > 240 or any(character in value for character in ("\x00", "\n", "\r")):
        raise ValueError(f"{field_name} is invalid")


__all__ = (
    "CodeScope",
    "CodeScopeDescriptor",
    "CodeScopeEnvironment",
    "CodeScopeLevel",
    "CodeWorktreeState",
)
