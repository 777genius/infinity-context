"""Canonical storage ports for code repository identity."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from infinity_context_core.features.code_identity.domain import (
    CodeRepository,
    CodeScopeAuthorization,
    RepositoryIdentityEvidence,
)


class CodeRepositoryPort(Protocol):
    async def get(self, repository_id: str) -> CodeRepository | None:
        """Load a canonical repository identity."""

    async def find_by_evidence(
        self,
        *,
        space_id: str,
        evidence: tuple[RepositoryIdentityEvidence, ...],
    ) -> tuple[CodeRepository, ...]:
        """Resolve aliases without trusting raw path or remote values."""

    async def create(self, repository: CodeRepository) -> CodeRepository:
        """Persist a new repository and all of its evidence aliases."""

    async def save(self, repository: CodeRepository) -> CodeRepository:
        """Persist one optimistic repository revision."""


class CodeRepositoryClockPort(Protocol):
    def now(self) -> datetime:
        """Return timezone-aware transaction time."""


class CodeRepositoryIdPort(Protocol):
    def new_repository_id(self) -> str:
        """Return a new opaque repository id."""


class CodeScopeAuthorizationPort(Protocol):
    async def get(
        self,
        *,
        repository_id: str,
        space_id: str,
        code_scope_id: str,
    ) -> CodeScopeAuthorization | None:
        """Load one server-owned CodeScope authorization."""

    async def create(
        self,
        authorization: CodeScopeAuthorization,
    ) -> CodeScopeAuthorization:
        """Persist one immutable initial CodeScope authorization."""


class CodeScopeAuthorizationIdPort(Protocol):
    def new_code_scope_authorization_id(self) -> str:
        """Return a new opaque authorization id."""


__all__ = (
    "CodeRepositoryClockPort",
    "CodeRepositoryIdPort",
    "CodeRepositoryPort",
    "CodeScopeAuthorizationIdPort",
    "CodeScopeAuthorizationPort",
)
