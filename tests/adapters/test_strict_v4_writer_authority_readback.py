from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.strict_v4_writer_authority import _read_exact
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    build_strict_v4_writer_authority,
)

AUTH = ProjectionReceiptAuthenticator(b"strict-v4-readback-key" * 2)
WHEN = datetime(2026, 8, 11, tzinfo=UTC)


def _receipt() -> SimpleNamespace:
    context = SimpleNamespace(
        context_sha256="2" * 64,
        payload=lambda: {"context_sha256": "2" * 64},
    )
    authority = SimpleNamespace(
        terminal_commitment_sha256="3" * 64,
        payload=lambda: {"terminal_commitment_sha256": "3" * 64},
    )
    return SimpleNamespace(
        run_id_sha256="1" * 64,
        a2_context=context,
        a2_authority=authority,
        a1_authority=SimpleNamespace(terminal_commitment_sha256="8" * 64),
        expected_index_terminal_sha256="3" * 64,
        receipt_sha256="4" * 64,
        receipt_mac_sha256="5" * 64,
        registration_sha256="6" * 64,
        registration_mac_sha256="7" * 64,
        registered_at=WHEN,
        prepared_at=WHEN + timedelta(seconds=1),
        payload=lambda: {"schema_version": "strict-v4-test"},
    )


def _exact_row(receipt: SimpleNamespace) -> tuple[dict[str, object], object]:
    writer = build_strict_v4_writer_authority(
        receipt=receipt,
        authenticator=AUTH,
        sealed_at=receipt.prepared_at,
    )
    return {
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
    }, writer


def test_exact_seal_readback_accepts_the_full_durable_payload() -> None:
    receipt = _receipt()
    row, writer = _exact_row(receipt)

    assert _read_exact(row, receipt, writer) == writer


@pytest.mark.parametrize(
    ("field", "divergent"),
    [
        ("run_id_sha256", "a" * 64),
        ("context_sha256", "b" * 64),
        ("authority_terminal_sha256", "c" * 64),
        ("preparation_receipt_sha256", "d" * 64),
        ("preparation_receipt_mac_sha256", "e" * 64),
        ("writer_authority_sha256", "f" * 64),
        ("writer_authority_mac_sha256", "0" * 64),
        ("registration_sha256", "9" * 64),
        ("registration_mac_sha256", "a" * 64),
        ("provider_calls", True),
        ("paid_go_ready", True),
        ("state", "closed"),
        ("sealed_at", WHEN + timedelta(seconds=2)),
        ("closed_at", WHEN + timedelta(seconds=3)),
    ],
)
def test_seal_replay_rejects_every_divergent_scalar(
    field: str,
    divergent: object,
) -> None:
    receipt = _receipt()
    row, writer = _exact_row(receipt)
    row[field] = divergent

    with pytest.raises(ProjectionReceiptError, match="writer_authority_divergent"):
        _read_exact(row, receipt, writer)


@pytest.mark.parametrize(
    "field",
    ["preparation_receipt_json", "writer_authority_json"],
)
def test_seal_replay_rejects_divergent_json(field: str) -> None:
    receipt = _receipt()
    row, writer = _exact_row(receipt)
    row[field] = "{}"

    with pytest.raises(ProjectionReceiptError, match="writer_authority"):
        _read_exact(row, receipt, writer)
