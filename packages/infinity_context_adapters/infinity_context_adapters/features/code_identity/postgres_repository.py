"""Postgres adapter for canonical CodeRepository and hashed alias evidence."""

from __future__ import annotations

from datetime import UTC, datetime

from infinity_context_core.features.code_identity.public import (
    FEATURE_ID,
    CodeRepository,
    CodeRepositoryProvider,
    CodeRepositoryStatus,
    RepositoryEvidenceKind,
    RepositoryIdentityEvidence,
)
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.feature_models import (
    CodeRepositoryAliasRow,
    CodeRepositoryRow,
)


class PostgresCodeRepository:
    adapter_name = "postgres"
    feature_id = FEATURE_ID

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, repository_id: str) -> CodeRepository | None:
        row = await self._session.get(CodeRepositoryRow, repository_id)
        if row is None:
            return None
        return _row_to_domain(row, await self._aliases(repository_id))

    async def find_by_evidence(
        self,
        *,
        space_id: str,
        evidence: tuple[RepositoryIdentityEvidence, ...],
    ) -> tuple[CodeRepository, ...]:
        if not evidence:
            return ()
        matches = or_(
            *(
                and_(
                    CodeRepositoryAliasRow.evidence_kind == item.kind.value,
                    CodeRepositoryAliasRow.evidence_digest == item.digest,
                )
                for item in evidence
            )
        )
        repository_ids = tuple(
            (
                await self._session.execute(
                    select(CodeRepositoryAliasRow.repository_id)
                    .where(CodeRepositoryAliasRow.space_id == space_id, matches)
                    .distinct()
                    .order_by(CodeRepositoryAliasRow.repository_id)
                )
            ).scalars()
        )
        repositories: list[CodeRepository] = []
        for repository_id in repository_ids:
            repository = await self.get(repository_id)
            if repository is not None:
                repositories.append(repository)
        return tuple(repositories)

    async def create(self, repository: CodeRepository) -> CodeRepository:
        if await self.get(repository.repository_id) is not None:
            raise ValueError("CodeRepository already exists")
        self._session.add(_domain_to_row(repository))
        await self._append_aliases(repository, existing=())
        return repository

    async def save(self, repository: CodeRepository) -> CodeRepository:
        expected_version = repository.version - 1
        if expected_version < 1:
            raise ValueError("CodeRepository version conflict")
        result = await self._session.execute(
            update(CodeRepositoryRow)
            .where(
                CodeRepositoryRow.id == repository.repository_id,
                CodeRepositoryRow.space_id == repository.space_id,
                CodeRepositoryRow.version == expected_version,
            )
            .values(
                provider=repository.provider.value,
                repo_key=repository.repo_key,
                safe_label=repository.safe_label,
                remote_url_hash=_remote_hash(repository.evidence),
                default_branch=repository.default_branch,
                monorepo_root=repository.monorepo_root,
                status=repository.status.value,
                version=repository.version,
                updated_at=repository.updated_at,
            )
        )
        if result.rowcount == 0:
            raise ValueError("CodeRepository version conflict")
        existing = await self._aliases(repository.repository_id)
        if not set(existing) <= set(repository.evidence):
            raise ValueError("CodeRepository alias evidence is append-only")
        await self._append_aliases(repository, existing=existing)
        return repository

    async def _aliases(
        self,
        repository_id: str,
    ) -> tuple[RepositoryIdentityEvidence, ...]:
        rows = tuple(
            (
                await self._session.execute(
                    select(CodeRepositoryAliasRow)
                    .where(CodeRepositoryAliasRow.repository_id == repository_id)
                    .order_by(CodeRepositoryAliasRow.id)
                )
            ).scalars()
        )
        return tuple(
            RepositoryIdentityEvidence(
                kind=RepositoryEvidenceKind(row.evidence_kind),
                digest=row.evidence_digest,
            )
            for row in rows
        )

    async def _append_aliases(
        self,
        repository: CodeRepository,
        *,
        existing: tuple[RepositoryIdentityEvidence, ...],
    ) -> None:
        known = set(existing)
        for evidence in repository.evidence:
            if evidence in known:
                continue
            self._session.add(
                CodeRepositoryAliasRow(
                    repository_id=repository.repository_id,
                    space_id=repository.space_id,
                    evidence_kind=evidence.kind.value,
                    evidence_digest=evidence.digest,
                    created_at=repository.updated_at,
                )
            )


def _domain_to_row(repository: CodeRepository) -> CodeRepositoryRow:
    return CodeRepositoryRow(
        id=repository.repository_id,
        space_id=repository.space_id,
        provider=repository.provider.value,
        repo_key=repository.repo_key,
        safe_label=repository.safe_label,
        remote_url_hash=_remote_hash(repository.evidence),
        default_branch=repository.default_branch,
        monorepo_root=repository.monorepo_root,
        status=repository.status.value,
        version=repository.version,
        created_at=repository.created_at,
        updated_at=repository.updated_at,
    )


def _row_to_domain(
    row: CodeRepositoryRow,
    evidence: tuple[RepositoryIdentityEvidence, ...],
) -> CodeRepository:
    return CodeRepository(
        repository_id=row.id,
        space_id=row.space_id,
        provider=CodeRepositoryProvider(row.provider),
        repo_key=row.repo_key,
        evidence=evidence,
        status=CodeRepositoryStatus(row.status),
        version=row.version,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
        safe_label=row.safe_label,
        default_branch=row.default_branch,
        monorepo_root=row.monorepo_root,
    )


def _remote_hash(evidence: tuple[RepositoryIdentityEvidence, ...]) -> str | None:
    return next(
        (item.digest for item in evidence if item.kind is RepositoryEvidenceKind.NORMALIZED_REMOTE),
        None,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


__all__ = ("PostgresCodeRepository",)
