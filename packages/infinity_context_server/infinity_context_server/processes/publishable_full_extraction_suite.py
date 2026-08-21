"""Exact two-benchmark extraction readback for the answer/judge suite sealer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, final

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS,
)

from infinity_context_server.processes.publishable_full_extraction_worker import (
    PublishableExtractionRunTerminal,
)

PUBLISHABLE_EXTRACTION_SUITE_SCHEMA = "publishable-full-extraction-suite.v2"
PUBLISHABLE_EXTRACTION_HANDOFF_SCHEMA = "publishable-full-extraction-handoff.v1"
PUBLISHABLE_EXTRACTION_BENCHMARKS = (
    (
        "mem0-locomo-top50-v1",
        MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS["mem0-locomo-top50-v1"],
    ),
    (
        "mem0-longmemeval-top50-v1",
        MANAGED_MEM0_V6_PROFILE_OPERATION_COUNTS["mem0-longmemeval-top50-v1"],
    ),
)
PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT = sum(
    count for _, count in PUBLISHABLE_EXTRACTION_BENCHMARKS
)


class PublishableExtractionSuiteError(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublishableExtractionTerminalReadbackPort(Protocol):
    def read_terminal(self) -> PublishableExtractionRunTerminal | None: ...


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionAnswerJudgeHandoff:
    """Evidence input only; it grants neither dispatch nor publication authority."""

    suite_readback_commitment_sha256: str
    profile_id: str
    run_id_sha256: str
    binding_commitment_sha256: str
    expected_receipt_count: int
    extraction_terminal_commitment_sha256: str
    ledger_terminal_commitment_sha256: str
    answer_judge_sealer_input_sha256: str = field(init=False)
    paid_go_ready: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        expected = dict(PUBLISHABLE_EXTRACTION_BENCHMARKS).get(self.profile_id)
        if (
            expected != self.expected_receipt_count
            or self.paid_go_ready is not False
            or any(
                not _sha(value)
                for value in (
                    self.suite_readback_commitment_sha256,
                    self.run_id_sha256,
                    self.binding_commitment_sha256,
                    self.extraction_terminal_commitment_sha256,
                    self.ledger_terminal_commitment_sha256,
                )
            )
        ):
            _fail("extraction_handoff_invalid")
        object.__setattr__(
            self,
            "answer_judge_sealer_input_sha256",
            canonical_sha256(self.body()),
        )

    def body(self) -> dict[str, object]:
        return {
            "schema_version": PUBLISHABLE_EXTRACTION_HANDOFF_SCHEMA,
            "suite_readback_commitment_sha256": self.suite_readback_commitment_sha256,
            "profile_id": self.profile_id,
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "expected_receipt_count": self.expected_receipt_count,
            "extraction_terminal_commitment_sha256": (self.extraction_terminal_commitment_sha256),
            "ledger_terminal_commitment_sha256": (self.ledger_terminal_commitment_sha256),
            "paid_go_ready": False,
        }


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionSuiteReadback:
    locomo_terminal: PublishableExtractionRunTerminal = field(repr=False)
    longmemeval_terminal: PublishableExtractionRunTerminal = field(repr=False)
    suite_readback_commitment_sha256: str = field(init=False)
    locomo_answer_judge_handoff: PublishableExtractionAnswerJudgeHandoff = field(init=False)
    longmemeval_answer_judge_handoff: PublishableExtractionAnswerJudgeHandoff = field(init=False)
    global_publishable: bool = field(default=False, init=False)
    paid_go_ready: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        terminals = (self.locomo_terminal, self.longmemeval_terminal)
        for terminal, expected in zip(
            terminals,
            PUBLISHABLE_EXTRACTION_BENCHMARKS,
            strict=True,
        ):
            _validate_terminal(terminal, profile_id=expected[0], receipt_count=expected[1])
        for values in (
            tuple(item.run_id_sha256 for item in terminals),
            tuple(item.binding_commitment_sha256 for item in terminals),
            tuple(item.dataset_sha256 for item in terminals),
            tuple(item.a1_manifest_context_sha256 for item in terminals),
            tuple(item.terminal_commitment_sha256 for item in terminals),
        ):
            if len(set(values)) != len(values):
                _fail("extraction_suite_cross_wire")
        if len({item.scheduler_bridge_runtime_authority_sha256 for item in terminals}) != 1:
            _fail("extraction_suite_cross_wire")
        if self.global_publishable is not False or self.paid_go_ready is not False:
            _fail("extraction_suite_readiness_invalid")
        commitment = canonical_sha256(self.body())
        object.__setattr__(self, "suite_readback_commitment_sha256", commitment)
        object.__setattr__(
            self,
            "locomo_answer_judge_handoff",
            _handoff(self.locomo_terminal, suite_commitment=commitment),
        )
        object.__setattr__(
            self,
            "longmemeval_answer_judge_handoff",
            _handoff(self.longmemeval_terminal, suite_commitment=commitment),
        )

    def body(self) -> dict[str, object]:
        terminals = (self.locomo_terminal, self.longmemeval_terminal)
        return {
            "schema_version": PUBLISHABLE_EXTRACTION_SUITE_SCHEMA,
            "ordered_profile_id": [item[0] for item in PUBLISHABLE_EXTRACTION_BENCHMARKS],
            "ordered_expected_receipt_count": [
                item[1] for item in PUBLISHABLE_EXTRACTION_BENCHMARKS
            ],
            "total_expected_receipt_count": PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT,
            "ordered_run_id_sha256": [item.run_id_sha256 for item in terminals],
            "ordered_binding_commitment_sha256": [
                item.binding_commitment_sha256 for item in terminals
            ],
            "ordered_extraction_terminal_commitment_sha256": [
                item.terminal_commitment_sha256 for item in terminals
            ],
            "scheduler_bridge_runtime_authority_sha256": (
                terminals[0].scheduler_bridge_runtime_authority_sha256
            ),
            "ordered_ledger_terminal_commitment_sha256": [
                item.ledger_terminal.terminal_commitment_sha256 for item in terminals
            ],
            "global_publishable": False,
            "paid_go_ready": False,
        }


def read_publishable_full_extraction_suite(
    *,
    locomo_reader: PublishableExtractionTerminalReadbackPort,
    longmemeval_reader: PublishableExtractionTerminalReadbackPort,
) -> PublishableExtractionSuiteReadback:
    """Read each independently sealed extraction terminal exactly once."""

    if any(
        not callable(getattr(reader, "read_terminal", None))
        for reader in (locomo_reader, longmemeval_reader)
    ):
        _fail("extraction_suite_reader_invalid")
    locomo = locomo_reader.read_terminal()
    longmemeval = longmemeval_reader.read_terminal()
    if locomo is None or longmemeval is None:
        _fail("extraction_suite_terminal_missing")
    return PublishableExtractionSuiteReadback(
        locomo_terminal=locomo,
        longmemeval_terminal=longmemeval,
    )


def _validate_terminal(
    terminal: object,
    *,
    profile_id: str,
    receipt_count: int,
) -> None:
    if type(terminal) is not PublishableExtractionRunTerminal:
        _fail("extraction_suite_terminal_invalid")
    ledger = terminal.ledger_terminal
    if type(ledger) is not ManagedFullRunExtractionTerminal:
        _fail("extraction_suite_terminal_invalid")
    try:
        ManagedFullRunExtractionTerminal.__post_init__(ledger)
    except Exception:
        _fail("extraction_suite_terminal_invalid")
    digests = (
        terminal.run_id_sha256,
        terminal.binding_commitment_sha256,
        terminal.methodology_commitment_sha256,
        terminal.admission_commitment_sha256,
        terminal.ingestion_root_sha256,
        terminal.a1_terminal_commitment_sha256,
        terminal.a1_manifest_context_sha256,
        terminal.runtime_binding_commitment_sha256,
        terminal.scheduler_bridge_runtime_authority_sha256,
        terminal.preparation_receipt_sha256,
        terminal.dataset_sha256,
        terminal.a2_terminal_commitment_sha256,
        terminal.journal_manifest_commitment_sha256,
        terminal.journal_state_commitment_sha256,
        terminal.journal_head_event_sha256,
    )
    if (
        terminal.profile_id != profile_id
        or terminal.expected_receipt_count != receipt_count
        or terminal.paid_go_ready is not False
        or any(not _sha(value) for value in digests)
        or terminal.terminal_commitment_sha256 != canonical_sha256(terminal.body())
        or ledger.context_commitment_sha256 != terminal.ledger_context_commitment_sha256
        or ledger.receipt_count != receipt_count
        or ledger.terminal_commitment_sha256 != canonical_sha256(ledger.body())
    ):
        _fail("extraction_suite_terminal_invalid")


def _handoff(
    terminal: PublishableExtractionRunTerminal,
    *,
    suite_commitment: str,
) -> PublishableExtractionAnswerJudgeHandoff:
    return PublishableExtractionAnswerJudgeHandoff(
        suite_readback_commitment_sha256=suite_commitment,
        profile_id=terminal.profile_id,
        run_id_sha256=terminal.run_id_sha256,
        binding_commitment_sha256=terminal.binding_commitment_sha256,
        expected_receipt_count=terminal.expected_receipt_count,
        extraction_terminal_commitment_sha256=terminal.terminal_commitment_sha256,
        ledger_terminal_commitment_sha256=(terminal.ledger_terminal.terminal_commitment_sha256),
    )


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise PublishableExtractionSuiteError(code) from None


__all__ = (
    "PUBLISHABLE_EXTRACTION_BENCHMARKS",
    "PUBLISHABLE_EXTRACTION_HANDOFF_SCHEMA",
    "PUBLISHABLE_EXTRACTION_SUITE_SCHEMA",
    "PUBLISHABLE_EXTRACTION_TOTAL_OPERATION_COUNT",
    "PublishableExtractionAnswerJudgeHandoff",
    "PublishableExtractionSuiteError",
    "PublishableExtractionSuiteReadback",
    "PublishableExtractionTerminalReadbackPort",
    "read_publishable_full_extraction_suite",
)
