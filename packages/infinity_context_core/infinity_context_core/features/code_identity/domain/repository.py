"""Canonical code repository identity and safe alias evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class CodeRepositoryProvider(StrEnum):
    LOCAL = "local"
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    MANUAL = "manual"


class CodeRepositoryStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class RepositoryEvidenceKind(StrEnum):
    NORMALIZED_REMOTE = "normalized_remote"
    GIT_COMMON_DIR = "git_common_dir"
    LOCAL_REGISTRY = "local_registry"
    PATH_FALLBACK = "path_fallback"


@dataclass(frozen=True, slots=True)
class RepositoryIdentityEvidence:
    kind: RepositoryEvidenceKind
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", RepositoryEvidenceKind(self.kind))
        if not _SHA256_RE.fullmatch(self.digest):
            raise ValueError("Repository evidence digest must be lowercase sha256")


@dataclass(frozen=True, slots=True)
class CodeRepository:
    repository_id: str
    space_id: str
    provider: CodeRepositoryProvider
    repo_key: str
    evidence: tuple[RepositoryIdentityEvidence, ...]
    status: CodeRepositoryStatus
    version: int
    created_at: datetime
    updated_at: datetime
    safe_label: str | None = None
    default_branch: str | None = None
    monorepo_root: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", CodeRepositoryProvider(self.provider))
        object.__setattr__(self, "status", CodeRepositoryStatus(self.status))
        for field_name in ("repository_id", "space_id", "repo_key"):
            _require_non_blank(field_name, getattr(self, field_name))
        if self.version < 1:
            raise ValueError("CodeRepository version must be positive")
        if not self.evidence:
            raise ValueError("CodeRepository requires identity evidence")
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError("CodeRepository evidence must be unique")
        _require_aware("created_at", self.created_at)
        _require_aware("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ValueError("CodeRepository updated_at cannot precede created_at")
        if self.safe_label is not None:
            _require_safe_label(self.safe_label)
        if self.default_branch is not None:
            _require_ref_name("default_branch", self.default_branch)
        if self.monorepo_root is not None:
            _require_relative_path("monorepo_root", self.monorepo_root)

    @classmethod
    def create(
        cls,
        *,
        repository_id: str,
        space_id: str,
        provider: CodeRepositoryProvider,
        evidence: tuple[RepositoryIdentityEvidence, ...],
        now: datetime,
        safe_label: str | None = None,
        default_branch: str | None = None,
        monorepo_root: str | None = None,
    ) -> CodeRepository:
        return cls(
            repository_id=repository_id,
            space_id=space_id,
            provider=provider,
            repo_key=f"repository-v1-{repository_id}",
            evidence=tuple(dict.fromkeys(evidence)),
            status=CodeRepositoryStatus.ACTIVE,
            version=1,
            created_at=now,
            updated_at=now,
            safe_label=safe_label,
            default_branch=default_branch,
            monorepo_root=monorepo_root,
        )

    def bind_evidence(
        self,
        evidence: tuple[RepositoryIdentityEvidence, ...],
        *,
        expected_version: int,
        now: datetime,
    ) -> CodeRepository:
        if self.version != expected_version:
            raise ValueError(
                f"CodeRepository version conflict: expected {expected_version}, "
                f"actual {self.version}"
            )
        if self.status is not CodeRepositoryStatus.ACTIVE:
            raise ValueError("Only active CodeRepository can accept evidence")
        _require_aware("now", now)
        if now < self.updated_at:
            raise ValueError("CodeRepository transaction time cannot move backwards")
        _require_no_remote_drift(self.evidence, evidence)
        merged = tuple(dict.fromkeys((*self.evidence, *evidence)))
        if merged == self.evidence:
            return self
        return replace(
            self,
            evidence=merged,
            version=self.version + 1,
            updated_at=now,
        )


def _require_no_remote_drift(
    existing: tuple[RepositoryIdentityEvidence, ...],
    observed: tuple[RepositoryIdentityEvidence, ...],
) -> None:
    existing_remotes = {
        item.digest for item in existing if item.kind is RepositoryEvidenceKind.NORMALIZED_REMOTE
    }
    observed_remotes = {
        item.digest for item in observed if item.kind is RepositoryEvidenceKind.NORMALIZED_REMOTE
    }
    if existing_remotes and observed_remotes and not observed_remotes <= existing_remotes:
        raise ValueError("Repository remote drift requires explicit review")


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_non_blank(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _require_safe_label(value: str) -> None:
    _require_non_blank("safe_label", value)
    if "://" in value or "@" in value or "\\" in value or value.startswith("/"):
        raise ValueError("safe_label cannot contain remote URL or absolute path")


def _require_ref_name(field_name: str, value: str) -> None:
    _require_non_blank(field_name, value)
    if any(character in value for character in ("\x00", "\n", "\r")):
        raise ValueError(f"{field_name} contains control characters")


def _require_relative_path(field_name: str, value: str) -> None:
    _require_non_blank(field_name, value)
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError(f"{field_name} must be a safe relative path")


__all__ = (
    "CodeRepository",
    "CodeRepositoryProvider",
    "CodeRepositoryStatus",
    "RepositoryEvidenceKind",
    "RepositoryIdentityEvidence",
)
