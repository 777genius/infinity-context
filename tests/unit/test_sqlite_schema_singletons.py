import asyncio
from pathlib import Path

from infinity_context_adapters.postgres import build_async_engine, create_schema
from infinity_context_adapters.postgres.locator_profile_reconciliation import (
    _profile_evidence_lock_sql,
)
from sqlalchemy import text


def test_create_schema_seeds_retrieval_v2_singletons_idempotently(tmp_path: Path) -> None:
    async def run() -> tuple[tuple[object, ...], tuple[object, ...]]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'singletons.db'}")
        try:
            await create_schema(engine)
            async with engine.connect() as connection:
                initial = (
                    await connection.execute(
                        text(
                            """
                            SELECT aggregate_version, changed_at
                            FROM memory_locator_profile_evidence_versions
                            WHERE singleton = TRUE
                            """
                        )
                    )
                ).one()
                fence = (
                    await connection.execute(
                        text(
                            """
                            SELECT fence_generation, active, reason, changed_at
                            FROM memory_locator_profile_maintenance_fence
                            WHERE singleton = TRUE
                            """
                        )
                    )
                ).one()

            await create_schema(engine)
            async with engine.connect() as connection:
                counts = (
                    await connection.execute(
                        text(
                            """
                            SELECT
                                (SELECT COUNT(*) FROM memory_locator_profile_evidence_versions),
                                (SELECT COUNT(*) FROM memory_locator_profile_maintenance_fence)
                            """
                        )
                    )
                ).one()
            return tuple(initial) + tuple(fence), tuple(counts)
        finally:
            await engine.dispose()

    values, counts = asyncio.run(run())

    assert values[0] == 1
    assert values[1] is not None
    assert values[2:5] == (0, 0, None)
    assert values[5] is not None
    assert counts == (1, 1)


def test_create_schema_preserves_existing_retrieval_v2_singletons(tmp_path: Path) -> None:
    async def run() -> tuple[tuple[object, ...], tuple[object, ...]]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'existing.db'}")
        try:
            await create_schema(engine)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        UPDATE memory_locator_profile_evidence_versions
                        SET aggregate_version = 41, changed_at = '2026-08-25 10:00:00'
                        WHERE singleton = TRUE
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        UPDATE memory_locator_profile_maintenance_fence
                        SET fence_generation = 7,
                            active = TRUE,
                            reason = 'operator-hold',
                            changed_at = '2026-08-25 11:00:00'
                        WHERE singleton = TRUE
                        """
                    )
                )

            await create_schema(engine)
            async with engine.connect() as connection:
                evidence = (
                    await connection.execute(
                        text(
                            """
                            SELECT aggregate_version, changed_at
                            FROM memory_locator_profile_evidence_versions
                            WHERE singleton = TRUE
                            """
                        )
                    )
                ).one()
                fence = (
                    await connection.execute(
                        text(
                            """
                            SELECT fence_generation, active, reason, changed_at
                            FROM memory_locator_profile_maintenance_fence
                            WHERE singleton = TRUE
                            """
                        )
                    )
                ).one()
            return tuple(evidence), tuple(fence)
        finally:
            await engine.dispose()

    evidence, fence = asyncio.run(run())

    assert evidence == (41, "2026-08-25 10:00:00")
    assert fence == (7, 1, "operator-hold", "2026-08-25 11:00:00")


def test_profile_evidence_lock_sql_is_dialect_safe() -> None:
    sqlite_statement = _profile_evidence_lock_sql("sqlite")
    postgres_statement = _profile_evidence_lock_sql("postgresql")

    assert "FOR UPDATE" not in sqlite_statement
    assert postgres_statement == f"{sqlite_statement} FOR UPDATE"
