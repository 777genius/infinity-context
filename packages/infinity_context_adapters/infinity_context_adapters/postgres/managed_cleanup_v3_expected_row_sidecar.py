"""Authenticated mutable sidecar lifecycle for cleanup-v4 expected-row claims."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import suppress
from pathlib import Path
from typing import Final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    canonical_bytes,
    commitment,
    digest,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_claims import (
    create_claim_schema,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_files import (
    close_secure_sqlite,
    create_secure_sqlite,
    open_secure_sqlite,
    unlink_secure_file,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_index_storage import (
    configure_index,
)

_MAC_DOMAIN: Final = b"managed-cleanup-v4/expected-row-claims-sidecar/v1\0"
_SCHEMA: Final = "managed-cleanup-v4-expected-row-claims-sidecar.v1"
_TABLES: Final = ("claims_metadata", "verification_claims", "verification_session")
_RACE_ATTEMPTS: Final = 100
_RACE_DELAY_SECONDS: Final = 0.01


def create_claim_sidecar(
    path: Path,
    *,
    context_sha256: str,
    authority_terminal_sha256: str,
    authentication_key: bytes,
) -> tuple[sqlite3.Connection, int]:
    """O_EXCL-create and authenticate a new empty claim sidecar."""
    context, terminal, key = _binding(context_sha256, authority_terminal_sha256, authentication_key)
    db, descriptor = create_secure_sqlite(path)
    try:
        configure_index(db)
        create_claim_schema(db)
        db.execute(
            "CREATE TABLE claims_metadata("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
            "payload_json TEXT NOT NULL,authentication_tag TEXT NOT NULL) STRICT"
        )
        payload = _payload(db, context, terminal)
        db.execute(
            "INSERT INTO claims_metadata VALUES(1,?,?)",
            (_encoded(payload).decode("ascii"), _tag(key, payload)),
        )
        db.commit()
        return db, descriptor
    except BaseException:
        try:
            with suppress(ManagedCleanupV3Error, FileNotFoundError):
                unlink_secure_file(path, descriptor)
        finally:
            close_secure_sqlite(db, descriptor)
        raise


def open_claim_sidecar(
    path: Path,
    *,
    context_sha256: str,
    authority_terminal_sha256: str,
    authentication_key: bytes,
    require_empty: bool = False,
) -> tuple[sqlite3.Connection, int]:
    """Open an existing sidecar and reject schema or binding divergence."""
    if type(require_empty) is not bool:
        _fail("empty_requirement_invalid")
    context, terminal, key = _binding(context_sha256, authority_terminal_sha256, authentication_key)
    db, descriptor = open_secure_sqlite(path, readonly=False)
    try:
        configure_index(db)
        row = db.execute(
            "SELECT payload_json,authentication_tag FROM claims_metadata WHERE singleton=1"
        ).fetchone()
        expected = _payload(db, context, terminal)
        if row is None:
            _fail("metadata_invalid")
        try:
            actual = json.loads(str(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ManagedCleanupV3Error(
                "managed_cleanup_v3_expected_index_claim_sidecar_metadata_invalid"
            ) from exc
        if actual != expected or not hmac.compare_digest(str(row[1]), _tag(key, expected)):
            _fail("authentication_invalid")
        if require_empty and (
            db.execute("SELECT 1 FROM verification_session LIMIT 1").fetchone() is not None
            or db.execute("SELECT 1 FROM verification_claims LIMIT 1").fetchone() is not None
        ):
            _fail("race_winner_not_empty")
        return db, descriptor
    except BaseException:
        close_secure_sqlite(db, descriptor)
        raise


def repair_missing_claim_sidecar(
    path: Path,
    *,
    context_sha256: str,
    authority_terminal_sha256: str,
    authentication_key: bytes,
) -> tuple[sqlite3.Connection, int]:
    """Create only an absent sidecar; an O_EXCL race reopens the winner."""
    arguments = {
        "context_sha256": context_sha256,
        "authority_terminal_sha256": authority_terminal_sha256,
        "authentication_key": authentication_key,
    }
    try:
        return create_claim_sidecar(path, **arguments)
    except ManagedCleanupV3Error as exc:
        if not _caused_by_exists(exc):
            raise
        last_error: BaseException = exc
        for _attempt in range(_RACE_ATTEMPTS):
            try:
                return open_claim_sidecar(path, require_empty=True, **arguments)
            except BaseException as race_error:
                last_error = race_error
                time.sleep(_RACE_DELAY_SECONDS)
        raise last_error from exc


def _payload(db: sqlite3.Connection, context: str, terminal: str) -> dict[str, object]:
    rows = tuple(
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    )
    tables = tuple(row[1] for row in rows if row[0] == "table")
    if tables != _TABLES or any(row[0] != "table" for row in rows):
        _fail("schema_invalid")
    return {
        "schema_version": _SCHEMA,
        "context_sha256": context,
        "authority_terminal_sha256": terminal,
        "schema_sha256": commitment("expected-row-claims-sidecar-schema/v4", rows),
    }


def _binding(context: str, terminal: str, key: bytes) -> tuple[str, str, bytes]:
    if type(key) is not bytes or len(key) < 32:
        _fail("authentication_key_invalid")
    return digest(context), digest(terminal), key


def _tag(key: bytes, payload: object) -> str:
    return hmac.new(key, _MAC_DOMAIN + _encoded(payload), hashlib.sha256).hexdigest()


def _encoded(payload: object) -> bytes:
    return canonical_bytes(payload)


def _caused_by_exists(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, OSError) and current.errno == errno.EEXIST:
            return True
        current = current.__cause__
    return False


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_index_claim_sidecar_{suffix}")


__all__ = (
    "create_claim_sidecar",
    "open_claim_sidecar",
    "repair_missing_claim_sidecar",
)
