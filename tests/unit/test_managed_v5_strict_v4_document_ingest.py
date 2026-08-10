from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
)
from infinity_context_server import (
    memory_comparison_managed_v5_strict_v4_document_ingest as ingest,
)


def _preparation() -> SimpleNamespace:
    return SimpleNamespace(
        profile_id="mem0-longmemeval-top50-v1",
        run_id_sha256="1" * 64,
        receipt_sha256="2" * 64,
        receipt_mac_sha256="3" * 64,
        expected_index_terminal_sha256="4" * 64,
        a2_context=SimpleNamespace(context_sha256="5" * 64),
    )


def test_document_ingest_receipt_authenticates_exact_preparation_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingest,
        "authenticate_strict_v4_preparation_receipt",
        lambda receipt, *, authenticator: None,
    )
    preparation = _preparation()
    authenticator = ProjectionReceiptAuthenticator(b"receipt-key" * 4)
    receipt = ingest.build_strict_v4_document_ingest_receipt(
        preparation_receipt=preparation,
        authenticator=authenticator,
        corpus_count=500,
        document_count=124_344,
        chunk_count=366_440,
        replayed_count=0,
        ordered_result_root_sha256="6" * 64,
    )

    ingest.authenticate_strict_v4_document_ingest_receipt(
        receipt,
        authenticator=authenticator,
    )

    assert receipt.provider_calls == 0
    assert receipt.preparation_receipt_sha256 == preparation.receipt_sha256
    assert receipt.payload()["receipt_sha256"] == receipt.receipt_sha256
    with pytest.raises(ingest.StrictV4DocumentIngestError, match="receipt_invalid"):
        ingest.authenticate_strict_v4_document_ingest_receipt(
            replace(receipt, chunk_count=receipt.chunk_count + 1),
            authenticator=authenticator,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordered_result_root_sha256", "Z" * 64),
        ("provider_calls", 1),
        ("chunk_count", 124_343),
        ("replayed_count", 124_345),
    ],
)
def test_document_ingest_receipt_rejects_invalid_material(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setattr(
        ingest,
        "authenticate_strict_v4_preparation_receipt",
        lambda receipt, *, authenticator: None,
    )
    values = {
        "preparation_receipt": _preparation(),
        "authenticator": ProjectionReceiptAuthenticator(b"receipt-key" * 4),
        "corpus_count": 500,
        "document_count": 124_344,
        "chunk_count": 366_440,
        "replayed_count": 0,
        "ordered_result_root_sha256": "6" * 64,
    }
    if field == "provider_calls":
        with pytest.raises(TypeError):
            ingest.build_strict_v4_document_ingest_receipt(**values, provider_calls=value)
        return
    values[field] = value
    with pytest.raises(ingest.StrictV4DocumentIngestError, match="receipt_invalid"):
        ingest.build_strict_v4_document_ingest_receipt(**values)


def test_document_ingest_root_is_order_and_identity_sensitive() -> None:
    first = ingest._extend_root(
        b"0" * 32,
        0,
        "source-1",
        "document-1",
        ("chunk-1", "chunk-2"),
    )
    replay = ingest._extend_root(
        b"0" * 32,
        0,
        "source-1",
        "document-1",
        ("chunk-1", "chunk-2"),
    )
    reordered = ingest._extend_root(
        b"0" * 32,
        0,
        "source-1",
        "document-1",
        ("chunk-2", "chunk-1"),
    )

    assert first == replay
    assert first != reordered
