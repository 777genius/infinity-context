"""Exact private SQLite schema for the subscription-runtime bridge journal."""

from __future__ import annotations

import hashlib
import sqlite3

from .contracts import BridgeJournalError
from .json_boundary import canonical_json_bytes

SCHEMA_VERSION = 3
APPLICATION_ID = 0x49434252

SCHEMA = (
    """CREATE TABLE bridge_journal_metadata (
        singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL,
        schema_fingerprint_sha256 TEXT NOT NULL,
        journal_generation_sha256 TEXT NOT NULL,
        event_count INTEGER NOT NULL,
        head_hmac_sha256 TEXT NOT NULL
    ) WITHOUT ROWID""",
    """CREATE TABLE bridge_intents (
        intent_id TEXT NOT NULL PRIMARY KEY,
        event_sequence INTEGER NOT NULL,
        logical_operation TEXT NOT NULL,
        logical_call_id TEXT NOT NULL,
        request_identity_nonce TEXT NOT NULL,
        pool_id TEXT NOT NULL,
        pool_authority_sha256 TEXT NOT NULL,
        bridge_id TEXT NOT NULL,
        bridge_authority_sha256 TEXT NOT NULL,
        request_body_sha256 TEXT NOT NULL,
        prompt_input_sha256 TEXT NOT NULL,
        response_format_type TEXT NOT NULL,
        response_format_sha256 TEXT NOT NULL,
        response_schema_sha256 TEXT,
        output_token_limit INTEGER NOT NULL,
        row_hmac_sha256 TEXT NOT NULL
    ) WITHOUT ROWID""",
    """CREATE UNIQUE INDEX bridge_intents_logical_call
       ON bridge_intents (logical_call_id)""",
    """CREATE TABLE bridge_results (
        intent_id TEXT NOT NULL PRIMARY KEY,
        event_sequence INTEGER NOT NULL,
        response_body_sha256 TEXT NOT NULL,
        output_text_sha256 TEXT NOT NULL,
        attestation_sha256 TEXT NOT NULL,
        receipt_hmac_sha256 TEXT NOT NULL,
        dispatch_binding_hmac_sha256 TEXT NOT NULL,
        physical_receipt_sha256 TEXT NOT NULL,
        thread_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL,
        cached_tokens INTEGER NOT NULL,
        cache_write_tokens INTEGER,
        completion_tokens INTEGER NOT NULL,
        reasoning_tokens INTEGER NOT NULL,
        total_tokens INTEGER NOT NULL,
        encrypted_output BLOB NOT NULL,
        row_hmac_sha256 TEXT NOT NULL,
        FOREIGN KEY (intent_id) REFERENCES bridge_intents(intent_id)
    ) WITHOUT ROWID""",
    """CREATE UNIQUE INDEX bridge_results_physical_receipt
       ON bridge_results (physical_receipt_sha256)""",
)


def configure_connection(connection: sqlite3.Connection) -> None:
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA synchronous = FULL")
        journal_mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
        if journal_mode is None or str(journal_mode[0]).lower() != "delete":
            raise BridgeJournalError("bridge_journal_mode_invalid")
    except sqlite3.Error as exc:
        raise BridgeJournalError("bridge_journal_configuration_failed") from exc


def create_schema(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        if _schema_rows(connection):
            raise BridgeJournalError("bridge_journal_create_not_empty")
        for statement in SCHEMA:
            connection.execute(statement)
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise


def validate_schema(connection: sqlite3.Connection) -> None:
    try:
        if schema_fingerprint(connection) != expected_schema_fingerprint():
            raise BridgeJournalError("bridge_journal_schema_invalid")
        application_id = connection.execute("PRAGMA application_id").fetchone()
        user_version = connection.execute("PRAGMA user_version").fetchone()
        quick = connection.execute("PRAGMA quick_check").fetchone()
        foreign = connection.execute("PRAGMA foreign_key_check").fetchone()
        if (
            application_id is None
            or application_id[0] != APPLICATION_ID
            or user_version is None
            or user_version[0] != SCHEMA_VERSION
            or quick is None
            or quick[0] != "ok"
            or foreign is not None
        ):
            raise BridgeJournalError("bridge_journal_integrity_invalid")
    except sqlite3.Error as exc:
        raise BridgeJournalError("bridge_journal_integrity_invalid") from exc


def schema_fingerprint(connection: sqlite3.Connection) -> str:
    return hashlib.sha256(canonical_json_bytes(_schema_rows(connection))).hexdigest()


def expected_schema_fingerprint() -> str:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        for statement in SCHEMA:
            connection.execute(statement)
        return schema_fingerprint(connection)
    finally:
        connection.close()


def _schema_rows(connection: sqlite3.Connection) -> list[list[object]]:
    return [
        list(row)
        for row in connection.execute(
            """SELECT type, name, tbl_name, sql
               FROM sqlite_schema
               WHERE name NOT LIKE 'sqlite_%'
               ORDER BY type, name, tbl_name"""
        ).fetchall()
    ]


__all__ = (
    "SCHEMA_VERSION",
    "configure_connection",
    "create_schema",
    "expected_schema_fingerprint",
    "schema_fingerprint",
    "validate_schema",
)
