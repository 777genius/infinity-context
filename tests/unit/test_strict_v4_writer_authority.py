from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    authenticate_strict_v4_writer_authority,
    build_strict_v4_writer_authority,
)

WHEN = datetime(2026, 8, 9, tzinfo=UTC)
AUTH = ProjectionReceiptAuthenticator(b"strict-v4-writer-test-key-value" * 2)


def _receipt():
    return SimpleNamespace(
        run_id_sha256="1" * 64,
        a2_context=SimpleNamespace(context_sha256="2" * 64),
        a2_authority=SimpleNamespace(terminal_commitment_sha256="3" * 64),
        receipt_sha256="4" * 64,
        receipt_mac_sha256="5" * 64,
        registration_sha256="6" * 64,
        registration_mac_sha256="7" * 64,
        a1_authority=SimpleNamespace(terminal_commitment_sha256="8" * 64),
        expected_index_terminal_sha256="3" * 64,
        registered_at=WHEN,
        prepared_at=WHEN + timedelta(seconds=1),
    )


def test_writer_authority_requires_seal_after_full_preparation() -> None:
    receipt = _receipt()
    with pytest.raises(ProjectionReceiptError, match="writer_authority_time_invalid"):
        build_strict_v4_writer_authority(
            receipt=receipt,
            authenticator=AUTH,
            sealed_at=receipt.prepared_at - timedelta(microseconds=1),
        )

    authority = build_strict_v4_writer_authority(
        receipt=receipt,
        authenticator=AUTH,
        sealed_at=receipt.prepared_at,
    )
    authenticate_strict_v4_writer_authority(
        authority,
        expected_receipt=receipt,
        authenticator=AUTH,
    )
    assert authority.provider_calls == 0
    assert authority.paid_go_ready is False


def test_writer_authority_rejects_preparation_before_registration() -> None:
    receipt = _receipt()
    receipt.prepared_at = WHEN
    receipt.registered_at = WHEN + timedelta(seconds=1)
    with pytest.raises(ProjectionReceiptError, match="writer_authority_time_invalid"):
        build_strict_v4_writer_authority(
            receipt=receipt,
            authenticator=AUTH,
            sealed_at=WHEN + timedelta(seconds=2),
        )
