"""Exact full-suite provider-call ledger shared by seals and receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET,
    PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET,
    PUBLISHABLE_FULL_TOTAL_CALL_BUDGET,
)

PUBLISHABLE_CALL_LEDGER_SCHEMA_VERSION = "memory-comparison-publishable-call-ledger.v1"


class PublishableCallLedgerError(ValueError):
    """Fail-closed rejection of a divergent full-suite call ledger."""


@final
@dataclass(frozen=True, slots=True)
class PublishableCallLedger:
    """The exact 130,226 + 8,160 = 138,386 call authority."""

    extraction_call_count: int
    answer_judge_call_count: int
    total_call_count: int

    def __post_init__(self) -> None:
        if (
            type(self.extraction_call_count) is not int
            or type(self.answer_judge_call_count) is not int
            or type(self.total_call_count) is not int
            or self.extraction_call_count != PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET
            or self.answer_judge_call_count != PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET
            or self.total_call_count != PUBLISHABLE_FULL_TOTAL_CALL_BUDGET
            or self.total_call_count != self.extraction_call_count + self.answer_judge_call_count
        ):
            _fail("publishable_call_ledger_invalid")

    def material(self) -> dict[str, object]:
        return {
            "schema_version": PUBLISHABLE_CALL_LEDGER_SCHEMA_VERSION,
            "extraction_call_count": self.extraction_call_count,
            "answer_judge_call_count": self.answer_judge_call_count,
            "total_call_count": self.total_call_count,
        }


def exact_publishable_call_ledger() -> PublishableCallLedger:
    return PublishableCallLedger(
        extraction_call_count=PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET,
        answer_judge_call_count=PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET,
        total_call_count=PUBLISHABLE_FULL_TOTAL_CALL_BUDGET,
    )


def publishable_call_ledger_from_material(value: object) -> PublishableCallLedger:
    expected = {
        "schema_version",
        "extraction_call_count",
        "answer_judge_call_count",
        "total_call_count",
    }
    if (
        type(value) is not dict
        or set(value) != expected
        or value.get("schema_version") != PUBLISHABLE_CALL_LEDGER_SCHEMA_VERSION
    ):
        _fail("publishable_call_ledger_material_invalid")
    try:
        return PublishableCallLedger(
            extraction_call_count=value["extraction_call_count"],
            answer_judge_call_count=value["answer_judge_call_count"],
            total_call_count=value["total_call_count"],
        )
    except (KeyError, TypeError, ValueError, PublishableCallLedgerError):
        _fail("publishable_call_ledger_material_invalid")


def _fail(code: str) -> None:
    raise PublishableCallLedgerError(code) from None


__all__ = (
    "PUBLISHABLE_CALL_LEDGER_SCHEMA_VERSION",
    "PublishableCallLedger",
    "PublishableCallLedgerError",
    "exact_publishable_call_ledger",
    "publishable_call_ledger_from_material",
)
