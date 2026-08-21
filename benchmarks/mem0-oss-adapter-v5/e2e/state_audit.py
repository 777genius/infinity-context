"""Independent authenticated reader for the adapter-owned operation SQLite."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path

from .canonical import E2EVerificationError, canonical_bytes, require_digest

_SCHEMA_VERSION = 3
_CREATE_OPERATIONS = """CREATE TABLE IF NOT EXISTS operations_v2 (
  unit_identity_sha256 TEXT PRIMARY KEY,
  request_sha256 TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN (
    'ADMITTED','RESERVED','DISPATCHED','RECEIPT_DURABLE',
    'STORAGE_VERIFIED','COMMITTED','CLEANED','ABORT_CLEANED')),
  runtime_receipt_sha256 TEXT,
  storage_commitment_sha256 TEXT,
  tombstone_commitment_sha256 TEXT,
  abort_origin_state TEXT,
  abort_result_sha256 TEXT,
  outcome_unknown INTEGER NOT NULL CHECK(outcome_unknown IN (0,1)),
  row_hmac TEXT NOT NULL,
  CHECK ((tombstone_commitment_sha256 IS NOT NULL) =
         (state IN ('CLEANED','ABORT_CLEANED'))),
  CHECK ((abort_origin_state IS NOT NULL AND abort_result_sha256 IS NOT NULL) =
         (state = 'ABORT_CLEANED')),
  CHECK (abort_origin_state IS NULL OR abort_origin_state IN
         ('ADMITTED','RESERVED','DISPATCHED','RECEIPT_DURABLE','STORAGE_VERIFIED')),
  CHECK (outcome_unknown = 0 OR state = 'DISPATCHED' OR
         (state = 'ABORT_CLEANED' AND abort_origin_state = 'DISPATCHED'))
) STRICT"""
_CREATE_META = """CREATE TABLE IF NOT EXISTS adapter_state_meta (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  schema_version INTEGER NOT NULL CHECK(schema_version = 3),
  structural_fingerprint TEXT NOT NULL,
  schema_hmac TEXT NOT NULL
) STRICT"""


def _stored_sql(value: str) -> str:
    return " ".join(value.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1).split())


_EXPECTED_TABLES = {
    "adapter_state_meta": _stored_sql(_CREATE_META),
    "operations_v2": _stored_sql(_CREATE_OPERATIONS),
}
_STRUCTURAL_FINGERPRINT = hashlib.sha256(
    json.dumps(_EXPECTED_TABLES, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


@dataclass(frozen=True, slots=True)
class OperationStateEvidence:
    unit_identity_sha256: str
    request_sha256: str
    state: str
    runtime_receipt_sha256: str | None
    storage_commitment_sha256: str | None
    tombstone_commitment_sha256: str | None
    abort_origin_state: str | None
    abort_result_sha256: str | None
    outcome_unknown: bool


class IndependentStateAuditor:
    def __init__(self, *, path: Path, hmac_key: bytes) -> None:
        if not path.is_absolute() or not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("e2e_state_auditor_invalid")
        self._path = path
        self._key = bytes(hmac_key)

    def for_path(self, path: Path) -> IndependentStateAuditor:
        return IndependentStateAuditor(path=path, hmac_key=self._key)

    def audit(
        self,
        *,
        expected_identity: str,
        expected_request_sha256: str,
        expected_state: str,
    ) -> OperationStateEvidence:
        if self._path.is_symlink() or not self._path.is_file():
            raise E2EVerificationError("e2e_state_file_invalid")
        if stat.S_IMODE(self._path.stat().st_mode) & 0o077:
            raise E2EVerificationError("e2e_state_file_invalid")
        connection = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True, timeout=10)
        try:
            connection.execute("PRAGMA trusted_schema=OFF")
            self._verify_schema(connection)
            rows = connection.execute(
                """SELECT unit_identity_sha256, request_sha256, state,
                          runtime_receipt_sha256, storage_commitment_sha256,
                          tombstone_commitment_sha256, abort_origin_state,
                          abort_result_sha256, outcome_unknown, row_hmac
                   FROM operations_v2 ORDER BY unit_identity_sha256"""
            ).fetchall()
        except sqlite3.Error:
            raise E2EVerificationError("e2e_state_read_failed") from None
        finally:
            connection.close()
        if len(rows) != 1:
            raise E2EVerificationError("e2e_state_inventory_invalid")
        row = rows[0]
        payload = {
            "abort_origin_state": row[6],
            "abort_result_sha256": row[7],
            "outcome_unknown": row[8] == 1,
            "request_sha256": row[1],
            "runtime_receipt_sha256": row[3],
            "state": row[2],
            "storage_commitment_sha256": row[4],
            "tombstone_commitment_sha256": row[5],
            "unit_identity_sha256": row[0],
        }
        presented = require_digest(row[9], "e2e_state_row_invalid")
        if row[8] not in {0, 1} or not hmac.compare_digest(presented, self._hmac(payload)):
            raise E2EVerificationError("e2e_state_row_unauthenticated")
        self._verify_semantics(payload)
        if (
            row[0] != expected_identity
            or row[1] != expected_request_sha256
            or row[2] != expected_state
        ):
            raise E2EVerificationError("e2e_state_binding_invalid")
        return OperationStateEvidence(
            unit_identity_sha256=row[0],
            request_sha256=row[1],
            state=row[2],
            runtime_receipt_sha256=row[3],
            storage_commitment_sha256=row[4],
            tombstone_commitment_sha256=row[5],
            abort_origin_state=row[6],
            abort_result_sha256=row[7],
            outcome_unknown=bool(row[8]),
        )

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = {
            name: " ".join(str(sql).split())
            for kind, name, sql in rows
            if kind == "table" and not str(name).startswith("sqlite_")
        }
        unexpected = [
            (kind, name)
            for kind, name, sql in rows
            if kind in {"trigger", "view"} or (kind == "index" and sql is not None)
        ]
        meta = connection.execute(
            "SELECT schema_version, structural_fingerprint, schema_hmac FROM adapter_state_meta"
        ).fetchall()
        expected_hmac = self._hmac(
            {"schema_version": _SCHEMA_VERSION, "fingerprint": _STRUCTURAL_FINGERPRINT}
        )
        if (
            tables != _EXPECTED_TABLES
            or unexpected
            or len(meta) != 1
            or meta[0][:2] != (_SCHEMA_VERSION, _STRUCTURAL_FINGERPRINT)
            or not isinstance(meta[0][2], str)
            or not hmac.compare_digest(meta[0][2], expected_hmac)
        ):
            raise E2EVerificationError("e2e_state_schema_unauthenticated")

    @staticmethod
    def _verify_semantics(payload: dict[str, object]) -> None:
        state = payload["state"]
        receipt_states = {"RECEIPT_DURABLE", "STORAGE_VERIFIED", "COMMITTED", "CLEANED"}
        storage_states = {"STORAGE_VERIFIED", "COMMITTED", "CLEANED"}
        if state not in {
            "ADMITTED",
            "RESERVED",
            "DISPATCHED",
            "RECEIPT_DURABLE",
            "STORAGE_VERIFIED",
            "COMMITTED",
            "CLEANED",
            "ABORT_CLEANED",
        }:
            raise E2EVerificationError("e2e_state_row_invalid")
        if state == "ABORT_CLEANED":
            origin = payload["abort_origin_state"]
            if origin not in {
                "ADMITTED",
                "RESERVED",
                "DISPATCHED",
                "RECEIPT_DURABLE",
                "STORAGE_VERIFIED",
            }:
                raise E2EVerificationError("e2e_state_row_invalid")
            requires_receipt = origin in {"RECEIPT_DURABLE", "STORAGE_VERIFIED"}
            requires_storage = origin == "STORAGE_VERIFIED"
            if (
                payload["abort_result_sha256"] is None
                or payload["tombstone_commitment_sha256"] is None
                or (payload["runtime_receipt_sha256"] is not None) != requires_receipt
                or (payload["storage_commitment_sha256"] is not None) != requires_storage
                or (payload["outcome_unknown"] is True and origin != "DISPATCHED")
            ):
                raise E2EVerificationError("e2e_state_row_invalid")
        elif (
            (payload["runtime_receipt_sha256"] is not None) != (state in receipt_states)
            or (payload["storage_commitment_sha256"] is not None) != (state in storage_states)
            or (payload["tombstone_commitment_sha256"] is not None) != (state == "CLEANED")
            or payload["abort_origin_state"] is not None
            or payload["abort_result_sha256"] is not None
            or (payload["outcome_unknown"] is True and state != "DISPATCHED")
        ):
            raise E2EVerificationError("e2e_state_row_invalid")
        for name in (
            "unit_identity_sha256",
            "request_sha256",
            "runtime_receipt_sha256",
            "storage_commitment_sha256",
            "tombstone_commitment_sha256",
            "abort_result_sha256",
        ):
            if payload[name] is not None:
                require_digest(payload[name], "e2e_state_row_invalid")

    def _hmac(self, value: object) -> str:
        return hmac.new(self._key, canonical_bytes(value), hashlib.sha256).hexdigest()
