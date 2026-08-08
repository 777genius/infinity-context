"""Requested extraction-token plan and post-run observed-spend ceiling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import final

_MAX_OPERATOR_TOKENS = 2_000_000_000
_MAX_ANSWER_JUDGE_TOKENS = 2_000_000


class ManagedV5ExtractionBudgetError(ValueError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
@dataclass(frozen=True, slots=True)
class ManagedV5ExtractionReservationUnit:
    request_body_bytes: int
    requested_output_tokens: int

    def __post_init__(self) -> None:
        if (
            type(self.request_body_bytes) is not int
            or self.request_body_bytes < 1
            or type(self.requested_output_tokens) is not int
            or self.requested_output_tokens < 1
        ):
            _fail("managed_v5_extraction_reservation_unit_invalid")

    @property
    def planned_token_reservation(self) -> int:
        return self.request_body_bytes + self.requested_output_tokens


@final
@dataclass(frozen=True, slots=True)
class ManagedV5ExtractionTokenBudget:
    operation_count: int
    aggregate_request_body_bytes: int
    aggregate_requested_output_tokens: int
    planned_extraction_token_reservation: int
    operator_extraction_token_ceiling: int
    operator_total_token_ceiling: int
    answer_judge_reserved_token_ceiling: int
    commitment_sha256: str

    def __post_init__(self) -> None:
        values = (
            self.operation_count,
            self.aggregate_request_body_bytes,
            self.aggregate_requested_output_tokens,
            self.planned_extraction_token_reservation,
            self.operator_extraction_token_ceiling,
            self.operator_total_token_ceiling,
            self.answer_judge_reserved_token_ceiling,
        )
        if (
            any(type(value) is not int or value < 1 for value in values)
            or self.planned_extraction_token_reservation
            != self.aggregate_request_body_bytes + self.aggregate_requested_output_tokens
            or self.operator_extraction_token_ceiling < self.planned_extraction_token_reservation
            or self.operator_total_token_ceiling
            != self.operator_extraction_token_ceiling + self.answer_judge_reserved_token_ceiling
            or self.operator_total_token_ceiling > _MAX_OPERATOR_TOKENS
            or self.answer_judge_reserved_token_ceiling > _MAX_ANSWER_JUDGE_TOKENS
            or self.commitment_sha256 != _commitment(self._commitment_payload())
        ):
            _fail("managed_v5_extraction_token_budget_invalid")

    @classmethod
    def reserve(
        cls,
        units: tuple[ManagedV5ExtractionReservationUnit, ...],
        *,
        operator_extraction_token_ceiling: int,
        operator_total_token_ceiling: int,
    ) -> ManagedV5ExtractionTokenBudget:
        if (
            type(units) is not tuple
            or not units
            or any(type(unit) is not ManagedV5ExtractionReservationUnit for unit in units)
            or type(operator_extraction_token_ceiling) is not int
            or type(operator_total_token_ceiling) is not int
        ):
            _fail("managed_v5_extraction_token_budget_invalid")
        request_bytes = sum(unit.request_body_bytes for unit in units)
        output_tokens = sum(unit.requested_output_tokens for unit in units)
        reservation = request_bytes + output_tokens
        answer_judge = operator_total_token_ceiling - operator_extraction_token_ceiling
        payload = {
            "aggregate_request_body_bytes": request_bytes,
            "aggregate_requested_output_tokens": output_tokens,
            "answer_judge_reserved_token_ceiling": answer_judge,
            "planned_extraction_token_reservation": reservation,
            "operation_count": len(units),
            "operator_extraction_token_ceiling": operator_extraction_token_ceiling,
            "operator_total_token_ceiling": operator_total_token_ceiling,
            "output_limit_enforcement": "requested_not_provider_verified",
            "reservation_method": "utf8_request_bytes_plus_requested_output_token_limits",
            "tokenizer_exact": False,
        }
        return cls(
            operation_count=len(units),
            aggregate_request_body_bytes=request_bytes,
            aggregate_requested_output_tokens=output_tokens,
            planned_extraction_token_reservation=reservation,
            operator_extraction_token_ceiling=operator_extraction_token_ceiling,
            operator_total_token_ceiling=operator_total_token_ceiling,
            answer_judge_reserved_token_ceiling=answer_judge,
            commitment_sha256=_commitment(payload),
        )

    def require_observed_extraction_tokens(
        self,
        *,
        provider_observed_request_tokens: int,
        provider_observed_response_tokens: int,
    ) -> None:
        if (
            type(provider_observed_request_tokens) is not int
            or provider_observed_request_tokens < 0
            or type(provider_observed_response_tokens) is not int
            or provider_observed_response_tokens < 0
            or provider_observed_request_tokens + provider_observed_response_tokens
            > self.operator_extraction_token_ceiling
        ):
            _fail("managed_v5_extraction_observed_token_ceiling_exceeded")

    def public_payload(self) -> dict[str, object]:
        return {**self._commitment_payload(), "commitment_sha256": self.commitment_sha256}

    def _commitment_payload(self) -> dict[str, object]:
        return {
            "aggregate_request_body_bytes": self.aggregate_request_body_bytes,
            "aggregate_requested_output_tokens": self.aggregate_requested_output_tokens,
            "answer_judge_reserved_token_ceiling": self.answer_judge_reserved_token_ceiling,
            "planned_extraction_token_reservation": (self.planned_extraction_token_reservation),
            "operation_count": self.operation_count,
            "operator_extraction_token_ceiling": self.operator_extraction_token_ceiling,
            "operator_total_token_ceiling": self.operator_total_token_ceiling,
            "output_limit_enforcement": "requested_not_provider_verified",
            "reservation_method": "utf8_request_bytes_plus_requested_output_token_limits",
            "tokenizer_exact": False,
        }


def _commitment(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fail(code: str) -> None:
    raise ManagedV5ExtractionBudgetError(code)


__all__ = (
    "ManagedV5ExtractionBudgetError",
    "ManagedV5ExtractionReservationUnit",
    "ManagedV5ExtractionTokenBudget",
)
