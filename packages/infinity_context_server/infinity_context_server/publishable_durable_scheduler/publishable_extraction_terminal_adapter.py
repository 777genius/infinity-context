"""Authenticate sealed extraction-suite terminals for the durable scheduler."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from typing import final

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)

from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA,
    PublishableExtractionRunTerminal,
)
from infinity_context_server.processes.publishable_full_extraction_suite import (
    PUBLISHABLE_EXTRACTION_BENCHMARKS,
    PUBLISHABLE_EXTRACTION_SUITE_SCHEMA,
    PublishableExtractionSuiteReadback,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    commitment,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SchedulerAuthenticatedExtractionTerminal,
    SchedulerExtractionTerminalEvidence,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    authenticate_extraction_terminal,
)
from infinity_context_server.publishable_durable_scheduler.runner_suite_binding import (
    require_exact_suite,
)

_READ_POLICY_SCHEMA = "publishable-extraction-suite-scheduler-read-policy.v2"
PUBLISHABLE_EXTRACTION_SUITE_TERMINAL_READ_POLICY_SHA256 = commitment(
    "extraction-suite-terminal-read-policy",
    {
        "authentication": "hmac-sha256-per-run-store",
        "ordered_benchmarks": [
            {"expected_receipt_count": count, "profile_id": profile_id}
            for profile_id, count in PUBLISHABLE_EXTRACTION_BENCHMARKS
        ],
        "policy_schema_version": _READ_POLICY_SCHEMA,
        "runtime_projection": "authenticated-phase-c-to-scheduler-bridge-v1",
        "source_schema_version": PUBLISHABLE_EXTRACTION_SUITE_SCHEMA,
        "source_terminal_schema_version": PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA,
        "validated_bindings": [
            "profile_id",
            "run_id_sha256",
            "binding_commitment_sha256",
            "dataset_sha256",
            "methodology_commitment_sha256",
            "runtime_binding_commitment_sha256",
            "scheduler_bridge_runtime_authority_sha256",
            "expected_receipt_count",
            "ledger_context_commitment_sha256",
        ],
    },
)


@final
class PublishableExtractionSuiteTerminalAdapter:
    """Issue per-run scheduler capabilities from one exact sealed suite readback."""

    __slots__ = ("_items", "_runs")

    def __init__(
        self,
        *,
        suite: SchedulerSuiteAuthority,
        run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
        readback: PublishableExtractionSuiteReadback,
    ) -> None:
        if (
            type(suite) is not SchedulerSuiteAuthority
            or type(run_stores) is not tuple
            or len(run_stores) != 2
            or any(type(item) is not SchedulerRunStoreSpec for item in run_stores)
            or type(readback) is not PublishableExtractionSuiteReadback
        ):
            _fail("scheduler_extraction_terminal_adapter_input_invalid")
        try:
            _validate_suite_authority(suite, run_stores)
            _validate_readback(readback)
            terminals = (readback.locomo_terminal, readback.longmemeval_terminal)
            items = tuple(
                _authenticate_slot(
                    suite=suite,
                    spec=spec,
                    terminal=terminal,
                    expected_profile_id=profile_id,
                    expected_receipt_count=receipt_count,
                )
                for spec, terminal, (profile_id, receipt_count) in zip(
                    run_stores,
                    terminals,
                    PUBLISHABLE_EXTRACTION_BENCHMARKS,
                    strict=True,
                )
            )
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_extraction_terminal_adapter_source_invalid")
        self._runs = tuple(spec.run for spec in run_stores)
        self._items = items

    @property
    def read_policy_sha256(self) -> str:
        return PUBLISHABLE_EXTRACTION_SUITE_TERMINAL_READ_POLICY_SHA256

    def read_terminal(
        self,
        *,
        run: SchedulerRunAuthority,
    ) -> SchedulerAuthenticatedExtractionTerminal:
        """Return only an exact bound run; this completed readback has no missing state."""

        if type(run) is not SchedulerRunAuthority:
            _fail("scheduler_extraction_terminal_adapter_run_invalid")
        try:
            if run.commitment_sha256 != commitment("run", run.material()):
                _fail("scheduler_extraction_terminal_adapter_run_invalid")
        except SchedulerRunnerError:
            raise
        except Exception:
            _fail("scheduler_extraction_terminal_adapter_run_invalid")
        for expected, item in zip(self._runs, self._items, strict=True):
            if run == expected:
                return item
            if hmac.compare_digest(run.commitment_sha256, expected.commitment_sha256):
                _fail("scheduler_extraction_terminal_adapter_run_cross_wire")
        _fail("scheduler_extraction_terminal_adapter_run_unknown")


def _validate_suite_authority(
    suite: SchedulerSuiteAuthority,
    run_stores: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
) -> None:
    if suite.commitment_sha256 != commitment(
        "suite", suite.material()
    ) or suite.bridge_boot.commitment_sha256 != commitment(
        "bridge-boot", suite.bridge_boot.material()
    ):
        _fail("scheduler_extraction_terminal_adapter_suite_invalid")
    try:
        require_exact_suite(suite, run_stores)
    except Exception:
        _fail("scheduler_extraction_terminal_adapter_suite_invalid")
    for spec in run_stores:
        run = spec.run
        if (
            run.commitment_sha256 != commitment("run", run.material())
            or run.suite_authority_sha256 != suite.commitment_sha256
            or run.bridge_boot_authority_sha256 != suite.bridge_boot.commitment_sha256
        ):
            _fail("scheduler_extraction_terminal_adapter_suite_invalid")


def _validate_readback(readback: PublishableExtractionSuiteReadback) -> None:
    if (
        readback.global_publishable is not False
        or readback.paid_go_ready is not False
        or readback.suite_readback_commitment_sha256 != canonical_sha256(readback.body())
    ):
        _fail("scheduler_extraction_terminal_adapter_source_invalid")
    terminals = (readback.locomo_terminal, readback.longmemeval_terminal)
    if any(type(item) is not PublishableExtractionRunTerminal for item in terminals):
        _fail("scheduler_extraction_terminal_adapter_source_invalid")
    for values in (
        tuple(item.run_id_sha256 for item in terminals),
        tuple(item.binding_commitment_sha256 for item in terminals),
        tuple(item.dataset_sha256 for item in terminals),
        tuple(item.terminal_commitment_sha256 for item in terminals),
    ):
        if len(set(values)) != 2:
            _fail("scheduler_extraction_terminal_adapter_source_cross_wire")


def _authenticate_slot(
    *,
    suite: SchedulerSuiteAuthority,
    spec: SchedulerRunStoreSpec,
    terminal: PublishableExtractionRunTerminal,
    expected_profile_id: str,
    expected_receipt_count: int,
) -> SchedulerAuthenticatedExtractionTerminal:
    run = spec.run
    source_context = _context_from_terminal(terminal)
    source_terminal = terminal.ledger_terminal
    try:
        ManagedFullRunExtractionTerminal.__post_init__(source_terminal)
    except Exception:
        _fail("scheduler_extraction_terminal_adapter_terminal_invalid")
    if (
        terminal.profile_id != expected_profile_id
        or terminal.profile_id != run.binding.profile.profile_id
        or terminal.run_id_sha256 != hashlib.sha256(run.binding.run_id.encode("utf-8")).hexdigest()
        or terminal.binding_commitment_sha256 != run.binding.binding_commitment_sha256
        or terminal.dataset_sha256 != run.binding.dataset_sha256
        or terminal.methodology_commitment_sha256 != suite.methodology_sha256
        or terminal.scheduler_bridge_runtime_authority_sha256
        != suite.bridge_boot.runtime_authority_sha256
        or terminal.expected_receipt_count != expected_receipt_count
        or source_context.expected_receipt_count != expected_receipt_count
        or terminal.ledger_context_commitment_sha256 != source_context.commitment_sha256
        or source_terminal.context_commitment_sha256 != source_context.commitment_sha256
        or source_terminal.receipt_count != expected_receipt_count
        or terminal.paid_go_ready is not False
        or terminal.terminal_commitment_sha256 != canonical_sha256(terminal.body())
    ):
        _fail("scheduler_extraction_terminal_adapter_terminal_divergent")
    context = replace(
        source_context,
        runtime_binding_commitment_sha256=(terminal.scheduler_bridge_runtime_authority_sha256),
    )
    projected_body = {
        **source_terminal.body(),
        "context_commitment_sha256": context.commitment_sha256,
    }
    ledger_terminal = ManagedFullRunExtractionTerminal(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=source_terminal.receipt_count,
        page_count=source_terminal.page_count,
        receipt_pages_root_sha256=source_terminal.receipt_pages_root_sha256,
        prompt_tokens=source_terminal.prompt_tokens,
        completion_tokens=source_terminal.completion_tokens,
        total_tokens=source_terminal.total_tokens,
        terminal_commitment_sha256=canonical_sha256(projected_body),
    )
    evidence = SchedulerExtractionTerminalEvidence(
        context=context,
        terminal=ledger_terminal,
    )
    return authenticate_extraction_terminal(
        run_authority_sha256=run.commitment_sha256,
        read_policy_sha256=PUBLISHABLE_EXTRACTION_SUITE_TERMINAL_READ_POLICY_SHA256,
        evidence=evidence,
        authentication_secret=spec.authentication_secret,
    )


def _context_from_terminal(
    terminal: PublishableExtractionRunTerminal,
) -> ManagedFullRunExtractionContext:
    try:
        return ManagedFullRunExtractionContext(
            profile_id=terminal.profile_id,
            run_id_sha256=terminal.run_id_sha256,
            binding_commitment_sha256=terminal.binding_commitment_sha256,
            methodology_commitment_sha256=terminal.methodology_commitment_sha256,
            admission_commitment_sha256=terminal.admission_commitment_sha256,
            ingestion_root_sha256=terminal.ingestion_root_sha256,
            a1_terminal_commitment_sha256=terminal.a1_terminal_commitment_sha256,
            a1_manifest_context_sha256=terminal.a1_manifest_context_sha256,
            runtime_binding_commitment_sha256=(terminal.runtime_binding_commitment_sha256),
            expected_receipt_count=terminal.expected_receipt_count,
        )
    except Exception:
        _fail("scheduler_extraction_terminal_adapter_terminal_invalid")


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code) from None


__all__ = (
    "PUBLISHABLE_EXTRACTION_SUITE_TERMINAL_READ_POLICY_SHA256",
    "PublishableExtractionSuiteTerminalAdapter",
)
