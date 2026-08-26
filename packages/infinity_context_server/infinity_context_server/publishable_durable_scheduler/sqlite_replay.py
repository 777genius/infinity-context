"""Bounded authenticated reopen verification for scheduler SQLite state."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SQLITE_SCHEDULER_SCHEMA_VERSION,
    SchedulerSQLiteAuthenticator,
    SchedulerSQLiteError,
    SchedulerSQLiteEvent,
    genesis_event_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_rows import (
    call_from_row,
    event_from_row,
    shard_values,
    verify_material,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_schema import (
    schema_fingerprint_sha256,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerRunState,
)

_MANIFEST_COLUMNS = (
    "run_id",
    "suite_authority_sha256",
    "run_authority_sha256",
    "manifest_authority_sha256",
    "case_manifest_sha256",
    "call_count",
    "shard_count",
)
_SHARD_COLUMNS = (
    "run_id",
    "shard_index",
    "shard_sha256",
    "start_ordinal",
    "end_ordinal",
)


def verify_headers(
    connection: sqlite3.Connection,
    authenticator: SchedulerSQLiteAuthenticator,
    manifest: BuiltSchedulerManifest,
) -> None:
    meta = connection.execute("SELECT * FROM scheduler_meta").fetchone()
    if meta is None:
        _fail("scheduler_sqlite_meta_missing")
    meta_values = {
        "singleton": meta["singleton"],
        "schema_version": meta["schema_version"],
        "schema_fingerprint_sha256": meta["schema_fingerprint_sha256"],
    }
    verify_material(authenticator, "meta-row", meta_values, meta["row_mac"])
    if meta_values != {
        "singleton": 1,
        "schema_version": SQLITE_SCHEDULER_SCHEMA_VERSION,
        "schema_fingerprint_sha256": schema_fingerprint_sha256(),
    }:
        _fail("scheduler_sqlite_meta_invalid")
    row = connection.execute("SELECT * FROM scheduler_manifests").fetchone()
    if row is None:
        _fail("scheduler_sqlite_manifest_missing")
    values = {name: row[name] for name in _MANIFEST_COLUMNS}
    verify_material(authenticator, "manifest-row", values, row["row_mac"])
    authority = manifest.authority
    expected = {
        "run_id": authority.run_id,
        "suite_authority_sha256": authority.suite_authority_sha256,
        "run_authority_sha256": authority.run_authority_sha256,
        "manifest_authority_sha256": authority.commitment_sha256,
        "case_manifest_sha256": authority.case_manifest_sha256,
        "call_count": authority.call_count,
        "shard_count": len(authority.ordered_shard_commitments),
    }
    if values != expected:
        _fail("scheduler_sqlite_manifest_drift")
    rows = connection.execute(
        "SELECT * FROM scheduler_shards ORDER BY shard_index LIMIT 257"
    ).fetchall()
    if len(rows) != len(manifest.shards):
        _fail("scheduler_sqlite_shard_count_invalid")
    for row, shard in zip(rows, manifest.shards, strict=True):
        values = {name: row[name] for name in _SHARD_COLUMNS}
        verify_material(authenticator, "shard-row", values, row["row_mac"])
        if values != shard_values(authority.run_id, shard):
            _fail("scheduler_sqlite_shard_drift")


def verify_calls(
    connection: sqlite3.Connection,
    authenticator: SchedulerSQLiteAuthenticator,
    manifest: BuiltSchedulerManifest,
    expected_by_ordinal: Callable[[object], SchedulerLogicalCall],
) -> None:
    after = -1
    observed = 0
    while True:
        rows = connection.execute(
            """SELECT * FROM scheduler_calls WHERE run_id = ? AND ordinal > ?
               ORDER BY ordinal LIMIT 257""",
            (manifest.authority.run_id, after),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            call_from_row(row, authenticator, expected=expected_by_ordinal(row["ordinal"]))
            observed += 1
            after = row["ordinal"]
        if len(rows) < 257:
            break
    if observed != manifest.authority.call_count:
        _fail("scheduler_sqlite_call_count_invalid")


def verify_events(
    connection: sqlite3.Connection,
    authenticator: SchedulerSQLiteAuthenticator,
    *,
    run: SchedulerRunState,
    event_head: str,
) -> None:
    after = 0
    previous = genesis_event_sha256()
    last: SchedulerSQLiteEvent | None = None
    while True:
        rows = connection.execute(
            """SELECT * FROM scheduler_events WHERE run_id = ? AND event_id > ?
               ORDER BY event_id LIMIT 257""",
            (run.run_id, after),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            current = event_from_row(row, authenticator)
            if current.event_id != after + 1 or current.previous_event_sha256 != previous:
                _fail("scheduler_sqlite_event_chain_invalid")
            after = current.event_id
            previous = current.event_sha256
            last = current
        if len(rows) < 257:
            break
    if last is None or last.event_sha256 != event_head or last.run_version != run.version:
        _fail("scheduler_sqlite_event_head_invalid")


def _fail(code: str) -> None:
    raise SchedulerSQLiteError(code)


__all__ = ("verify_calls", "verify_events", "verify_headers")
