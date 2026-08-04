from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

import pytest

from mem0_oss_adapter.residue import (
    ResidueCleanupError,
    prepare_scope_ledger,
    purge_scope_residue,
    record_scope_memory_ids,
    snapshot_scope_memory_ids,
)


@dataclass
class _Row:
    id: str


class _Store:
    def __init__(self, rows: list[_Row], *, continuation: object | None = None) -> None:
        self.rows = rows
        self.continuation = continuation
        self.deleted: list[str] = []

    def list(self, *, filters: dict[str, str], top_k: int) -> tuple[list[_Row], object | None]:
        assert filters == {"user_id": "user-1", "run_id": "run-1"}
        assert top_k == 10_000
        return list(self.rows), self.continuation

    def delete(self, *, vector_id: str) -> None:
        self.deleted.append(vector_id)
        self.rows = [row for row in self.rows if row.id != vector_id]


class _Db:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self._lock = threading.Lock()
        self.connection.executescript(
            """
            CREATE TABLE history (
                id TEXT PRIMARY KEY,
                memory_id TEXT,
                old_memory TEXT,
                new_memory TEXT,
                event TEXT,
                created_at DATETIME,
                updated_at DATETIME,
                is_deleted INTEGER,
                actor_id TEXT,
                role TEXT
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                session_scope TEXT,
                role TEXT,
                content TEXT,
                name TEXT,
                created_at DATETIME
            );
            """
        )


class _Memory:
    def __init__(self, *, vector_rows: list[_Row], entity_rows: list[_Row]) -> None:
        self.vector_store = _Store(vector_rows)
        self.entity_store = _Store(entity_rows)
        self.db = _Db()


def test_exact_scope_purge_removes_history_messages_and_entities_only_for_the_scope() -> None:
    memory = _Memory(
        vector_rows=[_Row("memory-1")],
        entity_rows=[_Row("entity-1"), _Row("entity-2")],
    )
    prepare_scope_ledger(memory.db)
    record_scope_memory_ids(
        memory.db,
        memory_ids=("memory-1",),
        user_id="user-1",
        run_id="run-1",
        source_id="source-1",
        source_sha256="a" * 64,
    )
    record_scope_memory_ids(
        memory.db,
        memory_ids=("other-memory",),
        user_id="user-2",
        run_id="run-2",
        source_id="other-source",
        source_sha256="b" * 64,
    )
    memory.db.connection.executemany(
        "INSERT INTO history (id, memory_id, old_memory, new_memory) VALUES (?, ?, ?, ?)",
        [
            ("history-1", "memory-1", "private old text", None),
            ("history-2", "memory-1", "private old text", None),
            ("history-3", "other-memory", "keep", None),
        ],
    )
    memory.db.connection.executemany(
        "INSERT INTO messages (id, session_scope, content) VALUES (?, ?, ?)",
        [
            ("message-1", "run_id=run-1&user_id=user-1", "private message"),
            ("message-2", "run_id=run-2&user_id=user-1", "keep"),
            ("message-3", "run_id=run-1&user_id=user-2", "keep"),
            ("message-4", "run_id=run-1&user_id=user-11", "keep"),
            ("message-5", "run_id=run-10&user_id=user-1", "keep"),
        ],
    )
    memory.db.connection.commit()

    ids = snapshot_scope_memory_ids(memory, user_id="user-1", run_id="run-1")
    proof = purge_scope_residue(
        memory,
        memory_ids=ids,
        user_id="user-1",
        run_id="run-1",
    )

    assert proof.memory_ids == ("memory-1",)
    assert proof.history_rows_deleted == 2
    assert proof.message_rows_deleted == 1
    assert proof.entity_rows_deleted == 2
    assert proof.ledger_rows_deleted == 1
    assert memory.entity_store.deleted == ["entity-1", "entity-2"]
    assert memory.db.connection.execute("SELECT memory_id FROM history").fetchall() == [
        ("other-memory",)
    ]
    assert memory.db.connection.execute("SELECT session_scope FROM messages").fetchall() == [
        ("run_id=run-2&user_id=user-1",),
        ("run_id=run-1&user_id=user-2",),
        ("run_id=run-1&user_id=user-11",),
        ("run_id=run-10&user_id=user-1",),
    ]


def test_scope_snapshot_fails_closed_when_qdrant_has_more_than_the_verified_bound() -> None:
    memory = _Memory(vector_rows=[], entity_rows=[])
    memory.vector_store.continuation = "next-page"

    with pytest.raises(ResidueCleanupError, match="verified cleanup bound"):
        snapshot_scope_memory_ids(memory, user_id="user-1", run_id="run-1")


def test_purge_fails_closed_when_the_pinned_mem0_sqlite_schema_drifts() -> None:
    memory = _Memory(vector_rows=[], entity_rows=[])
    memory.db.connection.execute("ALTER TABLE messages ADD COLUMN unexpected TEXT")

    with pytest.raises(ResidueCleanupError, match="schema differs"):
        purge_scope_residue(
            memory,
            memory_ids=(),
            user_id="user-1",
            run_id="run-1",
        )


def test_scope_ledger_refuses_to_adopt_non_fresh_history() -> None:
    memory = _Memory(vector_rows=[], entity_rows=[])
    memory.db.connection.execute(
        "INSERT INTO history (id, memory_id, old_memory) VALUES (?, ?, ?)",
        ("legacy-history", "legacy-memory", "private legacy text"),
    )
    memory.db.connection.commit()

    with pytest.raises(ResidueCleanupError, match="non-fresh"):
        prepare_scope_ledger(memory.db)


def test_scope_ledger_schema_drift_fails_closed() -> None:
    memory = _Memory(vector_rows=[], entity_rows=[])
    prepare_scope_ledger(memory.db)
    memory.db.connection.execute(
        "ALTER TABLE infinity_context_scope_ledger ADD COLUMN unexpected TEXT"
    )

    with pytest.raises(ResidueCleanupError, match="ledger schema differs"):
        prepare_scope_ledger(memory.db)
