"""Postgres checks for canonical repository identity and hashed aliases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from infinity_context_adapters.features.code_identity import PostgresCodeRepository
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_adapters.postgres.feature_models import (
    CodeRepositoryAliasRow,
    CodeRepositoryRow,
)
from infinity_context_adapters.postgres.models import (
    MemorySpaceRow,
)
from infinity_context_core.features.code_identity.public import (
    CodeRepositoryProvider,
    CodeRepositoryResolutionMethod,
    RepositoryEvidenceKind,
    RepositoryIdentityEvidence,
    ResolveCodeRepositoryCommand,
    ResolveCodeRepositoryHandler,
)
from sqlalchemy import select

NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_postgres_repository_binding_uses_hashes_and_resolves_worktrees(
    tmp_path: Path,
) -> None:
    remote = _evidence(RepositoryEvidenceKind.NORMALIZED_REMOTE, "github.com/org/repo")
    common_dir = _evidence(RepositoryEvidenceKind.GIT_COMMON_DIR, "opaque-common-dir")

    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'code-identity.db'}")
        try:
            await create_schema(engine)
            session_factory = build_session_factory(engine)
            async with session_factory() as session:
                session.add(
                    MemorySpaceRow(
                        id="space-1",
                        slug="space-1",
                        name="Space 1",
                        status="active",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await session.commit()

            async with session_factory() as session:
                created = await ResolveCodeRepositoryHandler(
                    repositories=PostgresCodeRepository(session),
                    clock=FakeClock(),
                    ids=FakeIds(),
                ).execute(
                    ResolveCodeRepositoryCommand(
                        space_id="space-1",
                        evidence=(remote, common_dir),
                        provider=CodeRepositoryProvider.GITHUB,
                        allow_create=True,
                        safe_label="org/repo",
                    )
                )
                await session.commit()
            assert created.method is CodeRepositoryResolutionMethod.CREATED

            async with session_factory() as session:
                resolved = await ResolveCodeRepositoryHandler(
                    repositories=PostgresCodeRepository(session),
                    clock=FakeClock(),
                    ids=FakeIds(),
                ).execute(
                    ResolveCodeRepositoryCommand(
                        space_id="space-1",
                        evidence=(common_dir,),
                        provider=CodeRepositoryProvider.LOCAL,
                    )
                )
                rows = tuple((await session.execute(select(CodeRepositoryRow))).scalars())
                aliases = tuple((await session.execute(select(CodeRepositoryAliasRow))).scalars())

            assert resolved.repository.repository_id == "repo-1"
            assert len(rows) == 1
            assert rows[0].remote_url_hash == remote.digest
            assert {alias.evidence_digest for alias in aliases} == {
                remote.digest,
                common_dir.digest,
            }
            persisted = repr((rows[0].__dict__, *(alias.__dict__ for alias in aliases)))
            assert "github.com" not in persisted
            assert "opaque-common-dir" not in persisted
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def _evidence(
    kind: RepositoryEvidenceKind,
    value: str,
) -> RepositoryIdentityEvidence:
    return RepositoryIdentityEvidence(
        kind=kind,
        digest=sha256(value.encode()).hexdigest(),
    )


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeIds:
    def new_repository_id(self) -> str:
        return "repo-1"
