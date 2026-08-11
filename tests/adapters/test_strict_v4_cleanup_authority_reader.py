from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.strict_v4_cleanup_authority import (
    _REGISTRATION_SQL,
    _WRITER_SQL,
    CLEANUP_READBACK_CAPABILITY_ERROR,
    AsyncPostgresStrictV4CleanupAuthorityReader,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_SEALER_ROLE,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    build_strict_v4_writer_authority,
)

PREP_AUTH = ProjectionReceiptAuthenticator(b"preparation-reader-test-key" * 2)
READBACK_AUTH = ProjectionReceiptAuthenticator(b"cleanup-reader-test-key" * 2)
WHEN = datetime(2026, 8, 9, tzinfo=UTC)


class _AlternateReadbackAuthenticator:
    def __init__(self, delegate: ProjectionReceiptAuthenticator) -> None:
        self._delegate = delegate
        self.calls: list[tuple[str, str]] = []

    @property
    def authority_sha256(self) -> str:
        return self._delegate.authority_sha256

    def sign(self, domain: str, payload_sha256: str) -> str:
        self.calls.append((domain, payload_sha256))
        return self._delegate.sign(domain, payload_sha256)


class _VerifyOnlyReadbackAuthenticator:
    authority_sha256 = READBACK_AUTH.authority_sha256

    def verify(self, _domain: str, _payload_sha256: str, _mac_sha256: str) -> bool:
        return True


class _Transaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def start(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _Connection:
    def __init__(self, registration, writer) -> None:
        self.registration = registration
        self.writer = writer
        self.tx = _Transaction()
        self.closed = False
        self.events: list[str] = []

    def transaction(self, **kwargs):
        self.events.append("transaction")
        assert kwargs == {"isolation": "repeatable_read", "readonly": True}
        return self.tx

    async def fetch(self, sql, *_args):
        self.events.append("read")
        if "memory_cleanup_v3_context_authorities" in sql:
            return [self.registration]
        return [self.writer]

    async def close(self) -> None:
        self.events.append("close")
        self.closed = True


def _receipt():
    context_payload = {"context_sha256": "2" * 64, "scope": "strict-v4"}
    authority_payload = {
        "terminal_commitment_sha256": "3" * 64,
        "ordered_page_sha256": ["9" * 64],
    }
    return SimpleNamespace(
        run_id_sha256="1" * 64,
        a2_context=SimpleNamespace(context_sha256="2" * 64, payload=lambda: context_payload),
        a2_authority=SimpleNamespace(
            terminal_commitment_sha256="3" * 64, payload=lambda: authority_payload
        ),
        a1_authority=SimpleNamespace(terminal_commitment_sha256="8" * 64),
        expected_index_terminal_sha256="3" * 64,
        receipt_sha256="4" * 64,
        receipt_mac_sha256="5" * 64,
        registration_sha256="6" * 64,
        registration_mac_sha256="7" * 64,
        registered_at=WHEN,
        prepared_at=WHEN + timedelta(seconds=1),
        payload=lambda: {"schema_version": "test", "receipt_sha256": "4" * 64},
    )


def _rows(receipt):
    writer = build_strict_v4_writer_authority(
        receipt=receipt,
        authenticator=PREP_AUTH,
        sealed_at=receipt.prepared_at,
    )
    registration = {
        "run_id_sha256": receipt.run_id_sha256,
        "context_sha256": receipt.a2_context.context_sha256,
        "authority_terminal_sha256": receipt.a2_authority.terminal_commitment_sha256,
        "context_json": json.dumps(receipt.a2_context.payload()),
        "authority_json": json.dumps(receipt.a2_authority.payload()),
        "registration_sha256": receipt.registration_sha256,
        "registration_mac_sha256": receipt.registration_mac_sha256,
        "registered_at": receipt.registered_at,
    }
    writer_row = {
        "run_id_sha256": receipt.run_id_sha256,
        "context_sha256": receipt.a2_context.context_sha256,
        "authority_terminal_sha256": receipt.a2_authority.terminal_commitment_sha256,
        "preparation_receipt_json": json.dumps(receipt.payload()),
        "preparation_receipt_sha256": receipt.receipt_sha256,
        "preparation_receipt_mac_sha256": receipt.receipt_mac_sha256,
        "writer_authority_json": json.dumps(writer.payload()),
        "writer_authority_sha256": writer.writer_authority_sha256,
        "writer_authority_mac_sha256": writer.writer_authority_mac_sha256,
        "registration_sha256": receipt.registration_sha256,
        "registration_mac_sha256": receipt.registration_mac_sha256,
        "provider_calls": 0,
        "paid_go_ready": False,
        "state": "sealed",
        "sealed_at": writer.sealed_at,
        "closed_at": None,
    }
    return registration, writer_row, writer


def _read(
    receipt,
    registration,
    writer_row,
    monkeypatch,
    readback_authenticator=READBACK_AUTH,
):
    monkeypatch.setattr(
        "infinity_context_adapters.postgres.strict_v4_cleanup_authority."
        "authenticate_strict_v4_preparation_receipt",
        lambda *_args, **_kwargs: None,
    )
    connection = _Connection(registration, writer_row)

    async def assert_capability(observed, *, capability_role, error_code):
        assert observed is connection
        assert capability_role == STRICT_V4_SEALER_ROLE
        assert error_code == CLEANUP_READBACK_CAPABILITY_ERROR
        connection.events.append("capability")

    monkeypatch.setattr(
        "infinity_context_adapters.postgres.strict_v4_cleanup_authority."
        "assert_strict_v4_runtime_capability",
        assert_capability,
    )
    recovery_calls = 0

    async def recover():
        nonlocal recovery_calls
        recovery_calls += 1
        return receipt

    async def connect():
        return connection

    readback = asyncio.run(
        AsyncPostgresStrictV4CleanupAuthorityReader(
            connect=connect,
            recover_preparation=recover,
            preparation_authenticator=PREP_AUTH,
            readback_authenticator=readback_authenticator,
            authentication_key_id="cleanup-key",
        ).read_registered_strict_v4(receipt.run_id_sha256)
    )
    return readback, connection, recovery_calls


def test_reader_binds_recovered_receipt_registration_and_sealed_writer(monkeypatch) -> None:
    receipt = _receipt()
    registration, writer_row, writer = _rows(receipt)
    readback, connection, recovery_calls = _read(receipt, registration, writer_row, monkeypatch)

    assert readback is not None
    assert readback.preparation_receipt_sha256 == receipt.receipt_sha256
    assert readback.registration_mac_sha256 == receipt.registration_mac_sha256
    assert readback.writer_authority_sha256 == writer.writer_authority_sha256
    assert recovery_calls == 1
    assert connection.tx.committed and connection.closed
    assert connection.events == ["capability", "transaction", "read", "read", "close"]


def test_reader_accepts_structural_readback_authenticator(monkeypatch) -> None:
    receipt = _receipt()
    registration, writer_row, _writer = _rows(receipt)
    alternate = _AlternateReadbackAuthenticator(READBACK_AUTH)

    readback, connection, recovery_calls = _read(
        receipt,
        registration,
        writer_row,
        monkeypatch,
        readback_authenticator=alternate,
    )

    assert readback is not None
    assert readback.authentication_authority_sha256 == READBACK_AUTH.authority_sha256
    assert alternate.calls == [("strict-v4-cleanup-authority-readback", readback.readback_sha256)]
    assert recovery_calls == 1
    assert connection.tx.committed and connection.closed


def test_reader_rejects_nonconforming_readback_authenticator_at_composition() -> None:
    async def unused():
        raise AssertionError("invalid authentication reached production I/O")

    with pytest.raises(ProjectionReceiptError, match="cleanup_readback_capability_invalid"):
        AsyncPostgresStrictV4CleanupAuthorityReader(
            connect=unused,
            recover_preparation=unused,
            preparation_authenticator=PREP_AUTH,
            readback_authenticator=_VerifyOnlyReadbackAuthenticator(),  # type: ignore[arg-type]
            authentication_key_id="cleanup-key",
        )


def test_reader_rejects_post_seal_registration_timestamp_tamper(monkeypatch) -> None:
    receipt = _receipt()
    registration, writer_row, _writer = _rows(receipt)
    registration["registered_at"] = receipt.registered_at + timedelta(microseconds=1)

    with pytest.raises(ProjectionReceiptError, match="registration_invalid"):
        _read(receipt, registration, writer_row, monkeypatch)


def test_reader_rejects_divergent_writer_sealed_timestamp(monkeypatch) -> None:
    receipt = _receipt()
    registration, writer_row, _writer = _rows(receipt)
    writer_row["sealed_at"] = receipt.prepared_at + timedelta(microseconds=1)

    with pytest.raises(ProjectionReceiptError, match="writer_invalid"):
        _read(receipt, registration, writer_row, monkeypatch)


def test_reader_sql_is_immune_to_hostile_search_path_shadow_relations() -> None:
    assert "FROM public.memory_cleanup_v3_context_authorities" in _REGISTRATION_SQL
    assert "FROM public.memory_comparison_strict_v4_preparations" in _WRITER_SQL


def test_reader_role_preflight_fails_before_transaction_and_always_closes(monkeypatch) -> None:
    receipt = _receipt()
    registration, writer_row, _writer = _rows(receipt)
    connection = _Connection(registration, writer_row)
    monkeypatch.setattr(
        "infinity_context_adapters.postgres.strict_v4_cleanup_authority."
        "authenticate_strict_v4_preparation_receipt",
        lambda *_args, **_kwargs: None,
    )

    async def reject_capability(observed, *, capability_role, error_code):
        assert observed is connection
        assert capability_role == STRICT_V4_SEALER_ROLE
        assert error_code == CLEANUP_READBACK_CAPABILITY_ERROR
        connection.events.append("capability")
        raise ProjectionReceiptError(error_code)

    async def recover():
        return receipt

    async def connect():
        return connection

    monkeypatch.setattr(
        "infinity_context_adapters.postgres.strict_v4_cleanup_authority."
        "assert_strict_v4_runtime_capability",
        reject_capability,
    )
    reader = AsyncPostgresStrictV4CleanupAuthorityReader(
        connect=connect,
        recover_preparation=recover,
        preparation_authenticator=PREP_AUTH,
        readback_authenticator=READBACK_AUTH,
        authentication_key_id="cleanup-key",
    )

    with pytest.raises(ProjectionReceiptError, match=f"^{CLEANUP_READBACK_CAPABILITY_ERROR}$"):
        asyncio.run(reader.read_registered_strict_v4(receipt.run_id_sha256))

    assert connection.closed is True
    assert connection.events == ["capability", "close"]
    assert connection.tx.committed is False
    assert connection.tx.rolled_back is False
