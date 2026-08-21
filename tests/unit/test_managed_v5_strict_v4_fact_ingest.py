from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
)
from infinity_context_server import memory_comparison_managed_v5_strict_v4_fact_ingest as ingest


def test_fact_ingest_receipt_authenticates_exact_preparation_binding(monkeypatch) -> None:
    monkeypatch.setattr(
        ingest,
        "authenticate_strict_v4_preparation_receipt",
        lambda receipt, *, authenticator: None,
    )
    preparation = SimpleNamespace(
        profile_id="mem0-locomo-top50-v1",
        run_id_sha256="1" * 64,
        receipt_sha256="2" * 64,
        receipt_mac_sha256="3" * 64,
        expected_index_terminal_sha256="4" * 64,
        a2_context=SimpleNamespace(context_sha256="5" * 64),
    )
    authenticator = ProjectionReceiptAuthenticator(b"receipt-key" * 4)
    receipt = ingest.build_strict_v4_fact_ingest_receipt(
        preparation_receipt=preparation,
        authenticator=authenticator,
        corpus_count=10,
        operation_count=5_882,
        replayed_count=0,
        ordered_result_root_sha256="6" * 64,
    )
    ingest.authenticate_strict_v4_fact_ingest_receipt(
        receipt,
        authenticator=authenticator,
    )
    assert receipt.provider_calls == 0
    assert receipt.preparation_receipt_sha256 == preparation.receipt_sha256
    assert receipt.payload()["receipt_sha256"] == receipt.receipt_sha256
    with pytest.raises(ingest.StrictV4FactIngestError, match="receipt_invalid"):
        ingest.authenticate_strict_v4_fact_ingest_receipt(
            replace(receipt, replayed_count=1),
            authenticator=authenticator,
        )


def test_fact_ingest_receipt_rejects_non_hex_roots(monkeypatch) -> None:
    monkeypatch.setattr(
        ingest,
        "authenticate_strict_v4_preparation_receipt",
        lambda receipt, *, authenticator: None,
    )
    preparation = SimpleNamespace(
        profile_id="mem0-locomo-top50-v1",
        run_id_sha256="1" * 64,
        receipt_sha256="2" * 64,
        receipt_mac_sha256="3" * 64,
        expected_index_terminal_sha256="4" * 64,
        a2_context=SimpleNamespace(context_sha256="5" * 64),
    )
    with pytest.raises(ingest.StrictV4FactIngestError, match="receipt_invalid"):
        ingest.build_strict_v4_fact_ingest_receipt(
            preparation_receipt=preparation,
            authenticator=ProjectionReceiptAuthenticator(b"receipt-key" * 4),
            corpus_count=10,
            operation_count=5_882,
            replayed_count=0,
            ordered_result_root_sha256="Z" * 64,
        )


def test_fact_ingest_source_ref_uses_canonical_bounded_preview() -> None:
    source_ref = ingest._fact_source_ref("benchmark-source", "x" * 291)

    assert source_ref.source_type == "memory_comparison_benchmark"
    assert source_ref.source_id == "benchmark-source"
    assert source_ref.quote_preview == "x" * 240
