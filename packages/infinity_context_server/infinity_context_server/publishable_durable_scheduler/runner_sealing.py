"""Bounded evaluation receipt-root calculation for suite sealing."""

from __future__ import annotations

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerRunAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    RUNNER_PAGE_SIZE,
    SchedulerRunnerError,
    is_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
)


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


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = ("evaluation_summary",)
