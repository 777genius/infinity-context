from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes

_USAGE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS provider_usage_v3 (
  slot_id TEXT PRIMARY KEY,
  request_sha256 TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN
    ('reserved','dispatched','committed','outcome_unknown')),
  envelope_json TEXT,
  receipt_json TEXT,
  CHECK ((state = 'committed') =
         (envelope_json IS NOT NULL AND receipt_json IS NOT NULL))
) STRICT"""
_META_TABLE_SQL = """CREATE TABLE IF NOT EXISTS provider_usage_meta (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  schema_version INTEGER NOT NULL CHECK(schema_version = 3),
  structural_fingerprint TEXT NOT NULL
) STRICT"""


def _stored_table_sql(value: str) -> str:
    return " ".join(value.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1).split())


PROVIDER_USAGE_STRUCTURAL_FINGERPRINT = sha256_bytes(
    canonical_json_bytes(
        {
            "schema_version": 3,
            "tables": {
                "provider_usage_meta": _stored_table_sql(_META_TABLE_SQL),
                "provider_usage_v3": _stored_table_sql(_USAGE_TABLE_SQL),
            },
            "triggers": [],
            "views": [],
            "explicit_indexes": [],
        }
    )
)


class JournalError(RuntimeError):
    pass


class SlotState(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    COMMITTED = "committed"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True)
class SlotRecord:
    slot_id: str
    request_sha256: str
    state: SlotState
    envelope: dict[str, Any] | None
    receipt: dict[str, Any] | None


class ProviderUsageJournal:
    """Durable schema-v3 provider ledger with conservative crash recovery."""

    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute(_USAGE_TABLE_SQL)
        self._connection.execute(_META_TABLE_SQL)
        try:
            self._validate_structure(allow_empty_meta=True)
            self._connection.execute(
                "INSERT OR IGNORE INTO provider_usage_meta VALUES (1, 3, ?)",
                (PROVIDER_USAGE_STRUCTURAL_FINGERPRINT,),
            )
            self._validate_structure(allow_empty_meta=False)
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def reserve(self, slot_id: str, request: dict[str, Any]) -> SlotRecord:
        request_sha = sha256_bytes(canonical_json_bytes(request))
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO provider_usage_v3 VALUES (?, ?, ?, NULL, NULL)",
                (slot_id, request_sha, SlotState.RESERVED.value),
            )
        record = self.get(slot_id)
        if record.request_sha256 != request_sha:
            raise JournalError("slot identity was reused with a different request")
        return record

    def mark_dispatched(self, slot_id: str) -> None:
        changed = self._connection.execute(
            "UPDATE provider_usage_v3 SET state = ? WHERE slot_id = ? AND state = ?",
            (SlotState.DISPATCHED.value, slot_id, SlotState.RESERVED.value),
        ).rowcount
        if changed != 1:
            raise JournalError("only a reserved slot can be dispatched")

    def commit_result(
        self,
        slot_id: str,
        envelope: dict[str, Any],
        receipt: dict[str, Any],
    ) -> None:
        envelope_json = canonical_json_bytes(envelope).decode()
        receipt_json = canonical_json_bytes(receipt).decode()
        with self._connection:
            changed = self._connection.execute(
                """UPDATE provider_usage_v3
                   SET state = ?, envelope_json = ?, receipt_json = ?
                   WHERE slot_id = ? AND state = ?""",
                (
                    SlotState.COMMITTED.value,
                    envelope_json,
                    receipt_json,
                    slot_id,
                    SlotState.DISPATCHED.value,
                ),
            ).rowcount
            if changed != 1:
                raise JournalError("only a dispatched slot can commit a result")

    def recover(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return retryable reserved slots and quarantine all dispatched slots."""
        with self._connection:
            dispatched = tuple(
                row[0]
                for row in self._connection.execute(
                    "SELECT slot_id FROM provider_usage_v3 WHERE state = ? ORDER BY slot_id",
                    (SlotState.DISPATCHED.value,),
                )
            )
            self._connection.executemany(
                "UPDATE provider_usage_v3 SET state = ? WHERE slot_id = ?",
                ((SlotState.OUTCOME_UNKNOWN.value, slot) for slot in dispatched),
            )
        reserved = tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT slot_id FROM provider_usage_v3 WHERE state = ? ORDER BY slot_id",
                (SlotState.RESERVED.value,),
            )
        )
        unknown = tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT slot_id FROM provider_usage_v3 WHERE state = ? ORDER BY slot_id",
                (SlotState.OUTCOME_UNKNOWN.value,),
            )
        )
        return reserved, unknown

    def get(self, slot_id: str) -> SlotRecord:
        row = self._connection.execute(
            "SELECT slot_id, request_sha256, state, envelope_json, receipt_json "
            "FROM provider_usage_v3 WHERE slot_id = ?",
            (slot_id,),
        ).fetchone()
        if row is None:
            raise JournalError(f"unknown provider slot: {slot_id}")
        return SlotRecord(
            slot_id=row[0],
            request_sha256=row[1],
            state=SlotState(row[2]),
            envelope=json.loads(row[3]) if row[3] else None,
            receipt=json.loads(row[4]) if row[4] else None,
        )

    def _validate_structure(self, *, allow_empty_meta: bool) -> None:
        rows = self._connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = {
            name: " ".join(sql.split())
            for kind, name, sql in rows
            if kind == "table" and not name.startswith("sqlite_")
        }
        expected_tables = {
            "provider_usage_meta": _stored_table_sql(_META_TABLE_SQL),
            "provider_usage_v3": _stored_table_sql(_USAGE_TABLE_SQL),
        }
        unexpected_objects = [
            (kind, name)
            for kind, name, sql in rows
            if kind in {"trigger", "view"} or (kind == "index" and sql is not None)
        ]
        meta = self._connection.execute(
            "SELECT singleton, schema_version, structural_fingerprint FROM provider_usage_meta"
        ).fetchall()
        expected_meta = (
            [[], [(1, 3, PROVIDER_USAGE_STRUCTURAL_FINGERPRINT)]]
            if allow_empty_meta
            else [[(1, 3, PROVIDER_USAGE_STRUCTURAL_FINGERPRINT)]]
        )
        if tables != expected_tables or unexpected_objects or meta not in expected_meta:
            raise JournalError("provider usage journal structural fingerprint mismatch")
