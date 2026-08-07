from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

import pytest

from e2e.canonical import E2EVerificationError
from e2e.scenario import ProviderFreeE2EScenario, _backup_sqlite, _tamper_state_row
from e2e.state_audit import _CREATE_OPERATIONS
from e2e.storage_audit import StorageScope


class _InvalidBaselineReceiptVerifier:
    def verify(self, _receipt: object) -> str:
        raise E2EVerificationError("e2e_receipt_invalid")


def test_receipt_tamper_probe_requires_valid_baseline_first() -> None:
    scenario = SimpleNamespace(_receipt_verifier=_InvalidBaselineReceiptVerifier())
    receipt = {"metadata": {"receipt_hmac_sha256": "0" * 64}}
    with pytest.raises(E2EVerificationError, match="e2e_receipt_invalid"):
        ProviderFreeE2EScenario._assert_receipt_tamper_rejected(scenario, receipt)


class _InvalidBaselineStateAuditor:
    def audit(self, **_kwargs: object) -> None:
        raise E2EVerificationError("e2e_state_binding_invalid")


def test_state_tamper_probe_requires_cleaned_baseline_first() -> None:
    fixture = SimpleNamespace(
        unit=SimpleNamespace(unit_identity_sha256="1" * 64),
        request_body_sha256="2" * 64,
    )
    scenario = SimpleNamespace(_state=_InvalidBaselineStateAuditor(), _fixture=fixture)
    with pytest.raises(E2EVerificationError, match="e2e_state_binding_invalid"):
        ProviderFreeE2EScenario._assert_state_tamper_rejected(scenario)


def test_sqlite_backup_contains_committed_row_while_source_connection_is_open(tmp_path) -> None:
    source_path = tmp_path / "source.sqlite3"
    copied_path = tmp_path / "copied.sqlite3"
    source = sqlite3.connect(source_path)
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute(_CREATE_OPERATIONS)
        source.execute(
            """INSERT INTO operations_v2 VALUES
               (?, ?, 'COMMITTED', ?, ?, NULL, NULL, NULL, 0, ?)""",
            ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64),
        )
        source.commit()

        _backup_sqlite(source_path, copied_path)
    finally:
        source.close()

    copied = sqlite3.connect(copied_path)
    try:
        assert copied.execute("SELECT unit_identity_sha256 FROM operations_v2").fetchall() == [
            ("1" * 64,)
        ]
    finally:
        copied.close()
    assert os.stat(copied_path).st_mode & 0o777 == 0o600


def test_state_tamper_rejects_zero_row_target_before_commit(tmp_path) -> None:
    path = tmp_path / "operations.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute(_CREATE_OPERATIONS)
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(E2EVerificationError, match="e2e_state_tamper_target_invalid"):
        _tamper_state_row(path, "1" * 64)

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM operations_v2").fetchone() == (0,)
    finally:
        connection.close()


class _ResidueBaselineStorageAuditor:
    def verify_absent(self, **_kwargs: object) -> None:
        raise E2EVerificationError("e2e_storage_residue_detected")


class _MustNotInject:
    def inject_residue(self, _scope: object) -> None:
        raise AssertionError("tamper mutation ran before baseline proof")


def test_storage_tamper_probe_requires_zero_residue_baseline_first() -> None:
    expected = object()
    scenario = object.__new__(ProviderFreeE2EScenario)
    scenario._storage = _ResidueBaselineStorageAuditor()
    scenario._qdrant = _MustNotInject()
    scenario._state = SimpleNamespace(audit=lambda **_kwargs: expected)
    scenario._counter = SimpleNamespace(read=lambda: 1)
    scenario._fixture = SimpleNamespace(
        unit=SimpleNamespace(unit_identity_sha256="1" * 64),
        request_body_sha256="2" * 64,
    )
    scope = StorageScope("u", "r", "s", "a" * 64)
    with pytest.raises(E2EVerificationError, match="e2e_storage_residue_detected"):
        scenario._assert_storage_residue_rejected(
            scope,
            {},
            expected_cleaned=expected,
            sealed_provider_ids=(),
        )


class _ProbeQdrant:
    def __init__(self) -> None:
        self.active = False

    def inject_residue(self, _scope: object) -> str:
        self.active = True
        return "forged"

    def delete_point(self, _point_id: str) -> None:
        self.active = False


class _ProbeStorage:
    def __init__(self, qdrant: _ProbeQdrant) -> None:
        self._qdrant = qdrant

    def verify_absent(self, **_kwargs: object) -> None:
        if self._qdrant.active:
            raise E2EVerificationError("e2e_storage_residue_detected")


class _MutatingRejectedCleanup:
    def __init__(self, state: SimpleNamespace) -> None:
        self._state = state

    def cleanup(self, _body: object, _key: object) -> None:
        self._state.current = object()
        raise E2EVerificationError("e2e_http_remote_failed")


def test_rejected_cleanup_probe_cannot_pass_after_mutating_cleaned_state() -> None:
    expected = object()
    state = SimpleNamespace(current=expected)
    state.audit = lambda **_kwargs: state.current
    qdrant = _ProbeQdrant()
    fixture = SimpleNamespace(
        unit=SimpleNamespace(unit_identity_sha256="1" * 64),
        request_body_sha256="2" * 64,
        idempotency_key=lambda _action: "3" * 64,
    )
    scenario = object.__new__(ProviderFreeE2EScenario)
    scenario._storage = _ProbeStorage(qdrant)
    scenario._qdrant = qdrant
    scenario._state = state
    scenario._counter = SimpleNamespace(read=lambda: 1)
    scenario._fixture = fixture
    scenario._adapter = _MutatingRejectedCleanup(state)
    scope = StorageScope("u", "r", "s", "a" * 64)
    with pytest.raises(E2EVerificationError, match="e2e_cleanup_probe_integrity_invalid"):
        scenario._assert_storage_residue_rejected(
            scope,
            {},
            expected_cleaned=expected,
            sealed_provider_ids=(),
        )
