from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from pathlib import Path

import pytest

from e2e.canonical import E2EVerificationError, canonical_bytes
from e2e.scenario import scan_durable_artifacts
from e2e.state_audit import (
    _CREATE_META,
    _CREATE_OPERATIONS,
    _SCHEMA_VERSION,
    _STRUCTURAL_FINGERPRINT,
    IndependentStateAuditor,
)
from e2e.storage_audit import IndependentStorageAuditor, StorageScope


def _hmac(key: bytes, value: object) -> str:
    return hmac.new(key, canonical_bytes(value), hashlib.sha256).hexdigest()


def _operation_db(path: Path, key: bytes) -> None:
    connection = sqlite3.connect(path)
    connection.execute(_CREATE_OPERATIONS)
    connection.execute(_CREATE_META)
    schema_hmac = _hmac(
        key,
        {"schema_version": _SCHEMA_VERSION, "fingerprint": _STRUCTURAL_FINGERPRINT},
    )
    connection.execute(
        "INSERT INTO adapter_state_meta VALUES (1, ?, ?, ?)",
        (_SCHEMA_VERSION, _STRUCTURAL_FINGERPRINT, schema_hmac),
    )
    payload = {
        "abort_origin_state": None,
        "abort_result_sha256": None,
        "outcome_unknown": False,
        "request_sha256": "2" * 64,
        "runtime_receipt_sha256": "3" * 64,
        "state": "COMMITTED",
        "storage_commitment_sha256": "4" * 64,
        "tombstone_commitment_sha256": None,
        "unit_identity_sha256": "1" * 64,
    }
    connection.execute(
        "INSERT INTO operations_v2 VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, 0, ?)",
        ("1" * 64, "2" * 64, "COMMITTED", "3" * 64, "4" * 64, _hmac(key, payload)),
    )
    connection.commit()
    connection.close()
    os.chmod(path, 0o600)


def test_state_auditor_verifies_hmac_and_rejects_tamper(tmp_path) -> None:
    path = tmp_path / "operations.sqlite3"
    key = b"k" * 32
    _operation_db(path, key)
    auditor = IndependentStateAuditor(path=path, hmac_key=key)
    evidence = auditor.audit(
        expected_identity="1" * 64,
        expected_request_sha256="2" * 64,
        expected_state="COMMITTED",
    )
    assert evidence.storage_commitment_sha256 == "4" * 64
    connection = sqlite3.connect(path)
    connection.execute("UPDATE operations_v2 SET storage_commitment_sha256 = ?", ("5" * 64,))
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="e2e_state_row_unauthenticated"):
        auditor.audit(
            expected_identity="1" * 64,
            expected_request_sha256="2" * 64,
            expected_state="COMMITTED",
        )


def test_state_auditor_accepts_authenticated_operator_abort_terminal(tmp_path) -> None:
    path = tmp_path / "aborted-operations.sqlite3"
    key = b"k" * 32
    connection = sqlite3.connect(path)
    connection.execute(_CREATE_OPERATIONS)
    connection.execute(_CREATE_META)
    connection.execute(
        "INSERT INTO adapter_state_meta VALUES (1, ?, ?, ?)",
        (
            _SCHEMA_VERSION,
            _STRUCTURAL_FINGERPRINT,
            _hmac(
                key,
                {
                    "schema_version": _SCHEMA_VERSION,
                    "fingerprint": _STRUCTURAL_FINGERPRINT,
                },
            ),
        ),
    )
    payload = {
        "abort_origin_state": "DISPATCHED",
        "abort_result_sha256": "5" * 64,
        "outcome_unknown": True,
        "request_sha256": "2" * 64,
        "runtime_receipt_sha256": None,
        "state": "ABORT_CLEANED",
        "storage_commitment_sha256": None,
        "tombstone_commitment_sha256": "4" * 64,
        "unit_identity_sha256": "1" * 64,
    }
    connection.execute(
        "INSERT INTO operations_v2 VALUES (?, ?, ?, NULL, NULL, ?, ?, ?, 1, ?)",
        (
            "1" * 64,
            "2" * 64,
            "ABORT_CLEANED",
            "4" * 64,
            "DISPATCHED",
            "5" * 64,
            _hmac(key, payload),
        ),
    )
    connection.commit()
    connection.close()
    os.chmod(path, 0o600)

    evidence = IndependentStateAuditor(path=path, hmac_key=key).audit(
        expected_identity="1" * 64,
        expected_request_sha256="2" * 64,
        expected_state="ABORT_CLEANED",
    )
    assert evidence.abort_origin_state == "DISPATCHED"
    assert evidence.outcome_unknown is True


class _Qdrant:
    collection = "mem0_oss_v5"
    entity_collection = "mem0_oss_v5_entities"

    def __init__(
        self,
        points: list[dict[str, object]],
        entities: list[dict[str, object]] | None = None,
    ) -> None:
        self.points = points
        self.entities = entities or []

    def scroll_all(self, collection: str) -> list[dict[str, object]]:
        return list(self.points if collection == self.collection else self.entities)


def _history_db(path: Path, scope: StorageScope, provider_id: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE history (
            id TEXT PRIMARY KEY, memory_id TEXT, old_memory TEXT, new_memory TEXT,
            event TEXT, created_at DATETIME, updated_at DATETIME, is_deleted INTEGER,
            actor_id TEXT, role TEXT)"""
    )
    connection.execute(
        """CREATE TABLE messages (
            id TEXT PRIMARY KEY, session_scope TEXT, role TEXT, content TEXT,
            name TEXT, created_at DATETIME)"""
    )
    connection.execute(
        """CREATE TABLE infinity_context_scope_ledger (
            memory_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, run_id TEXT NOT NULL,
            source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL)"""
    )
    connection.execute(
        "INSERT INTO history VALUES (?, ?, NULL, ?, 'ADD', ?, ?, 0, NULL, 'assistant')",
        (
            "history-1",
            provider_id,
            "Alice likes tea.",
            "2026-08-06T00:00:00Z",
            "2026-08-06T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO infinity_context_scope_ledger VALUES (?, ?, ?, ?, ?)",
        (provider_id, scope.user_id, scope.run_id, scope.source_id, scope.source_sha256),
    )
    connection.commit()
    connection.close()


def _point(scope: StorageScope) -> dict[str, object]:
    text = "Alice likes tea."
    return {
        "id": "provider-1",
        "payload": {
            **scope.filters,
            "data": text,
            "hash": hashlib.md5(text.encode(), usedforsecurity=False).hexdigest(),
            "created_at": "2026-08-06T00:00:00Z",
            "updated_at": "2026-08-06T00:00:00Z",
            "text_lemmatized": text,
            "role": "assistant",
            "extraction_memory_id": "0",
            "attributed_to": "user",
            "linked_memory_ids": [],
        },
    }


def test_storage_auditor_binds_global_qdrant_and_sqlite_inventory(tmp_path) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    auditor = IndependentStorageAuditor(qdrant=_Qdrant([_point(scope)]), history_db=history)
    result = auditor.verify_exact(scope=scope, expected_text="Alice likes tea.")
    assert result.provider_memory_ids == ("provider-1",)


def test_storage_auditor_accepts_pinned_v5_sqlite_without_legacy_scope_ledger(tmp_path) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    connection = sqlite3.connect(history)
    connection.execute("DROP TABLE infinity_context_scope_ledger")
    connection.commit()
    connection.close()
    auditor = IndependentStorageAuditor(qdrant=_Qdrant([_point(scope)]), history_db=history)
    assert auditor.verify_exact(
        scope=scope, expected_text="Alice likes tea."
    ).provider_memory_ids == ("provider-1",)


@pytest.mark.parametrize("residue", ["wrong-scope", "metadata-less", "entity"])
def test_storage_auditor_rejects_global_qdrant_false_pass(tmp_path, residue) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    expected = _point(scope)
    wrong = _point(StorageScope("other", "other-run", "other-source", "b" * 64))
    wrong["id"] = "provider-extra"
    metadata_less = {"id": "provider-extra", "payload": {}}
    qdrant = {
        "wrong-scope": _Qdrant([expected, wrong]),
        "metadata-less": _Qdrant([expected, metadata_less]),
        "entity": _Qdrant([expected], [wrong]),
    }[residue]
    auditor = IndependentStorageAuditor(qdrant=qdrant, history_db=history)
    with pytest.raises(E2EVerificationError, match="e2e_storage_inventory_invalid"):
        auditor.verify_exact(scope=scope, expected_text="Alice likes tea.")


@pytest.mark.parametrize("extra_key", ["raw_prompt", "output", "bearer"])
def test_storage_auditor_rejects_any_extra_qdrant_payload_field(tmp_path, extra_key) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    point = _point(scope)
    payload = point["payload"]
    assert isinstance(payload, dict)
    payload[extra_key] = "must-not-be-durable"
    auditor = IndependentStorageAuditor(qdrant=_Qdrant([point]), history_db=history)
    with pytest.raises(E2EVerificationError, match="e2e_storage_provenance_invalid"):
        auditor.verify_exact(scope=scope, expected_text="Alice likes tea.")


@pytest.mark.parametrize("table", ["history", "messages", "infinity_context_scope_ledger"])
def test_storage_auditor_rejects_unsealed_sqlite_rows(tmp_path, table) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    connection = sqlite3.connect(history)
    if table == "history":
        connection.execute(
            """INSERT INTO history VALUES (
                'extra', 'unsealed', NULL, 'x', 'ADD', 't', 't', 0, NULL, 'assistant'
            )"""
        )
    elif table == "messages":
        connection.execute(
            "INSERT INTO messages VALUES ('extra', 'foreign', 'user', 'x', NULL, 't')"
        )
    else:
        connection.execute(
            "INSERT INTO infinity_context_scope_ledger VALUES ('unsealed', 'u', 'r', 's', ?)",
            ("b" * 64,),
        )
    connection.commit()
    connection.close()
    auditor = IndependentStorageAuditor(qdrant=_Qdrant([_point(scope)]), history_db=history)
    with pytest.raises(E2EVerificationError, match="e2e_storage_sqlite_invalid"):
        auditor.verify_exact(scope=scope, expected_text="Alice likes tea.")


def test_cleanup_audit_requires_total_global_zero_residue(tmp_path) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    auditor = IndependentStorageAuditor(
        qdrant=_Qdrant([_point(StorageScope("foreign", "r", "s", "b" * 64))]),
        history_db=history,
    )
    with pytest.raises(E2EVerificationError, match="e2e_storage_residue_detected"):
        auditor.verify_absent(scope=scope, sealed_provider_ids=("provider-1",))


def test_cleanup_audit_rejects_global_sqlite_residue_with_empty_qdrant(tmp_path) -> None:
    scope = StorageScope("corpus", "run", "source", "a" * 64)
    history = tmp_path / "history.db"
    _history_db(history, scope, "provider-1")
    auditor = IndependentStorageAuditor(qdrant=_Qdrant([]), history_db=history)
    with pytest.raises(E2EVerificationError, match="e2e_storage_residue_detected"):
        auditor.verify_absent(scope=scope, sealed_provider_ids=("provider-1",))


def test_durable_artifact_scan_rejects_symlink(tmp_path) -> None:
    durable = tmp_path / "state"
    durable.mkdir()
    target = tmp_path / "target"
    target.write_text("safe")
    (durable / "linked").symlink_to(target)
    with pytest.raises(E2EVerificationError, match="e2e_durable_artifact_invalid"):
        scan_durable_artifacts((durable,), ())
