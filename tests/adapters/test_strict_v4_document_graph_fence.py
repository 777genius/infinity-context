from __future__ import annotations

import re
from pathlib import Path

from infinity_context_adapters.postgres.strict_v4_document_graph_fence import (
    STRICT_V4_DOCUMENT_CHILD_TABLES,
    STRICT_V4_DOCUMENT_GRAPH_FENCE_STATEMENTS,
)

_MIGRATION = (
    Path(__file__).parents[2]
    / "packages/infinity_context_adapters/infinity_context_adapters/postgres/"
    "migrations/0038_strict_v4_document_writer.sql"
)


def _normalize(value: str) -> str:
    return re.sub(r"[;\s]+", " ", value).strip().lower()


def test_document_graph_runtime_sql_is_pinned_in_migration() -> None:
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    assert STRICT_V4_DOCUMENT_CHILD_TABLES == ("memory_chunks", "memory_outbox")
    for statement in STRICT_V4_DOCUMENT_GRAPH_FENCE_STATEMENTS:
        assert _normalize(statement) in migration


def test_document_and_fact_outbox_triggers_are_exactly_lane_scoped() -> None:
    migration = _normalize(_MIGRATION.read_text(encoding="utf-8"))

    assert "when (new.aggregate_type = 'fact')" in migration
    assert "when (old.aggregate_type = 'fact')" in migration
    assert "when (new.aggregate_type = 'chunk')" in migration
    assert "when (old.aggregate_type = 'chunk')" in migration
    assert "deferrable initially deferred" in migration
    assert "managed-benchmark-document-v4-%" in migration
    assert "memory_comparison_is_strict_v4_document_writer" in migration


def test_document_writer_migration_stays_reviewable() -> None:
    assert len(_MIGRATION.read_text(encoding="utf-8").splitlines()) < 1_000
