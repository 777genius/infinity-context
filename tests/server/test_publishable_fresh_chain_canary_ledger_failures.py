"""Failure-shape and HMAC corruption tests split from the core ledger suite."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCallFailure,
    FreshChainCanaryError,
    FreshChainLookup,
    FreshChainLookupDisposition,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger import (
    FreshChainCanaryLedger,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FreshChainFailureDisposition,
    FreshChainLedgerError,
    TokenUsage,
    provider_disposition_sha256,
)
from test_publishable_fresh_chain_canary_ledger import (
    _digest,
    _failure_commitments,
    _intent,
    _ledger,
    _source_projection,
)


def test_failure_contract_and_ledger_reject_unknown_missing_tampered_and_duplicate(
    tmp_path: Path,
) -> None:
    intent = _digest("1")
    commitments = {
        "bridge_intent_sha256": _digest("2"),
        "provider_disposition_sha256": provider_disposition_sha256("rejected"),
        "request_body_sha256": _digest("6"),
        "response_body_sha256": _digest("3"),
    }
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_failure_disposition_invalid"):
        FreshChainCallFailure(
            stage="infinity_answer",
            ordinal=1,
            intent_sha256=intent,
            physical_receipt_sha256=_digest("4"),
            receipt_id="failed-receipt",
            usage=FreshChainUsage(1, 2, 3),
            provider_disposition="unknown",
            transport_dispatched=False,
            commitments=commitments,
        )
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_failure_invalid"):
        FreshChainCallFailure(
            stage="infinity_answer",
            ordinal=1,
            intent_sha256=intent,
            physical_receipt_sha256=_digest("4"),
            receipt_id="failed-receipt",
            usage=FreshChainUsage(1, 2, 3),
            provider_disposition="rejected",
            transport_dispatched=False,
            commitments={"provider_disposition_sha256": commitments["provider_disposition_sha256"]},
        )
    with pytest.raises(FreshChainCanaryError, match="fresh_chain_lookup_invalid"):
        FreshChainLookup(FreshChainLookupDisposition.FAILED, intent)

    ledger = _ledger(tmp_path)
    extraction_intent = _intent(
        ledger,
        "mem0_extraction",
        0,
        _source_projection(ledger),
    )
    absence = _digest("e")
    ledger.record_authenticated_pre_call_absence(
        "mem0_extraction", intent_sha256=extraction_intent, absence_sha256=absence
    )
    ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=extraction_intent,
        authenticated_absence_sha256=absence,
    )
    exact_commitments = _failure_commitments(
        ledger,
        "mem0_extraction",
        0,
        FreshChainFailureDisposition.REJECTED,
    )
    failure = FreshChainCallFailure(
        stage="mem0_extraction",
        ordinal=0,
        intent_sha256=extraction_intent,
        physical_receipt_sha256=_digest("3"),
        receipt_id="failed-receipt",
        usage=FreshChainUsage(1, 2, 3),
        provider_disposition="rejected",
        transport_dispatched=False,
        commitments=exact_commitments,
    )
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_failure_binding_invalid"):
        ledger.record_failure(
            "mem0_extraction",
            intent_sha256=extraction_intent,
            failure_sha256=_digest("2"),
            receipt_id=failure.receipt_id,
            receipt_sha256=failure.physical_receipt_sha256,
            token_usage=TokenUsage(1, 2, 3),
            provider_disposition=failure.provider_disposition,
            commitments=exact_commitments,
        )
    ledger.record_failure(
        "mem0_extraction",
        intent_sha256=extraction_intent,
        failure_sha256=failure.failure_sha256,
        receipt_id=failure.receipt_id,
        receipt_sha256=failure.physical_receipt_sha256,
        token_usage=TokenUsage(1, 2, 3),
        provider_disposition=failure.provider_disposition,
        commitments=exact_commitments,
    )
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_call_duplicate"):
        ledger.record_failure(
            "mem0_extraction",
            intent_sha256=extraction_intent,
            failure_sha256=failure.failure_sha256,
            receipt_id=failure.receipt_id,
            receipt_sha256=failure.physical_receipt_sha256,
            token_usage=TokenUsage(1, 2, 3),
            provider_disposition=failure.provider_disposition,
            commitments=exact_commitments,
        )


def test_wrong_operator_hmac_and_head_tamper_reject(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_corrupt"):
        FreshChainCanaryLedger.open(
            ledger.path,
            authentication_secret=b"wrong-operator-local-hmac-key!!!",
            plan=ledger.plan,
            require_existing=True,
        )
    with sqlite3.connect(ledger.path) as connection:
        connection.execute(
            "UPDATE fresh_chain_head SET event_head_hmac = ? WHERE singleton = 1",
            (_digest("f"),),
        )
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_corrupt"):
        ledger.read_snapshot()


def test_ledger_rejects_hardlinks_and_path_inode_swaps(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    hardlink = ledger.path.with_name("hardlinked-ledger.sqlite3")
    os.link(ledger.path, hardlink)
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_ledger_private_storage_invalid",
    ):
        ledger.read_snapshot()
    hardlink.unlink()

    displaced = ledger.path.with_name("displaced-ledger.sqlite3")
    ledger.path.rename(displaced)
    shutil.copyfile(displaced, ledger.path)
    ledger.path.chmod(0o600)
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_ledger_private_storage_invalid",
    ):
        ledger.read_snapshot()
