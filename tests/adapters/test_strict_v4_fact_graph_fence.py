from __future__ import annotations

import re
from pathlib import Path

from infinity_context_adapters.postgres.strict_v4_fact_graph_fence import (
    STRICT_V4_FACT_CHILD_TABLES,
    STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS,
)

_MIGRATION = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
    "migrations/0037_strict_v4_fact_writer.sql"
)


def _normalize(value: str) -> str:
    return re.sub(r"[;\s]+", " ", value).strip().lower()


def test_fact_graph_runtime_sql_is_pinned_in_migration() -> None:
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    assert STRICT_V4_FACT_CHILD_TABLES == (
        "memory_fact_versions",
        "memory_source_refs",
        "memory_outbox",
    )
    for statement in STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS:
        assert _normalize(statement) in migration


def test_fact_graph_runtime_uses_only_canonical_writer_authority() -> None:
    runtime_sql = _normalize(" ".join(STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS))
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    assert "memory_comparison_is_strict_v4_canonical_writer" in runtime_sql
    assert "infinity_context_strict_v4_fact_writer" not in runtime_sql
    assert "infinity_context_strict_v4_fact_writer" not in migration
    assert "memory_comparison_is_strict_v4_fact_writer" not in runtime_sql
    assert "memory_comparison_is_strict_v4_fact_writer" not in migration


def test_fact_graph_receipt_and_child_fences_remain_installed() -> None:
    runtime_sql = _normalize(" ".join(STRICT_V4_FACT_GRAPH_FENCE_STATEMENTS))

    for function_name in (
        "memory_comparison_lock_benchmark_fact_child_target",
        "memory_comparison_enforce_benchmark_fact_child_fence",
        "memory_comparison_enforce_benchmark_fact_receipt",
        "memory_comparison_verify_benchmark_fact_outbox_receipt",
    ):
        assert function_name in runtime_sql
    assert "deferrable initially deferred" in runtime_sql
    assert "managed-benchmark-fact-v4-%" in runtime_sql
