"""Verified cleanup and adapter-owned scope identity for the pinned Mem0 runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

_MAX_SCOPE_RECORDS = 10_000
_SQLITE_PARAMETER_BATCH = 500
_LEDGER_TABLE = "infinity_context_scope_ledger"
_LEDGER_COLUMNS = frozenset({"memory_id", "user_id", "run_id", "source_id", "source_sha256"})
_HISTORY_COLUMNS = frozenset(
    {
        "id",
        "memory_id",
        "old_memory",
        "new_memory",
        "event",
        "created_at",
        "updated_at",
        "is_deleted",
        "actor_id",
        "role",
    }
)
_MESSAGES_COLUMNS = frozenset({"id", "session_scope", "role", "content", "name", "created_at"})


class ResidueCleanupError(RuntimeError):
    """The adapter cannot prove that all logical state for a scope was removed."""


@dataclass(frozen=True, slots=True)
class ScopedResidueProof:
    entity_rows_deleted: int
    history_rows_deleted: int
    ledger_rows_deleted: int
    memory_ids: tuple[str, ...]
    message_rows_deleted: int


@dataclass(frozen=True, slots=True)
class SourceResidueProof:
    history_rows_deleted: int
    ledger_rows_deleted: int
    memory_ids: tuple[str, ...]


def prepare_scope_ledger(db: Any) -> None:
    """Create the ledger only for fresh state and prove every history id is mapped."""

    _ensure_scope_ledger(db)
    connection, lock = _database_handles(db)
    with lock:
        _require_pinned_sqlite_schema(connection)
        _require_scope_ledger_schema(connection)
        _verify_history_is_ledgered(connection)


def record_scope_memory_ids(
    db: Any,
    *,
    memory_ids: Sequence[str],
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> None:
    """Persist the canonical adapter mapping for every provider-created id."""

    ids = _validated_memory_ids(memory_ids, allow_empty=False)
    _ensure_scope_ledger(db)
    connection, lock = _database_handles(db)
    with lock:
        try:
            _require_pinned_sqlite_schema(connection)
            _require_scope_ledger_schema(connection)
            connection.execute("BEGIN")
            connection.executemany(
                f"""
                INSERT OR IGNORE INTO {_LEDGER_TABLE} (
                    memory_id, user_id, run_id, source_id, source_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [(memory_id, user_id, run_id, source_id, source_sha256) for memory_id in ids],
            )
            for memory_id in ids:
                row = connection.execute(
                    f"""
                    SELECT user_id, run_id, source_id, source_sha256
                    FROM {_LEDGER_TABLE}
                    WHERE memory_id = ?
                    """,
                    (memory_id,),
                ).fetchone()
                if row != (user_id, run_id, source_id, source_sha256):
                    raise ResidueCleanupError("scope ledger memory identity conflicts")
            _verify_history_is_ledgered(connection)
            connection.execute("COMMIT")
        except ResidueCleanupError:
            _rollback(connection)
            raise
        except Exception as exc:
            _rollback(connection)
            raise ResidueCleanupError("scope ledger write failed") from exc


def scope_ledger_memory_ids(db: Any, *, user_id: str, run_id: str) -> tuple[str, ...]:
    prepare_scope_ledger(db)
    return _ledger_memory_ids(db, user_id=user_id, run_id=run_id)


def source_ledger_memory_ids(
    db: Any,
    *,
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> tuple[str, ...]:
    prepare_scope_ledger(db)
    return _ledger_memory_ids(
        db,
        user_id=user_id,
        run_id=run_id,
        source_id=source_id,
        source_sha256=source_sha256,
    )


def require_isolated_subscription_scope(memory: Any, *, user_id: str, run_id: str) -> None:
    """Permit subscription extraction only on one fresh, empty user/run scope."""

    prepare_scope_ledger(memory.db)
    occupied = bool(
        scope_ledger_memory_ids(memory.db, user_id=user_id, run_id=run_id)
        or snapshot_scope_memory_ids(memory, user_id=user_id, run_id=run_id)
        or _scope_message_count(memory.db, user_id=user_id, run_id=run_id)
        or _list_rows(memory.entity_store, filters={"user_id": user_id, "run_id": run_id})
    )
    if occupied:
        raise ResidueCleanupError("subscription extraction requires a fresh isolated scope")


def snapshot_scope_memory_ids(memory: Any, *, user_id: str, run_id: str) -> tuple[str, ...]:
    return _snapshot_memory_ids(
        memory.vector_store,
        filters={"user_id": user_id, "run_id": run_id},
    )


def snapshot_history_memory_ids(db: Any) -> tuple[str, ...]:
    """Snapshot distinct history ids without requiring new rows to be ledgered yet."""

    connection, lock = _database_handles(db)
    with lock:
        _require_pinned_sqlite_schema(connection)
        _require_scope_ledger_schema(connection)
        rows = connection.execute(
            f"""
            SELECT DISTINCT memory_id
            FROM history
            ORDER BY memory_id
            LIMIT {_MAX_SCOPE_RECORDS + 1}
            """
        ).fetchall()
    if len(rows) > _MAX_SCOPE_RECORDS:
        raise ResidueCleanupError("Mem0 history exceeds the verified cleanup bound")
    if any(not isinstance(row, tuple) or len(row) != 1 for row in rows):
        raise ResidueCleanupError("Mem0 history snapshot was invalid")
    return _validated_memory_ids(tuple(row[0] for row in rows), allow_empty=True)


def snapshot_source_memory_ids(
    memory: Any,
    *,
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> tuple[str, ...]:
    return _snapshot_memory_ids(
        memory.vector_store,
        filters={
            "user_id": user_id,
            "run_id": run_id,
            "source_id": source_id,
            "source_sha256": source_sha256,
        },
    )


def purge_scope_residue(
    memory: Any,
    *,
    memory_ids: Sequence[str],
    user_id: str,
    run_id: str,
) -> ScopedResidueProof:
    """Delete and verify every logical store owned by one exact user/run scope."""

    ids = _validated_memory_ids(memory_ids, allow_empty=True)
    entities = _list_rows(
        memory.entity_store,
        filters={"user_id": user_id, "run_id": run_id},
    )
    for entity in entities:
        memory.entity_store.delete(vector_id=_record_id(entity))
    if _list_rows(memory.entity_store, filters={"user_id": user_id, "run_id": run_id}):
        raise ResidueCleanupError("entity residue remains after exact-scope purge")

    history_deleted, messages_deleted, ledger_deleted = _purge_scope_sqlite(
        memory.db,
        memory_ids=ids,
        user_id=user_id,
        run_id=run_id,
    )
    return ScopedResidueProof(
        entity_rows_deleted=len(entities),
        history_rows_deleted=history_deleted,
        ledger_rows_deleted=ledger_deleted,
        memory_ids=ids,
        message_rows_deleted=messages_deleted,
    )


def purge_source_residue(
    memory: Any,
    *,
    memory_ids: Sequence[str],
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> SourceResidueProof:
    """Remove only one failed source while preserving other sources in the run."""

    ids = _validated_memory_ids(memory_ids, allow_empty=True)
    _remove_and_verify_source_entity_links(
        memory,
        memory_ids=ids,
        user_id=user_id,
        run_id=run_id,
    )
    history_deleted, ledger_deleted = _purge_source_sqlite(
        memory.db,
        memory_ids=ids,
        user_id=user_id,
        run_id=run_id,
        source_id=source_id,
        source_sha256=source_sha256,
    )
    return SourceResidueProof(
        history_rows_deleted=history_deleted,
        ledger_rows_deleted=ledger_deleted,
        memory_ids=ids,
    )


def _ensure_scope_ledger(db: Any) -> None:
    connection, lock = _database_handles(db)
    with lock:
        try:
            _require_pinned_sqlite_schema(connection)
            existing = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (_LEDGER_TABLE,),
            ).fetchone()
            if existing is None:
                history_count = _scalar_count(connection, "SELECT COUNT(*) FROM history")
                message_count = _scalar_count(connection, "SELECT COUNT(*) FROM messages")
                if history_count or message_count:
                    raise ResidueCleanupError("scope ledger cannot adopt non-fresh Mem0 state")
                connection.execute("BEGIN")
                connection.execute(
                    f"""
                    CREATE TABLE {_LEDGER_TABLE} (
                        memory_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        source_sha256 TEXT NOT NULL
                    )
                    """
                )
                connection.execute("COMMIT")
            _require_scope_ledger_schema(connection)
        except ResidueCleanupError:
            _rollback(connection)
            raise
        except Exception as exc:
            _rollback(connection)
            raise ResidueCleanupError("scope ledger initialization failed") from exc


def _ledger_memory_ids(
    db: Any,
    *,
    user_id: str,
    run_id: str,
    source_id: str | None = None,
    source_sha256: str | None = None,
) -> tuple[str, ...]:
    connection, lock = _database_handles(db)
    where = "user_id = ? AND run_id = ?"
    parameters: tuple[str, ...] = (user_id, run_id)
    if source_id is not None and source_sha256 is not None:
        where += " AND source_id = ? AND source_sha256 = ?"
        parameters += (source_id, source_sha256)
    with lock:
        rows = connection.execute(
            f"""
            SELECT memory_id FROM {_LEDGER_TABLE}
            WHERE {where}
            ORDER BY memory_id
            LIMIT {_MAX_SCOPE_RECORDS + 1}
            """,
            parameters,
        ).fetchall()
    if len(rows) > _MAX_SCOPE_RECORDS:
        raise ResidueCleanupError("scope ledger exceeds the verified cleanup bound")
    if any(not isinstance(row, tuple) or len(row) != 1 for row in rows):
        raise ResidueCleanupError("scope ledger query was invalid")
    return _validated_memory_ids(tuple(row[0] for row in rows), allow_empty=True)


def _snapshot_memory_ids(store: Any, *, filters: Mapping[str, str]) -> tuple[str, ...]:
    rows = _list_rows(store, filters=filters)
    return _validated_memory_ids(tuple(_record_id(row) for row in rows), allow_empty=True)


def _list_rows(store: Any, *, filters: Mapping[str, str]) -> list[Any]:
    listed = store.list(filters=dict(filters), top_k=_MAX_SCOPE_RECORDS)
    if not isinstance(listed, tuple) or len(listed) != 2:
        raise ResidueCleanupError("scope list response was invalid")
    rows, continuation = listed
    if not isinstance(rows, list):
        raise ResidueCleanupError("scope list rows were invalid")
    if continuation is not None:
        raise ResidueCleanupError("scope exceeds the verified cleanup bound")
    return rows


def _record_id(row: object) -> str:
    candidate = row.get("id") if isinstance(row, Mapping) else getattr(row, "id", None)
    if not isinstance(candidate, str) or not candidate:
        raise ResidueCleanupError("scope record did not contain a stable id")
    return candidate


def _remove_and_verify_source_entity_links(
    memory: Any,
    *,
    memory_ids: Sequence[str],
    user_id: str,
    run_id: str,
) -> None:
    if not memory_ids:
        return
    filters = {"user_id": user_id, "run_id": run_id}
    before = _list_rows(memory.entity_store, filters=filters)
    if not any(set(_entity_linked_ids(row)).intersection(memory_ids) for row in before):
        return
    cleanup = getattr(memory, "_remove_memory_from_entity_store", None)
    if not callable(cleanup):
        raise ResidueCleanupError("Mem0 entity cleanup API differs from the pinned runtime")
    for memory_id in memory_ids:
        cleanup(memory_id, filters)
    after = _list_rows(memory.entity_store, filters=filters)
    if any(set(_entity_linked_ids(row)).intersection(memory_ids) for row in after):
        raise ResidueCleanupError("source entity residue remains after cleanup")


def _entity_linked_ids(row: object) -> tuple[str, ...]:
    payload = row.get("payload") if isinstance(row, Mapping) else getattr(row, "payload", None)
    if payload is None:
        return ()
    if not isinstance(payload, Mapping):
        raise ResidueCleanupError("entity payload was invalid")
    linked = payload.get("linked_memory_ids", [])
    if not isinstance(linked, list) or any(
        not isinstance(item, str) or not item for item in linked
    ):
        raise ResidueCleanupError("entity memory links were invalid")
    return tuple(linked)


def _purge_scope_sqlite(
    db: Any,
    *,
    memory_ids: tuple[str, ...],
    user_id: str,
    run_id: str,
) -> tuple[int, int, int]:
    connection, lock = _database_handles(db)
    with lock:
        try:
            _require_pinned_sqlite_schema(connection)
            _require_scope_ledger_schema(connection)
            ledger_ids = _ledger_ids_in_transaction(
                connection,
                user_id=user_id,
                run_id=run_id,
            )
            if set(ledger_ids) != set(memory_ids):
                raise ResidueCleanupError("scope cleanup ids differ from the canonical ledger")
            connection.execute("BEGIN")
            history_deleted = _delete_history_ids(connection, memory_ids)
            message_result = connection.execute(
                """
                DELETE FROM messages
                WHERE instr('&' || session_scope || '&', '&user_id=' || ? || '&') > 0
                  AND instr('&' || session_scope || '&', '&run_id=' || ? || '&') > 0
                """,
                (user_id, run_id),
            )
            ledger_result = connection.execute(
                f"DELETE FROM {_LEDGER_TABLE} WHERE user_id = ? AND run_id = ?",
                (user_id, run_id),
            )
            _verify_history_ids_absent(connection, memory_ids)
            _verify_scope_messages_absent(connection, user_id=user_id, run_id=run_id)
            _verify_scope_ledger_absent(connection, user_id=user_id, run_id=run_id)
            _verify_history_is_ledgered(connection)
            connection.execute("COMMIT")
            connection.execute("VACUUM")
        except ResidueCleanupError:
            _rollback(connection)
            raise
        except Exception as exc:
            _rollback(connection)
            raise ResidueCleanupError("Mem0 scope residue purge failed") from exc
    return history_deleted, message_result.rowcount, ledger_result.rowcount


def _purge_source_sqlite(
    db: Any,
    *,
    memory_ids: tuple[str, ...],
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> tuple[int, int]:
    connection, lock = _database_handles(db)
    with lock:
        try:
            _require_pinned_sqlite_schema(connection)
            _require_scope_ledger_schema(connection)
            ledger_ids = _ledger_ids_in_transaction(
                connection,
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
            if set(ledger_ids) != set(memory_ids):
                raise ResidueCleanupError("source cleanup ids differ from the canonical ledger")
            connection.execute("BEGIN")
            history_deleted = _delete_history_ids(connection, memory_ids)
            ledger_result = connection.execute(
                f"""
                DELETE FROM {_LEDGER_TABLE}
                WHERE user_id = ? AND run_id = ?
                  AND source_id = ? AND source_sha256 = ?
                """,
                (user_id, run_id, source_id, source_sha256),
            )
            _verify_history_ids_absent(connection, memory_ids)
            _verify_source_ledger_absent(
                connection,
                user_id=user_id,
                run_id=run_id,
                source_id=source_id,
                source_sha256=source_sha256,
            )
            _verify_history_is_ledgered(connection)
            connection.execute("COMMIT")
            connection.execute("VACUUM")
        except ResidueCleanupError:
            _rollback(connection)
            raise
        except Exception as exc:
            _rollback(connection)
            raise ResidueCleanupError("Mem0 source residue purge failed") from exc
    return history_deleted, ledger_result.rowcount


def _ledger_ids_in_transaction(
    connection: Any,
    *,
    user_id: str,
    run_id: str,
    source_id: str | None = None,
    source_sha256: str | None = None,
) -> tuple[str, ...]:
    where = "user_id = ? AND run_id = ?"
    parameters: tuple[str, ...] = (user_id, run_id)
    if source_id is not None and source_sha256 is not None:
        where += " AND source_id = ? AND source_sha256 = ?"
        parameters += (source_id, source_sha256)
    rows = connection.execute(
        f"SELECT memory_id FROM {_LEDGER_TABLE} WHERE {where}",
        parameters,
    ).fetchall()
    if len(rows) > _MAX_SCOPE_RECORDS:
        raise ResidueCleanupError("scope ledger exceeds the verified cleanup bound")
    return _validated_memory_ids(tuple(row[0] for row in rows), allow_empty=True)


def _delete_history_ids(connection: Any, memory_ids: Sequence[str]) -> int:
    deleted = 0
    for batch in _batches(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        result = connection.execute(
            f"DELETE FROM history WHERE memory_id IN ({placeholders})",
            batch,
        )
        deleted += result.rowcount
    return deleted


def _verify_history_ids_absent(connection: Any, memory_ids: Sequence[str]) -> None:
    for batch in _batches(memory_ids):
        placeholders = ",".join("?" for _ in batch)
        remaining = _scalar_count(
            connection,
            f"SELECT COUNT(*) FROM history WHERE memory_id IN ({placeholders})",
            batch,
        )
        if remaining:
            raise ResidueCleanupError("SQLite history residue remains")


def _verify_scope_messages_absent(connection: Any, *, user_id: str, run_id: str) -> None:
    remaining = _scalar_count(
        connection,
        """
        SELECT COUNT(*) FROM messages
        WHERE instr('&' || session_scope || '&', '&user_id=' || ? || '&') > 0
          AND instr('&' || session_scope || '&', '&run_id=' || ? || '&') > 0
        """,
        (user_id, run_id),
    )
    if remaining:
        raise ResidueCleanupError("SQLite message residue remains")


def _scope_message_count(db: Any, *, user_id: str, run_id: str) -> int:
    connection, lock = _database_handles(db)
    with lock:
        return _scalar_count(
            connection,
            """
            SELECT COUNT(*) FROM messages
            WHERE instr('&' || session_scope || '&', '&user_id=' || ? || '&') > 0
              AND instr('&' || session_scope || '&', '&run_id=' || ? || '&') > 0
            """,
            (user_id, run_id),
        )


def _verify_scope_ledger_absent(connection: Any, *, user_id: str, run_id: str) -> None:
    remaining = _scalar_count(
        connection,
        f"SELECT COUNT(*) FROM {_LEDGER_TABLE} WHERE user_id = ? AND run_id = ?",
        (user_id, run_id),
    )
    if remaining:
        raise ResidueCleanupError("scope ledger residue remains")


def _verify_source_ledger_absent(
    connection: Any,
    *,
    user_id: str,
    run_id: str,
    source_id: str,
    source_sha256: str,
) -> None:
    remaining = _scalar_count(
        connection,
        f"""
        SELECT COUNT(*) FROM {_LEDGER_TABLE}
        WHERE user_id = ? AND run_id = ? AND source_id = ? AND source_sha256 = ?
        """,
        (user_id, run_id, source_id, source_sha256),
    )
    if remaining:
        raise ResidueCleanupError("source ledger residue remains")


def _verify_history_is_ledgered(connection: Any) -> None:
    missing = _scalar_count(
        connection,
        f"""
        SELECT COUNT(*)
        FROM history AS history_row
        LEFT JOIN {_LEDGER_TABLE} AS ledger
          ON ledger.memory_id = history_row.memory_id
        WHERE history_row.memory_id IS NULL OR ledger.memory_id IS NULL
        """,
    )
    if missing:
        raise ResidueCleanupError("Mem0 history contains ids absent from the scope ledger")


def _require_pinned_sqlite_schema(connection: Any) -> None:
    if _sqlite_columns(connection, "history") != _HISTORY_COLUMNS:
        raise ResidueCleanupError("Mem0 history schema differs from the pinned runtime")
    if _sqlite_columns(connection, "messages") != _MESSAGES_COLUMNS:
        raise ResidueCleanupError("Mem0 messages schema differs from the pinned runtime")


def _require_scope_ledger_schema(connection: Any) -> None:
    if _sqlite_columns(connection, _LEDGER_TABLE) != _LEDGER_COLUMNS:
        raise ResidueCleanupError("scope ledger schema differs from the pinned adapter")


def _sqlite_columns(connection: Any, table: str) -> frozenset[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    if not isinstance(rows, list):
        raise ResidueCleanupError("Mem0 SQLite schema inspection was invalid")
    columns = frozenset(
        row[1]
        for row in rows
        if isinstance(row, tuple) and len(row) >= 2 and isinstance(row[1], str)
    )
    if len(columns) != len(rows):
        raise ResidueCleanupError("Mem0 SQLite schema inspection was invalid")
    return columns


def _database_handles(db: Any) -> tuple[Any, Any]:
    connection = getattr(db, "connection", None)
    lock = getattr(db, "_lock", None)
    if connection is None or lock is None:
        raise ResidueCleanupError("Mem0 SQLite manager is unavailable")
    return connection, lock


def _scalar_count(connection: Any, query: str, parameters: Sequence[Any] = ()) -> int:
    row = connection.execute(query, tuple(parameters)).fetchone()
    if (
        not isinstance(row, tuple)
        or len(row) != 1
        or isinstance(row[0], bool)
        or not isinstance(row[0], int)
        or row[0] < 0
    ):
        raise ResidueCleanupError("Mem0 SQLite count response was invalid")
    return row[0]


def _validated_memory_ids(
    memory_ids: Sequence[object],
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    ids = tuple(memory_ids)
    if (not allow_empty and not ids) or len(ids) > _MAX_SCOPE_RECORDS:
        raise ResidueCleanupError("scope memory id count is invalid")
    if any(not isinstance(memory_id, str) or not memory_id for memory_id in ids):
        raise ResidueCleanupError("scope memory ids were invalid")
    if len(ids) != len(set(ids)):
        raise ResidueCleanupError("scope memory ids were duplicated")
    return ids


def _batches(memory_ids: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(memory_ids[offset : offset + _SQLITE_PARAMETER_BATCH])
        for offset in range(0, len(memory_ids), _SQLITE_PARAMETER_BATCH)
    )


def _rollback(connection: Any) -> None:
    with suppress(Exception):
        connection.execute("ROLLBACK")
