"""Exact schema identity for the resumable-operation SQLite journal."""

from __future__ import annotations

import sqlite3
from functools import cache

JOURNAL_TABLES = frozenset(
    {
        "schema_meta",
        "operation_runs",
        "operation_manifest",
        "operation_states",
        "operation_receipts",
        "operation_events",
        "operation_checkpoints",
        "operation_commitment_nodes",
        "notification_outbox",
    }
)

JOURNAL_SCHEMA = (
    """CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """
    CREATE TABLE operation_runs (
        run_id TEXT PRIMARY KEY,
        operation_namespace TEXT NOT NULL,
        manifest_commitment_sha256 TEXT NOT NULL,
        policy_commitment_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        expected_operation_count INTEGER NOT NULL,
        journal_schema_version TEXT NOT NULL,
        phase TEXT NOT NULL,
        event_count INTEGER NOT NULL,
        head_event_sha256 TEXT
    )
    """,
    """
    CREATE TABLE operation_manifest (
        run_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        logical_operation_id TEXT NOT NULL,
        replay_key TEXT NOT NULL,
        operation_key TEXT NOT NULL,
        operation_kind TEXT NOT NULL,
        authority_commitment_sha256 TEXT NOT NULL,
        retry_disposition TEXT NOT NULL,
        PRIMARY KEY (run_id, ordinal),
        UNIQUE (run_id, logical_operation_id),
        UNIQUE (run_id, replay_key),
        FOREIGN KEY (run_id) REFERENCES operation_runs(run_id)
    )
    """,
    """
    CREATE TABLE operation_states (
        run_id TEXT NOT NULL,
        logical_operation_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        phase TEXT NOT NULL,
        request_commitment_sha256 TEXT,
        receipt_id TEXT,
        result_commitment_sha256 TEXT,
        verifier_key_id TEXT,
        verification_commitment_sha256 TEXT,
        PRIMARY KEY (run_id, logical_operation_id),
        UNIQUE (run_id, ordinal),
        UNIQUE (run_id, receipt_id),
        FOREIGN KEY (run_id, logical_operation_id)
            REFERENCES operation_manifest(run_id, logical_operation_id),
        FOREIGN KEY (run_id, ordinal)
            REFERENCES operation_manifest(run_id, ordinal)
    )
    """,
    """
    CREATE TABLE operation_receipts (
        run_id TEXT NOT NULL,
        logical_operation_id TEXT NOT NULL,
        receipt_identity_json TEXT NOT NULL,
        receipt_commitment_sha256 TEXT NOT NULL,
        verifier_key_id TEXT NOT NULL,
        verification_commitment_sha256 TEXT NOT NULL,
        PRIMARY KEY (run_id, logical_operation_id),
        FOREIGN KEY (run_id, logical_operation_id)
            REFERENCES operation_states(run_id, logical_operation_id)
    )
    """,
    """
    CREATE TABLE operation_events (
        run_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        logical_operation_id TEXT,
        payload_json TEXT NOT NULL,
        predecessor_event_sha256 TEXT,
        event_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        signature TEXT NOT NULL,
        PRIMARY KEY (run_id, sequence),
        UNIQUE (run_id, event_sha256),
        FOREIGN KEY (run_id) REFERENCES operation_runs(run_id)
    )
    """,
    """
    CREATE TABLE operation_checkpoints (
        run_id TEXT PRIMARY KEY,
        checkpoint_json TEXT NOT NULL,
        checkpoint_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        signature TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES operation_runs(run_id)
    )
    """,
    """
    CREATE TABLE operation_commitment_nodes (
        run_id TEXT NOT NULL,
        tree_kind TEXT NOT NULL CHECK(tree_kind IN ('state', 'receipt')),
        level INTEGER NOT NULL CHECK(level >= 0),
        node_index INTEGER NOT NULL CHECK(node_index >= 0),
        commitment_sha256 TEXT NOT NULL,
        valid_count INTEGER NOT NULL CHECK(valid_count >= 0),
        pending_count INTEGER NOT NULL CHECK(pending_count >= 0),
        dispatched_count INTEGER NOT NULL CHECK(dispatched_count >= 0),
        committed_count INTEGER NOT NULL CHECK(committed_count >= 0),
        outcome_unknown_count INTEGER NOT NULL CHECK(outcome_unknown_count >= 0),
        receipt_count INTEGER NOT NULL CHECK(receipt_count >= 0),
        PRIMARY KEY (run_id, tree_kind, level, node_index),
        FOREIGN KEY (run_id) REFERENCES operation_runs(run_id)
    )
    """,
    """
    CREATE TABLE notification_outbox (
        run_id TEXT NOT NULL,
        event_sha256 TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, event_sha256),
        FOREIGN KEY (run_id, event_sha256)
            REFERENCES operation_events(run_id, event_sha256)
    )
    """,
    """CREATE INDEX idx_operation_states_phase
       ON operation_states(run_id, phase, logical_operation_id)""",
    """CREATE INDEX idx_operation_states_run_phase_ordinal
       ON operation_states(run_id, phase, ordinal)""",
    """CREATE INDEX idx_operation_outbox_pending
       ON notification_outbox(run_id, delivered, event_sha256)""",
)


def schema_fingerprint(connection: sqlite3.Connection) -> tuple[object, ...]:
    objects = tuple(
        tuple(row)
        for row in connection.execute(
            """SELECT type, name, tbl_name, sql FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
        )
    )
    columns = tuple(
        (
            table,
            tuple(tuple(row) for row in connection.execute(f'PRAGMA table_xinfo("{table}")')),
        )
        for table in sorted(JOURNAL_TABLES)
    )
    return objects, columns


@cache
def expected_schema_fingerprint() -> tuple[object, ...]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in JOURNAL_SCHEMA:
            connection.execute(statement)
        return schema_fingerprint(connection)
    finally:
        connection.close()


__all__ = (
    "JOURNAL_SCHEMA",
    "JOURNAL_TABLES",
    "expected_schema_fingerprint",
    "schema_fingerprint",
)
