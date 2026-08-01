"""Additive schema upgrade for managed benchmark projection manifests."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from infinity_context_adapters.postgres.models import Base

_TABLE_NAME = "memory_comparison_benchmark_runs"
_PROJECTION_COLUMNS = (
    "projection_manifest_json",
    "projection_manifest_sha256",
    "projection_cleanup_state",
)
_PROJECTION_CONSTRAINTS = (
    "ck_memory_comparison_benchmark_run_manifest_coupling",
    "ck_memory_comparison_benchmark_run_projection_cleanup_state",
    "ck_memory_comparison_benchmark_run_projection_lifecycle",
)


def ensure_benchmark_projection_manifest_schema(connection: Connection) -> None:
    """Upgrade the benchmark registry before its writer fence is installed."""

    inspector = inspect(connection)
    if _TABLE_NAME not in set(inspector.get_table_names()):
        return
    if connection.dialect.name == "postgresql":
        _ensure_postgres_benchmark_projection_manifest_schema(connection, inspector)
    elif connection.dialect.name == "sqlite":
        _ensure_sqlite_benchmark_projection_manifest_schema(connection, inspector)


def _ensure_postgres_benchmark_projection_manifest_schema(
    connection: Connection,
    inspector=None,
) -> None:
    if inspector is not None and _has_current_projection_schema(inspector):
        return
    existing_columns = _column_names(connection)
    additive_columns = (
        ("projection_manifest_json", "JSONB"),
        ("projection_manifest_sha256", "VARCHAR(64)"),
        ("projection_cleanup_state", "VARCHAR(40)"),
    )
    for column_name, ddl in additive_columns:
        if column_name not in existing_columns:
            connection.execute(text(f"ALTER TABLE {_TABLE_NAME} ADD COLUMN {column_name} {ddl}"))

    connection.execute(
        text(
            """
            UPDATE memory_comparison_benchmark_runs
            SET projection_cleanup_state = CASE
                WHEN state = 'active' THEN 'unsealed'
                WHEN state = 'cleanup_pending' THEN 'blocked'
            END
            WHERE projection_cleanup_state IS NULL
            """
        )
    )
    connection.execute(
        text(
            """
            ALTER TABLE memory_comparison_benchmark_runs
            ALTER COLUMN projection_cleanup_state SET DEFAULT 'unsealed',
            ALTER COLUMN projection_cleanup_state SET NOT NULL
            """
        )
    )
    for constraint_name in _PROJECTION_CONSTRAINTS:
        connection.execute(
            text(
                "ALTER TABLE memory_comparison_benchmark_runs "
                f"DROP CONSTRAINT IF EXISTS {constraint_name}"
            )
        )
    constraint_definitions = {
        "ck_memory_comparison_benchmark_run_manifest_coupling": (
            "(projection_manifest_json IS NULL AND projection_manifest_sha256 IS NULL) OR "
            "(projection_manifest_json IS NOT NULL AND projection_manifest_sha256 IS NOT NULL)"
        ),
        "ck_memory_comparison_benchmark_run_projection_cleanup_state": (
            "projection_cleanup_state IN ('unsealed', 'sealed', 'pending', 'blocked')"
        ),
        "ck_memory_comparison_benchmark_run_projection_lifecycle": (
            "(state = 'active' AND projection_cleanup_state = 'unsealed' "
            "AND projection_manifest_json IS NULL) OR "
            "(state = 'active' AND projection_cleanup_state = 'sealed' "
            "AND projection_manifest_json IS NOT NULL) OR "
            "(state = 'cleanup_pending' AND projection_cleanup_state = 'blocked' "
            "AND projection_manifest_json IS NULL) OR "
            "(state = 'cleanup_pending' AND projection_cleanup_state = 'pending' "
            "AND projection_manifest_json IS NOT NULL)"
        ),
    }
    for constraint_name, definition in constraint_definitions.items():
        connection.execute(
            text(
                "ALTER TABLE memory_comparison_benchmark_runs "
                f"ADD CONSTRAINT {constraint_name} CHECK ({definition}) NOT VALID"
            )
        )
    for constraint_name in _PROJECTION_CONSTRAINTS:
        connection.execute(
            text(
                "ALTER TABLE memory_comparison_benchmark_runs "
                f"VALIDATE CONSTRAINT {constraint_name}"
            )
        )


def _ensure_sqlite_benchmark_projection_manifest_schema(
    connection: Connection,
    inspector,
) -> None:
    if _has_current_projection_schema(inspector):
        return
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE_NAME)}

    old_table_name = "_memory_comparison_benchmark_runs_projection_upgrade"
    connection.execute(text(f"DROP TABLE IF EXISTS {old_table_name}"))
    connection.execute(text(f"ALTER TABLE {_TABLE_NAME} RENAME TO {old_table_name}"))
    benchmark_table = Base.metadata.tables[_TABLE_NAME]
    benchmark_table.create(connection)

    target_columns = [column.name for column in benchmark_table.columns]
    select_expressions: list[str] = []
    for column_name in target_columns:
        if column_name == "projection_cleanup_state":
            existing_value = "projection_cleanup_state" if column_name in columns else "NULL"
            select_expressions.append(
                "CASE "
                f"WHEN {existing_value} IS NOT NULL THEN {existing_value} "
                "WHEN state = 'active' THEN 'unsealed' "
                "WHEN state = 'cleanup_pending' THEN 'blocked' END"
            )
        elif column_name in columns:
            select_expressions.append(column_name)
        else:
            select_expressions.append("NULL")
    connection.execute(
        text(
            f"INSERT INTO {_TABLE_NAME} ({', '.join(target_columns)}) "
            f"SELECT {', '.join(select_expressions)} FROM {old_table_name}"
        )
    )
    connection.execute(text(f"DROP TABLE {old_table_name}"))


def _column_names(connection: Connection) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(_TABLE_NAME)}


def _has_current_projection_schema(inspector) -> bool:
    columns = {column["name"]: column for column in inspector.get_columns(_TABLE_NAME)}
    constraint_names = {
        constraint.get("name") for constraint in inspector.get_check_constraints(_TABLE_NAME)
    }
    cleanup_column = columns.get("projection_cleanup_state")
    return (
        set(_PROJECTION_COLUMNS).issubset(columns)
        and cleanup_column is not None
        and cleanup_column.get("nullable") is False
        and _is_unsealed_server_default(cleanup_column.get("default"))
        and set(_PROJECTION_CONSTRAINTS).issubset(constraint_names)
    )


def _is_unsealed_server_default(default: object) -> bool:
    if default is None:
        return False
    normalized = str(default).strip().strip("()").strip().split("::", 1)[0].strip()
    return normalized.strip("'\"") == "unsealed"
