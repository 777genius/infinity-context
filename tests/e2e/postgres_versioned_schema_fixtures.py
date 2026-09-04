"""Historical versioned-schema installers for PostgreSQL E2E tests."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from infinity_context_adapters.postgres import build_async_engine
from infinity_context_adapters.postgres.staged_locator_migrations import (
    STAGED_MIGRATION_IDS,
    apply_staged_locator_migration,
)
from postgres_test_database import PostgresTestDatabase

_MIGRATIONS = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations"
)


async def install_versioned_schema_through(
    database: PostgresTestDatabase,
    migration_prefix: str,
) -> None:
    """Install the exact packaged schema, including historical staged phases."""

    paths = tuple(
        path for path in sorted(_MIGRATIONS.glob("*.sql")) if path.name[:5] <= migration_prefix
    )
    engine = build_async_engine(database.app_url)
    try:
        for path in paths:
            if path.stem in STAGED_MIGRATION_IDS:
                async with engine.connect() as connection:
                    await apply_staged_locator_migration(
                        connection,
                        migration_id=path.stem,
                    )
            raw = await database.connect()
            try:
                for statement in _raw_migration_statements(path):
                    await raw.execute(statement)
            finally:
                await raw.close()
    finally:
        await engine.dispose()

    raw = await database.connect()
    try:
        await raw.execute(
            """
            CREATE TABLE infinity_context_schema_migrations (
              migration_id VARCHAR(160) PRIMARY KEY,
              checksum VARCHAR(64) NOT NULL,
              execution_kind VARCHAR(32) NOT NULL,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT ck_infinity_context_schema_migration_kind
                CHECK (execution_kind IN ('applied', 'legacy_baseline'))
            )
            """
        )
        await raw.executemany(
            """
            INSERT INTO infinity_context_schema_migrations (
              migration_id, checksum, execution_kind
            ) VALUES ($1, $2, 'applied')
            """,
            [(path.stem, sha256(path.read_bytes()).hexdigest()) for path in paths],
        )
    finally:
        await raw.close()


def _raw_migration_statements(path: Path) -> tuple[str, ...]:
    sql = path.read_text(encoding="utf-8")
    marker = "-- infinity-context: no-transaction"
    separator = "-- infinity-context: statement-break"
    if not sql.lstrip().startswith(marker):
        return (sql,)
    statements = tuple(statement.strip() for statement in sql.split(separator) if statement.strip())
    assert len(statements) > 1, f"{path.name} declares no-transaction without separators"
    return statements
