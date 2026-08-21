"""Bounded evidence reads and application ports used while sealing a suite."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Protocol

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
)

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBenchmark,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    LOCOMO_EXTRACTION_OPERATION_COUNT,
    LONGMEMEVAL_EXTRACTION_OPERATION_COUNT,
    RUNNER_PAGE_SIZE,
    SchedulerAuthenticatedExtractionTerminal,
    SchedulerExtractionTerminalReadPort,
    SchedulerRunnerError,
    SchedulerSuiteSeal,
    is_sha256,
    verify_authenticated_extraction_terminal,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
)

_EXTRACTION_COUNTS = {
    SchedulerBenchmark.LOCOMO: LOCOMO_EXTRACTION_OPERATION_COUNT,
    SchedulerBenchmark.LONGMEMEVAL: LONGMEMEVAL_EXTRACTION_OPERATION_COUNT,
}


class SchedulerSuiteSealBindingPort(Protocol):
    """Optional application boundary that enriches and validates an exact seal."""

    @property
    def policy_sha256(self) -> str: ...

    def bind(self, seal: SchedulerSuiteSeal) -> SchedulerSuiteSeal: ...

    def validate(self, seal: SchedulerSuiteSeal) -> None: ...


def evaluation_summary(
    *,
    run: SchedulerRunAuthority,
    store: SQLiteDurableSchedulerStore,
) -> tuple[str, int]:
    """Stream one authenticated run into an ordered receipt root and token sum."""

    receipt_head = "0" * 64
    count = 0
    charged_tokens = 0
    after = -1
    while True:
        page = store.read_calls(after_ordinal=after, limit=RUNNER_PAGE_SIZE)
        for call in page:
            if (
                call.ordinal != count
                or call.phase is not SchedulerCallPhase.COMMITTED
                or not is_sha256(call.request_sha256)
                or not is_sha256(call.terminal_evidence_sha256)
            ):
                _fail("scheduler_runner_evaluation_incomplete")
            receipt_head = commitment(
                "runner-evaluation-receipt-link",
                {
                    "charged_tokens": call.charged_tokens,
                    "logical_call_id": call.logical_call_id,
                    "ordinal": call.ordinal,
                    "previous_receipt_sha256": receipt_head,
                    "receipt_sha256": call.terminal_evidence_sha256,
                    "request_sha256": call.request_sha256,
                    "run_authority_sha256": run.commitment_sha256,
                },
            )
            charged_tokens += call.charged_tokens
            count += 1
        if len(page) < RUNNER_PAGE_SIZE:
            break
        after = page[-1].ordinal
    if count != run.binding.profile.call_count:
        _fail("scheduler_runner_evaluation_incomplete")
    return commitment(
        "runner-evaluation-receipt-root",
        {
            "call_count": count,
            "ordered_receipt_head_sha256": receipt_head,
            "run_authority_sha256": run.commitment_sha256,
        },
    ), charged_tokens


def read_authenticated_extraction_terminals(
    *,
    suite: SchedulerSuiteAuthority,
    runs: tuple[SchedulerRunAuthority, SchedulerRunAuthority],
    authentication_secrets: tuple[bytes, bytes],
    reader: SchedulerExtractionTerminalReadPort | None,
    read_policy_sha256: str,
) -> tuple[
    SchedulerAuthenticatedExtractionTerminal,
    SchedulerAuthenticatedExtractionTerminal,
]:
    """Read and authenticate both extraction terminals without retaining receipts."""

    if reader is None:
        _fail("scheduler_runner_extraction_evidence_missing")
    observed: list[SchedulerAuthenticatedExtractionTerminal] = []
    for run, secret in zip(runs, authentication_secrets, strict=True):
        try:
            item = reader.read_terminal(run=run)
        except Exception:
            _fail("scheduler_runner_extraction_evidence_read_failed")
        if (
            type(item) is not SchedulerAuthenticatedExtractionTerminal
            or item.run_authority_sha256 != run.commitment_sha256
            or item.read_policy_sha256 != read_policy_sha256
            or not verify_authenticated_extraction_terminal(
                item,
                authentication_secret=secret,
            )
        ):
            _fail("scheduler_runner_extraction_evidence_unauthenticated")
        evidence = item.evidence
        context = evidence.context
        terminal = evidence.terminal
        try:
            ManagedFullRunExtractionContext.__post_init__(context)
            ManagedFullRunExtractionTerminal.__post_init__(terminal)
        except Exception:
            _fail("scheduler_runner_extraction_evidence_divergent")
        expected_count = _EXTRACTION_COUNTS[run.binding.profile.benchmark]
        if (
            context.profile_id != run.binding.profile.profile_id
            or context.run_id_sha256 != hashlib.sha256(run.binding.run_id.encode()).hexdigest()
            or context.binding_commitment_sha256 != run.binding.binding_commitment_sha256
            or context.methodology_commitment_sha256 != suite.methodology_sha256
            or context.runtime_binding_commitment_sha256
            != suite.bridge_boot.runtime_authority_sha256
            or context.expected_receipt_count != expected_count
            or terminal.context_commitment_sha256 != context.commitment_sha256
            or terminal.receipt_count != expected_count
        ):
            _fail("scheduler_runner_extraction_evidence_divergent")
        observed.append(item)
    return observed[0], observed[1]


def bind_suite_seal(
    seal: SchedulerSuiteSeal,
    *,
    binding: SchedulerSuiteSealBindingPort | None,
) -> SchedulerSuiteSeal:
    """Apply one optional adapter while preventing mutation of base seal evidence."""

    if binding is None:
        return seal
    try:
        bound = binding.bind(seal)
    except SchedulerRunnerError:
        raise
    except Exception:
        _fail("scheduler_runner_suite_seal_binding_failed")
    if (
        type(bound) is not SchedulerSuiteSeal
        or bound.paired_outcome is None
        or replace(bound, paired_outcome=seal.paired_outcome) != seal
    ):
        _fail("scheduler_runner_suite_seal_binding_invalid")
    return bound


def validate_suite_seal_binding(
    seal: SchedulerSuiteSeal,
    *,
    binding: SchedulerSuiteSealBindingPort | None,
) -> None:
    """Fail closed when a configured production binding is missing or divergent."""

    if binding is None:
        return
    if seal.paired_outcome is None:
        _fail("scheduler_runner_suite_seal_binding_missing")
    try:
        binding.validate(seal)
    except SchedulerRunnerError:
        raise
    except Exception:
        _fail("scheduler_runner_suite_seal_binding_invalid")


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = (
    "SchedulerSuiteSealBindingPort",
    "bind_suite_seal",
    "evaluation_summary",
    "read_authenticated_extraction_terminals",
    "validate_suite_seal_binding",
)
