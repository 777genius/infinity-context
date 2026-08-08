"""Resolve trusted repository evidence to one canonical identity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from infinity_context_core.features.code_identity.domain import (
    CodeRepository,
    CodeRepositoryProvider,
    CodeRepositoryStatus,
    RepositoryIdentityEvidence,
)
from infinity_context_core.features.code_identity.ports import (
    CodeRepositoryClockPort,
    CodeRepositoryIdPort,
    CodeRepositoryPort,
)


class CodeRepositoryResolutionMethod(StrEnum):
    EXPLICIT = "explicit"
    TRUSTED_EVIDENCE = "trusted_evidence"
    CREATED = "created"


@dataclass(frozen=True, slots=True)
class ResolveCodeRepositoryCommand:
    space_id: str
    evidence: tuple[RepositoryIdentityEvidence, ...]
    provider: CodeRepositoryProvider
    explicit_repository_id: str | None = None
    allow_create: bool = False
    safe_label: str | None = None
    default_branch: str | None = None
    monorepo_root: str | None = None


@dataclass(frozen=True, slots=True)
class ResolveCodeRepositoryResult:
    repository: CodeRepository
    method: CodeRepositoryResolutionMethod


@dataclass(frozen=True, slots=True)
class ResolveCodeRepositoryHandler:
    repositories: CodeRepositoryPort
    clock: CodeRepositoryClockPort
    ids: CodeRepositoryIdPort

    async def execute(
        self,
        command: ResolveCodeRepositoryCommand,
    ) -> ResolveCodeRepositoryResult:
        if not command.space_id.strip():
            raise ValueError("Repository resolution requires space_id")
        if command.explicit_repository_id is not None:
            repository = await self.repositories.get(command.explicit_repository_id)
            if repository is None:
                raise LookupError("Explicit CodeRepository not found")
            _require_usable(repository, command.space_id)
            return ResolveCodeRepositoryResult(
                repository=repository,
                method=CodeRepositoryResolutionMethod.EXPLICIT,
            )
        if not command.evidence:
            raise ValueError("Automatic repository resolution requires trusted evidence")
        matches = await self.repositories.find_by_evidence(
            space_id=command.space_id,
            evidence=command.evidence,
        )
        if len(matches) > 1:
            raise ValueError("Repository identity evidence is ambiguous")
        if matches:
            repository = matches[0]
            _require_usable(repository, command.space_id)
            changed = repository.bind_evidence(
                command.evidence,
                expected_version=repository.version,
                now=self.clock.now(),
            )
            if changed is not repository:
                repository = await self.repositories.save(changed)
            return ResolveCodeRepositoryResult(
                repository=repository,
                method=CodeRepositoryResolutionMethod.TRUSTED_EVIDENCE,
            )
        if not command.allow_create:
            raise LookupError("Repository identity is unresolved")
        repository = CodeRepository.create(
            repository_id=self.ids.new_repository_id(),
            space_id=command.space_id,
            provider=command.provider,
            evidence=command.evidence,
            now=self.clock.now(),
            safe_label=command.safe_label,
            default_branch=command.default_branch,
            monorepo_root=command.monorepo_root,
        )
        return ResolveCodeRepositoryResult(
            repository=await self.repositories.create(repository),
            method=CodeRepositoryResolutionMethod.CREATED,
        )


def _require_usable(repository: CodeRepository, space_id: str) -> None:
    if repository.space_id != space_id:
        raise PermissionError("CodeRepository belongs to another MemorySpace")
    if repository.status is not CodeRepositoryStatus.ACTIVE:
        raise ValueError("CodeRepository is not active")


__all__ = (
    "CodeRepositoryResolutionMethod",
    "ResolveCodeRepositoryCommand",
    "ResolveCodeRepositoryHandler",
    "ResolveCodeRepositoryResult",
)
