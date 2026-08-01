import asyncio
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import (
    benchmark_projection_schema,
    build_async_engine,
    create_schema,
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def test_postgres_projection_upgrade_orders_backfill_before_constraints(monkeypatch) -> None:
    connection = _RecordingConnection()
    monkeypatch.setattr(benchmark_projection_schema, "_column_names", lambda *_args: set())

    benchmark_projection_schema._ensure_postgres_benchmark_projection_manifest_schema(connection)

    statements = connection.statements
    assert len(statements) == 14
    assert all("ADD COLUMN" in statement for statement in statements[:3])
    assert "projection_manifest_json JSONB" in statements[0]
    assert "UPDATE memory_comparison_benchmark_runs" in statements[3]
    assert "WHEN state = 'cleanup_pending' THEN 'blocked'" in statements[3]
    assert "SET DEFAULT 'unsealed'" in statements[4]
    assert "SET NOT NULL" in statements[4]
    assert all("DROP CONSTRAINT IF EXISTS" in statement for statement in statements[5:8])
    assert all("ADD CONSTRAINT" in statement for statement in statements[8:11])
    assert all("NOT VALID" in statement for statement in statements[8:11])
    assert all("VALIDATE CONSTRAINT" in statement for statement in statements[11:])


def test_create_schema_upgrades_pre_projection_manifest_benchmark_rows(tmp_path: Path) -> None:
    async def run() -> tuple[
        dict[str, dict[str, object]],
        set[str],
        list[tuple[object, ...]],
    ]:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'benchmark-upgrade.db'}")
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("CREATE TABLE memory_spaces (id VARCHAR(80) PRIMARY KEY)")
                )
                await connection.execute(
                    text(
                        """
                        CREATE TABLE memory_comparison_benchmark_runs (
                            run_id_sha256 VARCHAR(64) PRIMARY KEY,
                            binding_commitment_sha256 VARCHAR(64) NOT NULL,
                            infinity_target_identity_sha256 VARCHAR(64) NOT NULL,
                            space_id VARCHAR(80) NOT NULL REFERENCES memory_spaces(id),
                            space_slug VARCHAR(160) NOT NULL,
                            idempotency_key_sha256 VARCHAR(64) NOT NULL,
                            registration_fingerprint_sha256 VARCHAR(64) NOT NULL,
                            state VARCHAR(40) NOT NULL,
                            cleanup_fingerprint_sha256 VARCHAR(64),
                            cleanup_receipt_json JSON,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            CONSTRAINT ck_memory_comparison_benchmark_run_state
                                CHECK (state IN ('active', 'cleanup_pending')),
                            CONSTRAINT ck_memory_comparison_benchmark_run_cleanup_state CHECK (
                                (state = 'active' AND cleanup_fingerprint_sha256 IS NULL
                                    AND cleanup_receipt_json IS NULL)
                                OR
                                (state = 'cleanup_pending'
                                    AND cleanup_fingerprint_sha256 IS NOT NULL
                                    AND cleanup_receipt_json IS NOT NULL)
                            ),
                            UNIQUE (space_id),
                            UNIQUE (space_slug),
                            UNIQUE (idempotency_key_sha256)
                        )
                        """
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO memory_spaces (id) VALUES ('space-active'), ('space-cleanup')"
                    )
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO memory_comparison_benchmark_runs (
                            run_id_sha256,
                            binding_commitment_sha256,
                            infinity_target_identity_sha256,
                            space_id,
                            space_slug,
                            idempotency_key_sha256,
                            registration_fingerprint_sha256,
                            state,
                            cleanup_fingerprint_sha256,
                            cleanup_receipt_json,
                            created_at,
                            updated_at
                        ) VALUES
                            ('run-active', 'binding-active', 'target-active',
                             'space-active', 'slug-active', 'key-active', 'fingerprint-active',
                             'active', NULL, NULL, '2026-01-01', '2026-01-01'),
                            ('run-cleanup', 'binding-cleanup', 'target-cleanup',
                             'space-cleanup', 'slug-cleanup', 'key-cleanup',
                             'fingerprint-cleanup', 'cleanup_pending', 'cleanup-fingerprint',
                             '{}', '2026-01-01', '2026-01-01')
                        """
                    )
                )

            await create_schema(engine)
            await create_schema(engine)

            def inspect_upgrade(connection):
                inspector = inspect(connection)
                columns = {
                    column["name"]: column
                    for column in inspector.get_columns("memory_comparison_benchmark_runs")
                }
                constraints = {
                    constraint["name"]
                    for constraint in inspector.get_check_constraints(
                        "memory_comparison_benchmark_runs"
                    )
                }
                rows = connection.execute(
                    text(
                        """
                        SELECT run_id_sha256, projection_manifest_json,
                               projection_manifest_sha256, projection_cleanup_state
                        FROM memory_comparison_benchmark_runs
                        ORDER BY run_id_sha256
                        """
                    )
                ).all()
                return columns, constraints, rows

            async with engine.connect() as connection:
                result = await connection.run_sync(inspect_upgrade)

            with pytest.raises(IntegrityError):
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            """
                            UPDATE memory_comparison_benchmark_runs
                            SET projection_cleanup_state = 'pending'
                            WHERE run_id_sha256 = 'run-active'
                            """
                        )
                    )
            return result
        finally:
            await engine.dispose()

    columns, constraints, rows = asyncio.run(run())

    assert columns["projection_cleanup_state"]["nullable"] is False
    assert "unsealed" in str(columns["projection_cleanup_state"]["default"])
    assert {
        "ck_memory_comparison_benchmark_run_manifest_coupling",
        "ck_memory_comparison_benchmark_run_projection_cleanup_state",
        "ck_memory_comparison_benchmark_run_projection_lifecycle",
    }.issubset(constraints)
    assert rows == [
        ("run-active", None, None, "unsealed"),
        ("run-cleanup", None, None, "blocked"),
    ]


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement) -> None:
        self.statements.append(" ".join(str(statement).split()))


def test_postgres_projection_upgrade_skips_current_schema() -> None:
    connection = _RecordingConnection()

    benchmark_projection_schema._ensure_postgres_benchmark_projection_manifest_schema(
        connection, _CurrentProjectionSchemaInspector()
    )

    assert connection.statements == []


class _CurrentProjectionSchemaInspector:
    def get_columns(self, _table_name: str) -> list[dict[str, object]]:
        return [
            {"name": "projection_manifest_json"},
            {"name": "projection_manifest_sha256"},
            {
                "name": "projection_cleanup_state",
                "nullable": False,
                "default": "('unsealed'::character varying)",
            },
        ]

    def get_check_constraints(self, _table_name: str) -> list[dict[str, object]]:
        return [
            {"name": "ck_memory_comparison_benchmark_run_manifest_coupling"},
            {"name": "ck_memory_comparison_benchmark_run_projection_cleanup_state"},
            {"name": "ck_memory_comparison_benchmark_run_projection_lifecycle"},
        ]
