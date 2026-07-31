"""Exact public models for a gold-blind dispatch manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    validate_dispatch_id,
)


@final
@dataclass(frozen=True, slots=True)
class GoldBlindExpectedDispatchCase:
    """Exact backend-role selection for one expected case in a run."""

    case_id: str
    retrieval_backend_id: str
    answer_backend_id: str
    judge_backend_id: str

    def __post_init__(self) -> None:
        validate_dispatch_id(self.case_id, field_name="Expected case_id")
        for value in (
            self.retrieval_backend_id,
            self.answer_backend_id,
            self.judge_backend_id,
        ):
            validate_dispatch_id(value, field_name="Expected backend_id")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindExpectedDispatchCase is final")
