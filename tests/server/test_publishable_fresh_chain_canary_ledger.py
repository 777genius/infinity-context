"""Focused durable-ledger contracts for the exact fresh-chain canary."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from infinity_context_server.publishable_fresh_chain_canary.contracts import (
    FreshChainCallFailure,
    FreshChainLookup,
    FreshChainLookupDisposition,
    FreshChainUsage,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger import (
    FreshChainCanaryLedger,
)
from infinity_context_server.publishable_fresh_chain_canary.ledger_models import (
    FRESH_CHAIN_CASE_ID,
    FRESH_CHAIN_STAGES,
    FreshChainFailureDisposition,
    FreshChainLedgerError,
    FreshChainPlan,
    TokenUsage,
    canonical_sha256,
    fresh_chain_failed_terminal_outcome_sha256,
    provider_disposition_sha256,
)

KEY = b"operator-local-hmac-key-32bytes!"


def _digest(character: str) -> str:
    return character * 64


def _plan(**changes: object) -> FreshChainPlan:
    values = {
        "run_id": "fresh-chain-run-1",
        "namespace_id": "fresh-namespace-1",
        "namespace_commitment_sha256": _digest("a"),
        "source_commitment_sha256": _digest("b"),
        "common_condition_policy_sha256": _digest("c"),
        "commitments": {"official_case": _digest("d")},
    }
    values.update(changes)
    return FreshChainPlan(**values)  # type: ignore[arg-type]


def _ledger(tmp_path: Path) -> FreshChainCanaryLedger:
    ledger = FreshChainCanaryLedger.open(
        (tmp_path / "private" / "fresh-chain.sqlite3").absolute(),
        authentication_secret=KEY,
        plan=_plan(),
    )
    ledger.record_source_projection_bound(source_projection_commitment_sha256=_digest("4"))
    return ledger


def _source_projection(ledger: FreshChainCanaryLedger) -> str:
    value = ledger.read_snapshot().source_projection_commitment_sha256
    assert value is not None
    return value


def _intent_commitments(ledger: FreshChainCanaryLedger, stage: str) -> dict[str, str]:
    commitments = {
        "namespace_commitment_sha256": ledger.plan.namespace_commitment_sha256,
        "source_commitment_sha256": ledger.plan.source_commitment_sha256,
        "source_projection_commitment_sha256": (
            ledger.read_snapshot().source_projection_commitment_sha256
        ),
    }
    if stage == "mem0_answer":
        retrieval = ledger.read_snapshot().retrieval_handoff
        assert retrieval is not None
        commitments["retrieval_handoff_sha256"] = dict(retrieval.commitments)["handoff_sha256"]
    return commitments


def _handoff_commitments(
    ledger: FreshChainCanaryLedger,
    intent: str,
    result: str,
    receipt: str,
    *,
    memory_count: int = 2,
) -> dict[str, str]:
    retrieval_material = _digest("5")
    material = {
        "extraction_intent_sha256": intent,
        "extraction_receipt_sha256": receipt,
        "extraction_result_sha256": result,
        "memory_authority_sha256": _digest("e"),
        "memory_count": memory_count,
        "namespace_commitment_sha256": ledger.plan.namespace_commitment_sha256,
        "retrieval_authority_sha256": _digest("f"),
        "retrieval_material_sha256": retrieval_material,
        "source_commitment_sha256": ledger.plan.source_commitment_sha256,
        "source_projection_commitment_sha256": (
            ledger.read_snapshot().source_projection_commitment_sha256
        ),
    }
    return {
        "extraction_intent_sha256": intent,
        "handoff_sha256": canonical_sha256(material),
        "memory_count_sha256": canonical_sha256({"memory_count": memory_count}),
        "retrieval_material_sha256": retrieval_material,
        "source_commitment_sha256": ledger.plan.source_commitment_sha256,
        "source_projection_commitment_sha256": (
            ledger.read_snapshot().source_projection_commitment_sha256
        ),
    }


def _failure_commitments(
    ledger: FreshChainCanaryLedger,
    stage: str,
    ordinal: int,
    disposition: FreshChainFailureDisposition,
) -> dict[str, str]:
    request = ledger.read_snapshot().stages[ordinal].request_sha256
    assert request is not None
    if stage == "mem0_extraction":
        commitments = {
            key: _digest("9")
            for key in (
                "admission_commitment_sha256",
                "operation_id_sha256",
                "output_text_sha256",
                "run_identity_commitment_sha256",
                "runtime_binding_commitment_sha256",
                "scope_sha256",
                "unit_identity_sha256",
                "unit_sha256",
            )
        }
        source_projection = ledger.read_snapshot().source_projection_commitment_sha256
        assert source_projection is not None
        commitments["source_projection_commitment_sha256"] = source_projection
    else:
        commitments = {
            "bridge_intent_sha256": _digest("9"),
            "response_body_sha256": _digest("8"),
        }
    commitments["provider_disposition_sha256"] = provider_disposition_sha256(disposition)
    commitments["request_body_sha256"] = request
    return commitments


def _intent(
    ledger: FreshChainCanaryLedger,
    stage: str,
    ordinal: int,
    input_authority: str,
) -> str:
    intent = f"{ordinal + 1:x}" * 64
    ledger.record_intent(
        stage,
        intent_sha256=intent,
        request_sha256=f"{ordinal + 6:x}" * 64,
        input_authority_sha256=input_authority,
        commitments=_intent_commitments(ledger, stage),
    )
    return intent


def _success(
    ledger: FreshChainCanaryLedger,
    stage: str,
    ordinal: int,
    intent: str,
) -> tuple[str, str]:
    result = f"{ordinal + 1:x}" * 64
    receipt = f"{ordinal + 6:x}" * 64
    absence = f"{ordinal + 11:x}" * 64
    ledger.record_authenticated_pre_call_absence(
        stage,
        intent_sha256=intent,
        absence_sha256=absence,
    )
    ledger.record_dispatch_started(
        stage,
        intent_sha256=intent,
        authenticated_absence_sha256=absence,
    )
    request = ledger.read_snapshot().stages[ordinal].request_sha256
    assert request is not None
    if stage == "mem0_extraction":
        commitments = {
            key: f"{ordinal + 10:x}" * 64
            for key in (
                "admission_commitment_sha256",
                "operation_id_sha256",
                "output_text_sha256",
                "run_identity_commitment_sha256",
                "runtime_binding_commitment_sha256",
                "scope_sha256",
                "unit_identity_sha256",
                "unit_sha256",
            )
        }
        source_projection = ledger.read_snapshot().source_projection_commitment_sha256
        assert source_projection is not None
        commitments["source_projection_commitment_sha256"] = source_projection
    else:
        commitments = {
            key: f"{ordinal + 10:x}" * 64
            for key in (
                "bridge_intent_sha256",
                "encrypted_output_sha256",
                "output_text_sha256",
                "response_body_sha256",
            )
        }
    commitments["request_body_sha256"] = request
    ledger.record_success(
        stage,
        intent_sha256=intent,
        result_sha256=result,
        receipt_id=f"receipt-{ordinal}",
        receipt_sha256=receipt,
        token_usage=TokenUsage(ordinal + 1, ordinal + 2, 2 * ordinal + 3),
        commitments=commitments,
    )
    return result, receipt


def _complete_calls(ledger: FreshChainCanaryLedger) -> None:
    extraction_intent = _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
    extraction_result, extraction_receipt = _success(
        ledger, "mem0_extraction", 0, extraction_intent
    )
    ledger.record_retrieval_handoff(
        extraction_result_sha256=extraction_result,
        extraction_receipt_sha256=extraction_receipt,
        namespace_commitment_sha256=ledger.plan.namespace_commitment_sha256,
        memory_authority_sha256=_digest("e"),
        retrieval_authority_sha256=_digest("f"),
        memory_count=2,
        commitments=_handoff_commitments(
            ledger,
            extraction_intent,
            extraction_result,
            extraction_receipt,
        ),
    )
    prior_result = extraction_result
    for ordinal, stage in enumerate(FRESH_CHAIN_STAGES[1:], start=1):
        input_authority = (
            _digest("f")
            if stage == "mem0_answer"
            else prior_result
            if stage in {"infinity_judge", "mem0_judge"}
            else ledger.plan.source_commitment_sha256
        )
        intent = _intent(ledger, stage, ordinal, input_authority)
        prior_result, _receipt = _success(ledger, stage, ordinal, intent)


def _complete(ledger: FreshChainCanaryLedger) -> None:
    _complete_calls(ledger)
    ledger.record_cleanup(
        namespace_commitment_sha256=ledger.plan.namespace_commitment_sha256,
        cleanup_authority_sha256=_digest("8"),
        receipt_id="cleanup-receipt",
        receipt_sha256=_digest("0"),
        outcome_sha256=_digest("6"),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )
    snapshot = ledger.read_snapshot()
    ledger.complete(
        outcome_sha256=canonical_sha256(
            {
                "activation_evidence_only": True,
                "cleanup": snapshot.cleanup.material(),
                "ordered_receipt_ids": list(snapshot.ordered_receipt_ids),
                "plan_commitment_sha256": snapshot.plan.commitment_sha256,
                "publishable": False,
                "retrieval_handoff": snapshot.retrieval_handoff.material(),
                "source_projection_commitment_sha256": (
                    snapshot.source_projection_commitment_sha256
                ),
            }
        )
    )


def test_source_projection_is_mandatory_first_exact_and_restart_bound(
    tmp_path: Path,
) -> None:
    path = (tmp_path / "unbound" / "fresh-chain.sqlite3").absolute()
    ledger = FreshChainCanaryLedger.open(
        path,
        authentication_secret=KEY,
        plan=_plan(),
    )
    assert ledger.read_snapshot().source_projection_commitment_sha256 is None
    assert ledger.read_snapshot().next_stage is None
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_source_projection_missing",
    ):
        ledger.record_intent(
            "mem0_extraction",
            intent_sha256=_digest("1"),
            request_sha256=_digest("6"),
            input_authority_sha256=ledger.plan.source_commitment_sha256,
            commitments={
                "namespace_commitment_sha256": ledger.plan.namespace_commitment_sha256,
                "source_commitment_sha256": ledger.plan.source_commitment_sha256,
                "source_projection_commitment_sha256": _digest("4"),
            },
        )

    bound = ledger.record_source_projection_bound(source_projection_commitment_sha256=_digest("4"))
    assert bound.source_projection_commitment_sha256 == _digest("4")
    assert bound.next_stage == "mem0_extraction"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT event_kind FROM fresh_chain_events ORDER BY sequence"
        ).fetchall() == [("source_projection_bound",)]
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_source_projection_duplicate",
    ):
        ledger.record_source_projection_bound(source_projection_commitment_sha256=_digest("4"))
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_source_projection_conflict",
    ):
        ledger.record_source_projection_bound(source_projection_commitment_sha256=_digest("5"))

    reopened = FreshChainCanaryLedger.open(
        path,
        authentication_secret=KEY,
        plan=ledger.plan,
        require_existing=True,
    )
    assert reopened.read_snapshot() == bound


def test_exact_five_stage_chain_binds_handoff_usage_cleanup_and_terminal(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    assert ledger.read_snapshot().next_stage == "mem0_extraction"
    _complete(ledger)

    snapshot = ledger.read_snapshot()
    assert snapshot.plan.material()["case_id"] == FRESH_CHAIN_CASE_ID == "conv-26:qa:1"
    assert snapshot.source_projection_commitment_sha256 == _digest("4")
    assert tuple(stage.stage for stage in snapshot.stages) == FRESH_CHAIN_STAGES
    assert snapshot.ordered_completed_stages == FRESH_CHAIN_STAGES
    assert snapshot.intent_count == snapshot.result_count == snapshot.physical_attempt_count == 5
    assert snapshot.ordered_receipt_ids == tuple(f"receipt-{index}" for index in range(5))
    assert snapshot.token_usage == TokenUsage(15, 20, 35)
    assert snapshot.retrieval_handoff is not None
    assert snapshot.stages[3].input_authority_sha256 == (
        snapshot.retrieval_handoff.retrieval_authority_sha256
    )
    assert snapshot.cleanup is not None
    assert snapshot.cleanup.deleted is True
    assert snapshot.cleanup.operation_count == 1
    assert snapshot.cleanup.residual_count == 0
    assert snapshot.cleanup.material()["deleted"] is True
    assert snapshot.completed and snapshot.succeeded and snapshot.next_stage is None
    assert snapshot.material()["publishable"] is False
    assert all(stage.material()["publishable"] is False for stage in snapshot.stages)


@pytest.mark.parametrize(
    ("deleted", "operation_count", "residual_count"),
    (
        (False, 1, 0),
        (True, 0, 0),
        (True, 2, 0),
        (True, 1, 1),
        (1, 1, 0),
        (True, True, 0),
        (True, 1, False),
    ),
)
def test_cleanup_requires_exact_deleted_operation_and_residual_proof(
    tmp_path: Path,
    deleted: object,
    operation_count: object,
    residual_count: object,
) -> None:
    ledger = _ledger(tmp_path)
    _complete_calls(ledger)
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_cleanup_invalid"):
        ledger.record_cleanup(
            namespace_commitment_sha256=ledger.plan.namespace_commitment_sha256,
            cleanup_authority_sha256=_digest("8"),
            receipt_id="cleanup-receipt",
            receipt_sha256=_digest("0"),
            outcome_sha256=_digest("6"),
            deleted=deleted,  # type: ignore[arg-type]
            operation_count=operation_count,  # type: ignore[arg-type]
            residual_count=residual_count,  # type: ignore[arg-type]
        )


def test_pending_intent_requires_recovery_and_reopen_preserves_it(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    intent = _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
    ledger.record_authenticated_pre_call_absence(
        "mem0_extraction",
        intent_sha256=intent,
        absence_sha256=_digest("e"),
    )
    ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=intent,
        authenticated_absence_sha256=_digest("e"),
    )
    ledger.record_ambiguous_outcome(
        "mem0_extraction",
        intent_sha256=intent,
        ambiguity_sha256=_digest("f"),
    )

    reopened = FreshChainCanaryLedger.open(
        ledger.path,
        authentication_secret=KEY,
        plan=ledger.plan,
        require_existing=True,
    )
    snapshot = reopened.read_snapshot()
    assert snapshot.recovery_required and snapshot.next_stage is None
    assert snapshot.pending_intent is not None
    assert snapshot.pending_intent.ambiguity_sha256 == _digest("f")
    assert snapshot.pending_intent.authenticated_absence_sha256 == (_digest("e"),)


@pytest.mark.parametrize(
    ("operation", "code"),
    (
        ("unknown", "fresh_chain_stage_unknown"),
        ("out_of_order", "fresh_chain_call_out_of_order"),
        ("missing_result", "fresh_chain_call_missing_or_duplicate"),
        ("duplicate_intent", "fresh_chain_call_duplicate"),
        ("conflicting_intent", "fresh_chain_intent_replay_conflict"),
    ),
)
def test_unknown_missing_duplicate_conflict_and_order_fail_closed(
    tmp_path: Path,
    operation: str,
    code: str,
) -> None:
    ledger = _ledger(tmp_path)
    if operation == "unknown":
        action = lambda: ledger.record_intent(  # noqa: E731
            "provider_extension",
            intent_sha256=_digest("1"),
            request_sha256=_digest("2"),
            input_authority_sha256=ledger.plan.source_commitment_sha256,
        )
    elif operation == "out_of_order":
        action = lambda: ledger.record_intent(  # noqa: E731
            "infinity_answer",
            intent_sha256=_digest("1"),
            request_sha256=_digest("2"),
            input_authority_sha256=_digest("3"),
        )
    elif operation == "missing_result":
        action = lambda: ledger.record_success(  # noqa: E731
            "mem0_extraction",
            intent_sha256=_digest("1"),
            result_sha256=_digest("2"),
            receipt_id="receipt",
            receipt_sha256=_digest("3"),
            token_usage=TokenUsage(1, 1, 2),
        )
    else:
        _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
        if operation == "duplicate_intent":
            action = lambda: ledger.record_intent(  # noqa: E731
                "mem0_extraction",
                intent_sha256=_digest("1"),
                request_sha256=_digest("6"),
                input_authority_sha256=_source_projection(ledger),
                commitments=_intent_commitments(ledger, "mem0_extraction"),
            )
        else:
            action = lambda: ledger.record_intent(  # noqa: E731
                "mem0_extraction",
                intent_sha256=_digest("9"),
                request_sha256=_digest("6"),
                input_authority_sha256=_source_projection(ledger),
                commitments={"call": _digest("a")},
            )
    with pytest.raises(FreshChainLedgerError, match=code):
        action()


def test_wrong_handoff_and_mem0_answer_authority_fail_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    intent = _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
    result, receipt = _success(ledger, "mem0_extraction", 0, intent)
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_retrieval_handoff_conflict"):
        ledger.record_retrieval_handoff(
            extraction_result_sha256=_digest("9"),
            extraction_receipt_sha256=receipt,
            namespace_commitment_sha256=ledger.plan.namespace_commitment_sha256,
            memory_authority_sha256=_digest("e"),
            retrieval_authority_sha256=_digest("f"),
            memory_count=2,
            commitments=_handoff_commitments(
                ledger,
                intent,
                _digest("9"),
                receipt,
            ),
        )
    ledger.record_retrieval_handoff(
        extraction_result_sha256=result,
        extraction_receipt_sha256=receipt,
        namespace_commitment_sha256=ledger.plan.namespace_commitment_sha256,
        memory_authority_sha256=_digest("e"),
        retrieval_authority_sha256=_digest("f"),
        memory_count=2,
        commitments=_handoff_commitments(ledger, intent, result, receipt),
    )
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_infinity_source_conflict"):
        _intent(ledger, "infinity_answer", 1, _digest("9"))
    infinity_intent = _intent(
        ledger,
        "infinity_answer",
        1,
        ledger.plan.source_commitment_sha256,
    )
    infinity_result, _ = _success(ledger, "infinity_answer", 1, infinity_intent)
    judge_intent = _intent(ledger, "infinity_judge", 2, infinity_result)
    _success(ledger, "infinity_judge", 2, judge_intent)
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_mem0_retrieval_conflict"):
        _intent(ledger, "mem0_answer", 3, _digest("e"))


def test_exact_intent_result_and_handoff_commitment_schemas_fail_closed(
    tmp_path: Path,
) -> None:
    intent_ledger = _ledger(tmp_path / "intent")
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_intent_commitments_invalid",
    ):
        intent_ledger.record_intent(
            "mem0_extraction",
            intent_sha256=_digest("1"),
            request_sha256=_digest("6"),
            input_authority_sha256=_source_projection(intent_ledger),
            commitments={"generic": _digest("a")},
        )

    result_ledger = _ledger(tmp_path / "result")
    intent = _intent(
        result_ledger,
        "mem0_extraction",
        0,
        _source_projection(result_ledger),
    )
    result_ledger.record_authenticated_pre_call_absence(
        "mem0_extraction",
        intent_sha256=intent,
        absence_sha256=_digest("e"),
    )
    result_ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=intent,
        authenticated_absence_sha256=_digest("e"),
    )
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_result_commitments_invalid",
    ):
        result_ledger.record_success(
            "mem0_extraction",
            intent_sha256=intent,
            result_sha256=_digest("2"),
            receipt_id="receipt",
            receipt_sha256=_digest("3"),
            token_usage=TokenUsage(1, 1, 2),
            commitments={"generic": _digest("a")},
        )

    handoff_ledger = _ledger(tmp_path / "handoff")
    intent = _intent(
        handoff_ledger,
        "mem0_extraction",
        0,
        _source_projection(handoff_ledger),
    )
    result, receipt = _success(handoff_ledger, "mem0_extraction", 0, intent)
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_retrieval_handoff_commitments_invalid",
    ):
        handoff_ledger.record_retrieval_handoff(
            extraction_result_sha256=result,
            extraction_receipt_sha256=receipt,
            namespace_commitment_sha256=handoff_ledger.plan.namespace_commitment_sha256,
            memory_authority_sha256=_digest("e"),
            retrieval_authority_sha256=_digest("f"),
            memory_count=2,
            commitments={"generic": _digest("a")},
        )


def test_source_projection_cross_wires_fail_for_intent_result_handoff_and_failure(
    tmp_path: Path,
) -> None:
    intent_ledger = _ledger(tmp_path / "intent-projection")
    wrong_intent_commitments = _intent_commitments(
        intent_ledger,
        "mem0_extraction",
    )
    wrong_intent_commitments["source_projection_commitment_sha256"] = _digest("5")
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_intent_commitments_invalid",
    ):
        intent_ledger.record_intent(
            "mem0_extraction",
            intent_sha256=_digest("1"),
            request_sha256=_digest("6"),
            input_authority_sha256=_source_projection(intent_ledger),
            commitments=wrong_intent_commitments,
        )

    result_ledger = _ledger(tmp_path / "result-projection")
    intent = _intent(
        result_ledger,
        "mem0_extraction",
        0,
        _source_projection(result_ledger),
    )
    absence = _digest("e")
    result_ledger.record_authenticated_pre_call_absence(
        "mem0_extraction",
        intent_sha256=intent,
        absence_sha256=absence,
    )
    result_ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=intent,
        authenticated_absence_sha256=absence,
    )
    request = result_ledger.read_snapshot().stages[0].request_sha256
    assert request is not None
    wrong_result_commitments = {
        key: _digest("9")
        for key in (
            "admission_commitment_sha256",
            "operation_id_sha256",
            "output_text_sha256",
            "run_identity_commitment_sha256",
            "runtime_binding_commitment_sha256",
            "scope_sha256",
            "unit_identity_sha256",
            "unit_sha256",
        )
    }
    wrong_result_commitments.update(
        {
            "request_body_sha256": request,
            "source_projection_commitment_sha256": _digest("5"),
        }
    )
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_result_commitments_invalid",
    ):
        result_ledger.record_success(
            "mem0_extraction",
            intent_sha256=intent,
            result_sha256=_digest("2"),
            receipt_id="result-receipt",
            receipt_sha256=_digest("3"),
            token_usage=TokenUsage(1, 1, 2),
            commitments=wrong_result_commitments,
        )

    handoff_ledger = _ledger(tmp_path / "handoff-projection")
    intent = _intent(
        handoff_ledger,
        "mem0_extraction",
        0,
        _source_projection(handoff_ledger),
    )
    result, receipt = _success(handoff_ledger, "mem0_extraction", 0, intent)
    wrong_handoff_commitments = _handoff_commitments(
        handoff_ledger,
        intent,
        result,
        receipt,
    )
    wrong_handoff_commitments["source_projection_commitment_sha256"] = _digest("5")
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_retrieval_handoff_commitments_invalid",
    ):
        handoff_ledger.record_retrieval_handoff(
            extraction_result_sha256=result,
            extraction_receipt_sha256=receipt,
            namespace_commitment_sha256=handoff_ledger.plan.namespace_commitment_sha256,
            memory_authority_sha256=_digest("e"),
            retrieval_authority_sha256=_digest("f"),
            memory_count=2,
            commitments=wrong_handoff_commitments,
        )

    failure_ledger = _ledger(tmp_path / "failure-projection")
    intent = _intent(
        failure_ledger,
        "mem0_extraction",
        0,
        _source_projection(failure_ledger),
    )
    failure_ledger.record_authenticated_pre_call_absence(
        "mem0_extraction",
        intent_sha256=intent,
        absence_sha256=absence,
    )
    failure_ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=intent,
        authenticated_absence_sha256=absence,
    )
    wrong_failure_commitments = _failure_commitments(
        failure_ledger,
        "mem0_extraction",
        0,
        FreshChainFailureDisposition.REJECTED,
    )
    wrong_failure_commitments["source_projection_commitment_sha256"] = _digest("5")
    failure = FreshChainCallFailure(
        stage="mem0_extraction",
        ordinal=0,
        intent_sha256=intent,
        physical_receipt_sha256=_digest("3"),
        receipt_id="failure-receipt",
        usage=FreshChainUsage(1, 0, 1),
        provider_disposition=FreshChainFailureDisposition.REJECTED,
        transport_dispatched=True,
        commitments=wrong_failure_commitments,
    )
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_failure_commitments_invalid",
    ):
        failure_ledger.record_failure(
            "mem0_extraction",
            intent_sha256=intent,
            failure_sha256=failure.failure_sha256,
            receipt_id=failure.receipt_id,
            receipt_sha256=failure.physical_receipt_sha256,
            token_usage=TokenUsage(1, 0, 1),
            provider_disposition=failure.provider_disposition,
            commitments=wrong_failure_commitments,
        )


def test_result_without_authenticated_pre_call_absence_rejects(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    intent = _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_authenticated_absence_missing",
    ):
        ledger.record_success(
            "mem0_extraction",
            intent_sha256=intent,
            result_sha256=_digest("2"),
            receipt_id="receipt",
            receipt_sha256=_digest("3"),
            token_usage=TokenUsage(1, 1, 2),
        )


def test_dispatch_start_requires_bound_absence_and_precedes_result(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    intent = _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
    absence = _digest("e")

    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_dispatch_started_absence_missing",
    ):
        ledger.record_dispatch_started(
            "mem0_extraction",
            intent_sha256=intent,
            authenticated_absence_sha256=absence,
        )

    ledger.record_authenticated_pre_call_absence(
        "mem0_extraction",
        intent_sha256=intent,
        absence_sha256=absence,
    )
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_dispatch_started_missing",
    ):
        ledger.record_success(
            "mem0_extraction",
            intent_sha256=intent,
            result_sha256=_digest("2"),
            receipt_id="receipt",
            receipt_sha256=_digest("3"),
            token_usage=TokenUsage(1, 1, 2),
        )

    snapshot = ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=intent,
        authenticated_absence_sha256=absence,
    )
    assert snapshot.pending_intent is not None
    assert snapshot.pending_intent.dispatch_started_sha256 is not None
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_dispatch_started_duplicate",
    ):
        ledger.record_dispatch_started(
            "mem0_extraction",
            intent_sha256=intent,
            authenticated_absence_sha256=absence,
        )


def test_tamper_replay_conflict_and_completed_replay_are_fail_closed(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _complete(ledger)

    reopened = FreshChainCanaryLedger.open(
        ledger.path,
        authentication_secret=KEY,
        plan=ledger.plan,
        require_existing=True,
    )
    assert reopened.read_snapshot().completed
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_terminal"):
        reopened.record_intent(
            "mem0_extraction",
            intent_sha256=_digest("f"),
            request_sha256=_digest("e"),
            input_authority_sha256=ledger.plan.source_commitment_sha256,
        )
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_replay_conflict"):
        FreshChainCanaryLedger.open(
            ledger.path,
            authentication_secret=KEY,
            plan=_plan(run_id="divergent-run"),
            require_existing=True,
        )

    with sqlite3.connect(ledger.path) as connection:
        connection.execute("UPDATE fresh_chain_events SET payload_json = '{}' WHERE sequence = 1")
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_corrupt"):
        reopened.read_snapshot()


def test_failed_receipt_requires_cleanup_and_failed_terminal(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    intent = _intent(ledger, "mem0_extraction", 0, _source_projection(ledger))
    ledger.record_authenticated_pre_call_absence(
        "mem0_extraction",
        intent_sha256=intent,
        absence_sha256=_digest("e"),
    )
    ledger.record_dispatch_started(
        "mem0_extraction",
        intent_sha256=intent,
        authenticated_absence_sha256=_digest("e"),
    )
    failure = FreshChainCallFailure(
        stage="mem0_extraction",
        ordinal=0,
        intent_sha256=intent,
        physical_receipt_sha256=_digest("3"),
        receipt_id="failed-receipt",
        usage=FreshChainUsage(4, 0, 4),
        provider_disposition=FreshChainFailureDisposition.PROVIDER_FAILED,
        transport_dispatched=True,
        commitments=_failure_commitments(
            ledger,
            "mem0_extraction",
            0,
            FreshChainFailureDisposition.PROVIDER_FAILED,
        ),
    )
    lookup = FreshChainLookup(
        FreshChainLookupDisposition.FAILED,
        intent,
        failure=failure,
    )
    assert lookup.failure is failure
    snapshot = ledger.record_failure(
        "mem0_extraction",
        intent_sha256=intent,
        failure_sha256=failure.failure_sha256,
        receipt_id=failure.receipt_id,
        receipt_sha256=failure.physical_receipt_sha256,
        token_usage=TokenUsage(4, 0, 4),
        provider_disposition=failure.provider_disposition,
        commitments=failure.commitments,
    )
    assert snapshot.physical_attempt_count == 1
    assert snapshot.stages[0].status == "failed"
    assert snapshot.stages[0].result_sha256 is None
    assert snapshot.stages[0].failure_sha256 == failure.failure_sha256
    assert snapshot.stages[0].provider_disposition == "provider_failed"
    assert snapshot.stages[0].material()["failure"] == {
        "sha256": failure.failure_sha256,
        "provider_disposition": "provider_failed",
        "commitments": dict(failure.commitments),
        "publishable": False,
    }
    with pytest.raises(FreshChainLedgerError, match="fresh_chain_ledger_failed"):
        _intent(ledger, "infinity_answer", 1, _digest("9"))
    ledger.record_cleanup(
        namespace_commitment_sha256=ledger.plan.namespace_commitment_sha256,
        cleanup_authority_sha256=_digest("4"),
        receipt_id="cleanup-receipt",
        receipt_sha256=_digest("5"),
        outcome_sha256=_digest("6"),
        deleted=True,
        operation_count=1,
        residual_count=0,
    )
    before_terminal = ledger.read_snapshot()
    assert before_terminal.cleanup is not None
    expected_terminal = fresh_chain_failed_terminal_outcome_sha256(
        plan=before_terminal.plan,
        source_projection_commitment_sha256=(before_terminal.source_projection_commitment_sha256),
        stages=before_terminal.stages,
        retrieval_handoff=before_terminal.retrieval_handoff,
        cleanup=before_terminal.cleanup,
    )
    with pytest.raises(
        FreshChainLedgerError,
        match="fresh_chain_terminal_outcome_conflict",
    ):
        ledger.terminate_failed(outcome_sha256=_digest("7"))
    snapshot = ledger.terminate_failed()
    assert snapshot.completed and not snapshot.succeeded
    assert snapshot.terminal_outcome is not None
    assert snapshot.terminal_outcome.outcome_sha256 == expected_terminal
    assert snapshot.material()["publishable"] is False

    reopened = FreshChainCanaryLedger.open(
        ledger.path,
        authentication_secret=KEY,
        plan=ledger.plan,
        require_existing=True,
    )
    assert reopened.read_snapshot() == snapshot
