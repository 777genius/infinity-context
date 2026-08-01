"""Concurrency-safe provider call and token budget decorator."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from infinity_context_server.memory_comparison_llm import approximate_token_count
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderChatCompletion,
    ProviderChatCompletionsPort,
)

DEFAULT_BOUNDED_PROVIDER_MAX_CALLS = 32
_CLOSED = "bounded_provider_closed"
_CALL_LIMIT = "bounded_provider_call_limit"
_TOKEN_LIMIT = "bounded_provider_token_limit"
_OUTPUT_LIMIT = "bounded_provider_output_limit"
_DEADLINE = "bounded_provider_deadline"
_ESTIMATE_INVALID = "bounded_provider_estimate_invalid"
_DELEGATE_FAILED = "bounded_provider_delegate_failed"
_USAGE_INVALID = "bounded_provider_usage_invalid"
_USAGE_EXCEEDED_RESERVATION = "bounded_provider_usage_exceeded_reservation"
_DELEGATE_CLOSE_FAILED = "bounded_provider_delegate_close_failed"


class BoundedProviderError(RuntimeError):
    """Fixed-code failure that never includes provider inputs or credentials."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BoundedProviderBudget:
    """Immutable admission limits for one provider transport lifetime.

    ``deadline_monotonic`` is checked immediately before admission and after the
    delegate returns or raises. This decorator cannot preempt an in-flight
    delegate call; transport adapters must enforce their own request timeout.
    """

    max_total_tokens: int
    deadline_monotonic: float
    max_calls: int = DEFAULT_BOUNDED_PROVIDER_MAX_CALLS
    max_output_tokens_per_call: int = 4096

    def __post_init__(self) -> None:
        _positive_int(self.max_total_tokens, label="max_total_tokens")
        _positive_int(self.max_calls, label="max_calls")
        _positive_int(self.max_output_tokens_per_call, label="max_output_tokens_per_call")
        if (
            isinstance(self.deadline_monotonic, bool)
            or not isinstance(self.deadline_monotonic, int | float)
            or not math.isfinite(self.deadline_monotonic)
            or self.deadline_monotonic <= 0
        ):
            raise ValueError("deadline_monotonic must be a positive finite number")


@dataclass(frozen=True, slots=True)
class BoundedProviderUsageSnapshot:
    """Prompt-free public accounting state."""

    calls: int
    reserved_tokens: int
    consumed_tokens: int
    remaining_tokens: int

    def public_payload(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "reserved_tokens": self.reserved_tokens,
            "consumed_tokens": self.consumed_tokens,
            "remaining_tokens": self.remaining_tokens,
        }


class BoundedProviderChatCompletions:
    """Decorate a provider port with one fail-closed, process-local budget."""

    def __init__(
        self,
        *,
        delegate: ProviderChatCompletionsPort,
        budget: BoundedProviderBudget,
        input_token_estimator: Callable[[str], int] = approximate_token_count,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._delegate = delegate
        self._budget = budget
        self._input_token_estimator = input_token_estimator
        self._clock = monotonic_clock
        self._condition = threading.Condition(threading.Lock())
        self._calls = 0
        self._reserved_tokens = 0
        self._consumed_tokens = 0
        self._active_calls = 0
        self._accepting_calls = True
        self._close_started = False
        self._close_completed = False

    def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
        temperature: float | None = None,
        response_format: Mapping[str, object] | None = None,
    ) -> ProviderChatCompletion:
        output_reservation = self._validated_output_reservation(max_output_tokens)
        input_reservation = self._estimated_input_reservation(system_prompt, user_prompt)
        reservation = input_reservation + output_reservation
        self._admit(reservation)
        try:
            completion = self._delegate.complete(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                response_format=response_format,
            )
        except BaseException as exc:
            self._finalize_failed_call(reservation)
            if isinstance(exc, Exception):
                raise BoundedProviderError(_DELEGATE_FAILED) from None
            raise

        try:
            actual_tokens = _reported_usage(completion)
        except BoundedProviderError:
            self._finalize_invalid_usage(reservation)
            raise
        if actual_tokens is None:
            actual_tokens = reservation
        elif completion.token_usage_source != "provider_observed":
            actual_tokens = max(reservation, actual_tokens)
        return self._finalize_success(completion, reservation, actual_tokens)

    def usage_snapshot(self) -> BoundedProviderUsageSnapshot:
        with self._condition:
            committed = self._consumed_tokens + self._reserved_tokens
            return BoundedProviderUsageSnapshot(
                calls=self._calls,
                reserved_tokens=self._reserved_tokens,
                consumed_tokens=self._consumed_tokens,
                remaining_tokens=max(0, self._budget.max_total_tokens - committed),
            )

    def close(self) -> None:
        owns_close = False
        with self._condition:
            if self._close_completed:
                return
            if not self._close_started:
                self._close_started = True
                self._accepting_calls = False
                owns_close = True
            if not owns_close:
                while not self._close_completed:
                    self._condition.wait()
                return
            while self._active_calls:
                self._condition.wait()
        close_failed = False
        try:
            self._delegate.close()
        except Exception:
            close_failed = True
        finally:
            with self._condition:
                self._close_completed = True
                self._condition.notify_all()
        if close_failed:
            raise BoundedProviderError(_DELEGATE_CLOSE_FAILED) from None

    def _validated_output_reservation(self, value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > self._budget.max_output_tokens_per_call
        ):
            raise BoundedProviderError(_OUTPUT_LIMIT)
        return value

    def _estimated_input_reservation(self, system_prompt: str, user_prompt: str) -> int:
        try:
            estimate = self._input_token_estimator(f"{system_prompt}\n{user_prompt}")
        except Exception:
            raise BoundedProviderError(_ESTIMATE_INVALID) from None
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise BoundedProviderError(_ESTIMATE_INVALID)
        return estimate

    def _admit(self, reservation: int) -> None:
        with self._condition:
            if not self._accepting_calls:
                raise BoundedProviderError(_CLOSED)
            if self._clock() >= self._budget.deadline_monotonic:
                self._accepting_calls = False
                raise BoundedProviderError(_DEADLINE)
            if self._calls >= self._budget.max_calls:
                raise BoundedProviderError(_CALL_LIMIT)
            committed = self._consumed_tokens + self._reserved_tokens
            if reservation > self._budget.max_total_tokens - committed:
                raise BoundedProviderError(_TOKEN_LIMIT)
            self._calls += 1
            self._reserved_tokens += reservation
            self._active_calls += 1

    def _finalize_failed_call(self, reservation: int) -> None:
        with self._condition:
            self._reserved_tokens -= reservation
            self._consumed_tokens += reservation
            self._active_calls -= 1
            if self._clock() >= self._budget.deadline_monotonic:
                self._accepting_calls = False
            self._condition.notify_all()

    def _finalize_invalid_usage(self, reservation: int) -> None:
        with self._condition:
            self._reserved_tokens -= reservation
            self._consumed_tokens += reservation
            self._active_calls -= 1
            self._accepting_calls = False
            self._condition.notify_all()

    def _finalize_success(
        self,
        completion: ProviderChatCompletion,
        reservation: int,
        actual_tokens: int,
    ) -> ProviderChatCompletion:
        error_code = ""
        with self._condition:
            self._reserved_tokens -= reservation
            self._consumed_tokens += actual_tokens
            self._active_calls -= 1
            if actual_tokens > reservation:
                self._accepting_calls = False
                error_code = _USAGE_EXCEEDED_RESERVATION
            elif self._clock() >= self._budget.deadline_monotonic:
                self._accepting_calls = False
                error_code = _DEADLINE
            self._condition.notify_all()
        if error_code:
            raise BoundedProviderError(error_code)
        return completion


def _positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _reported_usage(completion: ProviderChatCompletion) -> int | None:
    if type(completion) is not ProviderChatCompletion:
        raise BoundedProviderError(_USAGE_INVALID)
    prompt_tokens = completion.prompt_tokens
    completion_tokens = completion.completion_tokens
    for value in (prompt_tokens, completion_tokens):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BoundedProviderError(_USAGE_INVALID)
    usage_source = completion.token_usage_source
    if usage_source == "":
        if prompt_tokens != 0 or completion_tokens != 0:
            raise BoundedProviderError(_USAGE_INVALID)
        return None
    if usage_source not in {
        "provider_observed",
        "estimated_by_subscription_adapter",
    }:
        raise BoundedProviderError(_USAGE_INVALID)
    if prompt_tokens <= 0 or completion_tokens <= 0:
        raise BoundedProviderError(_USAGE_INVALID)
    return prompt_tokens + completion_tokens


__all__ = [
    "DEFAULT_BOUNDED_PROVIDER_MAX_CALLS",
    "BoundedProviderBudget",
    "BoundedProviderChatCompletions",
    "BoundedProviderError",
    "BoundedProviderUsageSnapshot",
]
