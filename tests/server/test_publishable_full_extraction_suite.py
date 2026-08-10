"""O(1) synthetic terminal tests for publishable extraction suite readback."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pytest
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
    PublishableExtractionSuiteError,
    read_publishable_full_extraction_suite,
)
from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableExtractionRunTerminal,
)


def _sha(value: object) -> str:
    return hashlib.sha256(str(value).encode("ascii")).hexdigest()


def _terminal(
    profile_id: str,
    receipt_count: int,
    seed: str,
    *,
    run_id_sha256: str | None = None,
) -> PublishableExtractionRunTerminal:
    context = ManagedFullRunExtractionContext(
        profile_id=profile_id,
        run_id_sha256=run_id_sha256 or _sha(f"{seed}:run"),
        binding_commitment_sha256=_sha(f"{seed}:binding"),
        methodology_commitment_sha256=_sha("shared-methodology"),
        admission_commitment_sha256=_sha(f"{seed}:admission"),
        ingestion_root_sha256=_sha(f"{seed}:ingestion"),
        a1_terminal_commitment_sha256=_sha(f"{seed}:a1-terminal"),
        a1_manifest_context_sha256=_sha(f"{seed}:a1-context"),
        runtime_binding_commitment_sha256=_sha("shared-runtime-binding"),
        expected_receipt_count=receipt_count,
    )
    ledger_body = {
        "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
        "context_commitment_sha256": context.commitment_sha256,
        "receipt_count": receipt_count,
        "page_count": (receipt_count + FULL_RUN_EXTRACTION_PAGE_SIZE - 1)
        // FULL_RUN_EXTRACTION_PAGE_SIZE,
        "receipt_pages_root_sha256": _sha(f"{seed}:receipt-pages"),
        "usage": {
            "prompt_tokens": receipt_count * 2,
            "completion_tokens": receipt_count,
            "total_tokens": receipt_count * 3,
        },
    }
    ledger = ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=receipt_count,
        page_count=int(ledger_body["page_count"]),
        receipt_pages_root_sha256=str(ledger_body["receipt_pages_root_sha256"]),
        prompt_tokens=receipt_count * 2,
        completion_tokens=receipt_count,
        total_tokens=receipt_count * 3,
        terminal_commitment_sha256=canonical_sha256(ledger_body),
    )
    return PublishableExtractionRunTerminal(
        profile_id=context.profile_id,
        run_id_sha256=context.run_id_sha256,
        binding_commitment_sha256=context.binding_commitment_sha256,
        methodology_commitment_sha256=context.methodology_commitment_sha256,
        admission_commitment_sha256=context.admission_commitment_sha256,
        ingestion_root_sha256=context.ingestion_root_sha256,
        a1_terminal_commitment_sha256=context.a1_terminal_commitment_sha256,
        a1_manifest_context_sha256=context.a1_manifest_context_sha256,
        runtime_binding_commitment_sha256=(context.runtime_binding_commitment_sha256),
        preparation_receipt_sha256=_sha(f"{seed}:preparation"),
        dataset_sha256=_sha(f"{seed}:dataset"),
        a2_terminal_commitment_sha256=_sha(f"{seed}:a2-terminal"),
        expected_receipt_count=receipt_count,
        journal_manifest_commitment_sha256=_sha(f"{seed}:journal-manifest"),
        journal_state_commitment_sha256=_sha(f"{seed}:journal-state"),
        journal_head_event_sha256=_sha(f"{seed}:journal-head"),
        ledger_terminal=ledger,
    )


@dataclass
class _Reader:
    terminal: PublishableExtractionRunTerminal | None
    calls: int = 0

    def read_terminal(self) -> PublishableExtractionRunTerminal | None:
        self.calls += 1
        return self.terminal


def _exact_terminals() -> tuple[
    PublishableExtractionRunTerminal,
    PublishableExtractionRunTerminal,
]:
    return (
        _terminal("mem0-locomo-top50-v1", 5_882, "locomo"),
        _terminal("mem0-longmemeval-top50-v1", 124_344, "longmemeval"),
    )


def test_exact_synthetic_terminal_counts_are_accepted_without_dataset_materialization() -> None:
    locomo, longmemeval = _exact_terminals()
    locomo_reader = _Reader(locomo)
    longmemeval_reader = _Reader(longmemeval)

    readback = read_publishable_full_extraction_suite(
        locomo_reader=locomo_reader,
        longmemeval_reader=longmemeval_reader,
    )

    assert PUBLISHABLE_EXTRACTION_BENCHMARKS == (
        ("mem0-locomo-top50-v1", 5_882),
        ("mem0-longmemeval-top50-v1", 124_344),
    )
    assert PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT == 130_226
    assert readback.body()["ordered_expected_receipt_count"] == [5_882, 124_344]
    assert readback.body()["total_expected_receipt_count"] == 130_226
    assert locomo_reader.calls == longmemeval_reader.calls == 1
    assert readback.global_publishable is False
    assert readback.paid_go_ready is False
    assert locomo.paid_go_ready is longmemeval.paid_go_ready is False
    assert readback.locomo_answer_judge_handoff.paid_go_ready is False
    assert readback.longmemeval_answer_judge_handoff.paid_go_ready is False
    assert (
        readback.locomo_answer_judge_handoff.suite_readback_commitment_sha256
        == readback.suite_readback_commitment_sha256
        == readback.longmemeval_answer_judge_handoff.suite_readback_commitment_sha256
    )


@pytest.mark.parametrize("missing", ["locomo", "longmemeval"])
def test_missing_terminal_evidence_rejects(missing: str) -> None:
    locomo, longmemeval = _exact_terminals()
    locomo_reader = _Reader(None if missing == "locomo" else locomo)
    longmemeval_reader = _Reader(None if missing == "longmemeval" else longmemeval)

    with pytest.raises(
        PublishableExtractionSuiteError,
        match="extraction_suite_terminal_missing",
    ):
        read_publishable_full_extraction_suite(
            locomo_reader=locomo_reader,
            longmemeval_reader=longmemeval_reader,
        )
    assert locomo_reader.calls == longmemeval_reader.calls == 1


def test_wrong_profile_count_and_swapped_evidence_reject() -> None:
    locomo, longmemeval = _exact_terminals()
    wrong_count = _terminal("mem0-locomo-top50-v1", 5_881, "wrong-count")
    for first, second in ((wrong_count, longmemeval), (longmemeval, locomo)):
        with pytest.raises(
            PublishableExtractionSuiteError,
            match="extraction_suite_terminal_invalid",
        ):
            read_publishable_full_extraction_suite(
                locomo_reader=_Reader(first),
                longmemeval_reader=_Reader(second),
            )


def test_duplicate_run_and_forged_nested_ledger_evidence_reject() -> None:
    locomo, _ = _exact_terminals()
    duplicate_run = _terminal(
        "mem0-longmemeval-top50-v1",
        124_344,
        "duplicate-run",
        run_id_sha256=locomo.run_id_sha256,
    )
    with pytest.raises(
        PublishableExtractionSuiteError,
        match="extraction_suite_cross_wire",
    ):
        read_publishable_full_extraction_suite(
            locomo_reader=_Reader(locomo),
            longmemeval_reader=_Reader(duplicate_run),
        )

    forged = _terminal(
        "mem0-longmemeval-top50-v1",
        124_344,
        "forged-ledger",
    )
    ledger = forged.ledger_terminal
    object.__setattr__(ledger, "page_count", ledger.page_count + 1)
    object.__setattr__(
        ledger,
        "terminal_commitment_sha256",
        canonical_sha256(ledger.body()),
    )
    object.__setattr__(
        forged,
        "terminal_commitment_sha256",
        canonical_sha256(forged.body()),
    )
    with pytest.raises(
        PublishableExtractionSuiteError,
        match="extraction_suite_terminal_invalid",
    ):
        read_publishable_full_extraction_suite(
            locomo_reader=_Reader(locomo),
            longmemeval_reader=_Reader(forged),
        )
