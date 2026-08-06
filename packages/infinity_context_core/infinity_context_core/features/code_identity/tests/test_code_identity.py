"""Repository binding and repository-relative scope invariants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from infinity_context_core.features.code_identity.public import (
    CodeRepository,
    CodeRepositoryProvider,
    CodeRepositoryResolutionMethod,
    CodeScope,
    CodeScopeLevel,
    CodeWorktreeState,
    RepositoryEvidenceKind,
    RepositoryIdentityEvidence,
    ResolveCodeRepositoryCommand,
    ResolveCodeRepositoryHandler,
)

NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_worktree_evidence_resolves_one_canonical_repository() -> None:
    common_dir = _evidence(RepositoryEvidenceKind.GIT_COMMON_DIR, "common-dir")
    remote = _evidence(RepositoryEvidenceKind.NORMALIZED_REMOTE, "github/org/repo")
    repositories = InMemoryRepositories()
    handler = ResolveCodeRepositoryHandler(
        repositories=repositories,
        clock=FakeClock(),
        ids=FakeIds(),
    )

    created = asyncio.run(
        handler.execute(
            ResolveCodeRepositoryCommand(
                space_id="space-1",
                evidence=(common_dir, remote),
                provider=CodeRepositoryProvider.GITHUB,
                allow_create=True,
                safe_label="org/repo",
            )
        )
    )
    resolved_from_another_worktree = asyncio.run(
        handler.execute(
            ResolveCodeRepositoryCommand(
                space_id="space-1",
                evidence=(common_dir,),
                provider=CodeRepositoryProvider.LOCAL,
            )
        )
    )

    assert created.method is CodeRepositoryResolutionMethod.CREATED
    assert resolved_from_another_worktree.method is CodeRepositoryResolutionMethod.TRUSTED_EVIDENCE
    assert resolved_from_another_worktree.repository.repository_id == "repo-1"


def test_conflicting_alias_evidence_is_ambiguous_instead_of_last_write_wins() -> None:
    evidence_a = _evidence(RepositoryEvidenceKind.LOCAL_REGISTRY, "binding-a")
    evidence_b = _evidence(RepositoryEvidenceKind.LOCAL_REGISTRY, "binding-b")
    repositories = InMemoryRepositories(
        (
            _repository("repo-a", evidence_a),
            _repository("repo-b", evidence_b),
        )
    )

    with pytest.raises(ValueError, match="ambiguous"):
        asyncio.run(
            ResolveCodeRepositoryHandler(
                repositories=repositories,
                clock=FakeClock(),
                ids=FakeIds(),
            ).execute(
                ResolveCodeRepositoryCommand(
                    space_id="space-1",
                    evidence=(evidence_a, evidence_b),
                    provider=CodeRepositoryProvider.LOCAL,
                )
            )
        )


def test_matching_common_dir_cannot_auto_bind_a_different_remote() -> None:
    common_dir = _evidence(RepositoryEvidenceKind.GIT_COMMON_DIR, "common-dir")
    original_remote = _evidence(
        RepositoryEvidenceKind.NORMALIZED_REMOTE,
        "github/org/repo",
    )
    changed_remote = _evidence(
        RepositoryEvidenceKind.NORMALIZED_REMOTE,
        "github/attacker/repo",
    )
    repositories = InMemoryRepositories(
        (_repository_with_evidence("repo-a", (common_dir, original_remote)),)
    )

    with pytest.raises(ValueError, match="remote drift requires explicit review"):
        asyncio.run(
            ResolveCodeRepositoryHandler(
                repositories=repositories,
                clock=FakeClock(),
                ids=FakeIds(),
            ).execute(
                ResolveCodeRepositoryCommand(
                    space_id="space-1",
                    evidence=(common_dir, changed_remote),
                    provider=CodeRepositoryProvider.GITHUB,
                )
            )
        )

    assert repositories._repositories["repo-a"].evidence == (
        common_dir,
        original_remote,
    )


def test_code_scope_rejects_absolute_or_parent_paths_and_tracks_dirty_state() -> None:
    scope = CodeScope(
        repository_id="repo-1",
        scope_level=CodeScopeLevel.BRANCH,
        branch="feature/memory",
        worktree_state=CodeWorktreeState.DIRTY,
    )

    assert scope.worktree_state is CodeWorktreeState.DIRTY
    assert (
        scope.code_scope_id
        == CodeScope(
            repository_id="repo-1",
            scope_level=CodeScopeLevel.BRANCH,
            branch="feature/memory",
            commit_sha="a" * 40,
            worktree_state=CodeWorktreeState.CLEAN,
        ).code_scope_id
    )
    package = CodeScope(
        repository_id="repo-1",
        scope_level=CodeScopeLevel.PACKAGE,
        package_name="infinity-context-core",
    )
    assert package.code_scope_id.startswith("code-scope-v1-")
    with pytest.raises(ValueError, match="repository-relative"):
        CodeScope(
            repository_id="repo-1",
            scope_level=CodeScopeLevel.FILE,
            file_path_glob="/Users/alice/secret.py",
        )
    with pytest.raises(ValueError, match="repository-relative"):
        CodeScope(
            repository_id="repo-1",
            scope_level=CodeScopeLevel.FILE,
            file_path_glob="../secret.py",
        )


def _repository(
    repository_id: str,
    evidence: RepositoryIdentityEvidence,
) -> CodeRepository:
    return CodeRepository.create(
        repository_id=repository_id,
        space_id="space-1",
        provider=CodeRepositoryProvider.LOCAL,
        evidence=(evidence,),
        now=NOW,
    )


def _repository_with_evidence(
    repository_id: str,
    evidence: tuple[RepositoryIdentityEvidence, ...],
) -> CodeRepository:
    return CodeRepository.create(
        repository_id=repository_id,
        space_id="space-1",
        provider=CodeRepositoryProvider.LOCAL,
        evidence=evidence,
        now=NOW,
    )


def _evidence(
    kind: RepositoryEvidenceKind,
    value: str,
) -> RepositoryIdentityEvidence:
    return RepositoryIdentityEvidence(
        kind=kind,
        digest=sha256(value.encode()).hexdigest(),
    )


class InMemoryRepositories:
    def __init__(self, repositories: tuple[CodeRepository, ...] = ()) -> None:
        self._repositories = {repository.repository_id: repository for repository in repositories}

    async def get(self, repository_id: str) -> CodeRepository | None:
        return self._repositories.get(repository_id)

    async def find_by_evidence(
        self,
        *,
        space_id: str,
        evidence: tuple[RepositoryIdentityEvidence, ...],
    ) -> tuple[CodeRepository, ...]:
        requested = set(evidence)
        return tuple(
            repository
            for repository in self._repositories.values()
            if repository.space_id == space_id and requested.intersection(repository.evidence)
        )

    async def create(self, repository: CodeRepository) -> CodeRepository:
        self._repositories[repository.repository_id] = repository
        return repository

    async def save(self, repository: CodeRepository) -> CodeRepository:
        self._repositories[repository.repository_id] = repository
        return repository


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    def new_repository_id(self) -> str:
        return "repo-1"
