from __future__ import annotations

import threading
from collections.abc import Mapping

import pytest
from infinity_context_server.memory_comparison_bounded_provider import (
    DEFAULT_BOUNDED_PROVIDER_MAX_CALLS,
    BoundedProviderBudget,
    BoundedProviderChatCompletions,
    BoundedProviderError,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderChatCompletion,
)


class _Delegate:
    def __init__(self, completion: ProviderChatCompletion | None = None) -> None:
        self.completion = completion or _completion(prompt_tokens=1, completion_tokens=1)
        self.calls = 0
        self.close_calls = 0
        self.failure: Exception | None = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self._lock = threading.Lock()

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
        del model, system_prompt, user_prompt, max_output_tokens, temperature, response_format
        with self._lock:
            self.calls += 1
        self.entered.set()
        if self.block:
            assert self.release.wait(timeout=2)
        if self.failure is not None:
            failure = self.failure
            self.failure = None
            raise failure
        return self.completion

    def close(self) -> None:
        self.close_calls += 1


def test_default_call_limit_supports_exactly_32_calls() -> None:
    delegate = _Delegate()
    provider = _provider(delegate, max_total_tokens=1000)

    for _ in range(DEFAULT_BOUNDED_PROVIDER_MAX_CALLS):
        _complete(provider)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)
    assert exc_info.value.code == "bounded_provider_call_limit"
    assert delegate.calls == 32


def test_token_and_output_limits_reject_before_delegate() -> None:
    delegate = _Delegate()
    provider = _provider(delegate, max_total_tokens=6, output_ceiling=4, estimate=3)

    with pytest.raises(BoundedProviderError) as token_error:
        _complete(provider, max_output_tokens=4)
    assert token_error.value.code == "bounded_provider_token_limit"

    with pytest.raises(BoundedProviderError) as output_error:
        _complete(provider, max_output_tokens=5)
    assert output_error.value.code == "bounded_provider_output_limit"
    assert delegate.calls == 0


def test_expired_monotonic_deadline_rejects_without_delegate_call() -> None:
    delegate = _Delegate()
    provider = _provider(delegate, clock=lambda: 11.0, deadline=10.0)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)

    assert exc_info.value.code == "bounded_provider_deadline"
    assert delegate.calls == 0


def test_concurrent_admission_cannot_oversubscribe_token_reservation() -> None:
    delegate = _Delegate()
    delegate.block = True
    provider = _provider(delegate, max_calls=2, max_total_tokens=3, estimate=1)
    first_result: list[object] = []

    def first_call() -> None:
        try:
            first_result.append(_complete(provider))
        except Exception as exc:  # pragma: no cover - diagnostic capture
            first_result.append(exc)

    thread = threading.Thread(target=first_call)
    thread.start()
    assert delegate.entered.wait(timeout=2)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)
    snapshot = provider.usage_snapshot()
    assert exc_info.value.code == "bounded_provider_token_limit"
    assert delegate.calls == 1
    assert snapshot.calls == 1
    assert snapshot.reserved_tokens == 3

    delegate.release.set()
    thread.join(timeout=2)
    assert len(first_result) == 1
    assert isinstance(first_result[0], ProviderChatCompletion)


def test_delegate_failure_burns_reservation_and_call_count() -> None:
    delegate = _Delegate()
    delegate.failure = RuntimeError("secret provider payload")
    provider = _provider(delegate, max_calls=2, max_total_tokens=6, estimate=1)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)
    assert str(exc_info.value) == "bounded_provider_delegate_failed"
    assert provider.usage_snapshot().public_payload() == {
        "calls": 1,
        "reserved_tokens": 0,
        "consumed_tokens": 3,
        "remaining_tokens": 3,
    }

    _complete(provider)
    assert delegate.calls == 2
    assert provider.usage_snapshot().calls == 2


def test_reported_usage_reconciles_and_snapshot_is_prompt_free() -> None:
    delegate = _Delegate(_completion(prompt_tokens=2, completion_tokens=1))
    provider = _provider(delegate, max_total_tokens=10, estimate=3)

    provider.complete(
        model="model",
        system_prompt="do-not-leak-system",
        user_prompt="do-not-leak-user",
        max_output_tokens=4,
    )

    payload = provider.usage_snapshot().public_payload()
    assert payload == {
        "calls": 1,
        "reserved_tokens": 0,
        "consumed_tokens": 3,
        "remaining_tokens": 7,
    }
    assert "leak" not in repr(payload)


def test_actual_usage_above_reservation_trips_provider_closed() -> None:
    delegate = _Delegate(_completion(prompt_tokens=3, completion_tokens=2))
    provider = _provider(delegate, max_total_tokens=10, estimate=1)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)
    assert exc_info.value.code == "bounded_provider_usage_exceeded_reservation"
    assert provider.usage_snapshot().consumed_tokens == 5

    with pytest.raises(BoundedProviderError) as closed_error:
        _complete(provider)
    assert closed_error.value.code == "bounded_provider_closed"
    assert delegate.calls == 1


def test_missing_and_invalid_usage_are_conservative() -> None:
    missing = _Delegate(ProviderChatCompletion(text="ok"))
    missing_provider = _provider(missing, max_total_tokens=10, estimate=2)
    _complete(missing_provider)
    assert missing_provider.usage_snapshot().consumed_tokens == 4

    invalid = _Delegate(_completion(prompt_tokens=-1, completion_tokens=1))
    invalid_provider = _provider(invalid, max_total_tokens=10, estimate=2)
    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(invalid_provider)
    assert exc_info.value.code == "bounded_provider_usage_invalid"
    assert invalid_provider.usage_snapshot().consumed_tokens == 4
    with pytest.raises(BoundedProviderError, match="bounded_provider_closed"):
        _complete(invalid_provider)


def test_estimated_usage_charges_at_least_the_admitted_reservation() -> None:
    estimated = _Delegate(
        _completion(
            prompt_tokens=1,
            completion_tokens=1,
            usage_source="estimated_by_subscription_adapter",
        )
    )
    provider = _provider(estimated, max_total_tokens=10, estimate=2)

    _complete(provider)

    assert provider.usage_snapshot().consumed_tokens == 4


def test_estimated_usage_above_reservation_is_charged_and_closes_provider() -> None:
    estimated = _Delegate(
        _completion(
            prompt_tokens=3,
            completion_tokens=2,
            usage_source="estimated_by_subscription_adapter",
        )
    )
    provider = _provider(estimated, max_total_tokens=10, estimate=1)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)

    assert exc_info.value.code == "bounded_provider_usage_exceeded_reservation"
    assert provider.usage_snapshot().consumed_tokens == 5
    with pytest.raises(BoundedProviderError, match="bounded_provider_closed"):
        _complete(provider)


def test_provider_observed_usage_requires_strictly_positive_counts() -> None:
    invalid = _Delegate(_completion(prompt_tokens=0, completion_tokens=1))
    provider = _provider(invalid, max_total_tokens=10, estimate=2)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)

    assert exc_info.value.code == "bounded_provider_usage_invalid"
    assert provider.usage_snapshot().consumed_tokens == 4


def test_deadline_is_checked_after_delegate_returns_but_does_not_preempt_it() -> None:
    delegate = _Delegate()
    clock_values = iter((1.0, 11.0))
    provider = _provider(delegate, clock=lambda: next(clock_values), deadline=10.0)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)

    assert exc_info.value.code == "bounded_provider_deadline"
    assert delegate.calls == 1
    assert provider.usage_snapshot().consumed_tokens == 2


def test_wrong_delegate_result_type_closes_without_leaking_active_reservation() -> None:
    delegate = _Delegate()
    delegate.completion = object()  # type: ignore[assignment]
    provider = _provider(delegate, max_total_tokens=10, estimate=2)

    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)

    assert exc_info.value.code == "bounded_provider_usage_invalid"
    assert provider.usage_snapshot().public_payload() == {
        "calls": 1,
        "reserved_tokens": 0,
        "consumed_tokens": 4,
        "remaining_tokens": 6,
    }
    provider.close()


def test_close_is_idempotent_and_prevents_future_calls() -> None:
    delegate = _Delegate()
    provider = _provider(delegate)

    provider.close()
    provider.close()

    assert delegate.close_calls == 1
    with pytest.raises(BoundedProviderError) as exc_info:
        _complete(provider)
    assert exc_info.value.code == "bounded_provider_closed"
    assert delegate.calls == 0


def _provider(
    delegate: _Delegate,
    *,
    max_calls: int = DEFAULT_BOUNDED_PROVIDER_MAX_CALLS,
    max_total_tokens: int = 100,
    output_ceiling: int = 4,
    estimate: int = 1,
    clock=lambda: 1.0,
    deadline: float = 10.0,
) -> BoundedProviderChatCompletions:
    return BoundedProviderChatCompletions(
        delegate=delegate,
        budget=BoundedProviderBudget(
            max_calls=max_calls,
            max_total_tokens=max_total_tokens,
            max_output_tokens_per_call=output_ceiling,
            deadline_monotonic=deadline,
        ),
        input_token_estimator=lambda _text: estimate,
        monotonic_clock=clock,
    )


def _complete(
    provider: BoundedProviderChatCompletions,
    *,
    max_output_tokens: int = 2,
) -> ProviderChatCompletion:
    return provider.complete(
        model="model",
        system_prompt="system",
        user_prompt="user",
        max_output_tokens=max_output_tokens,
    )


def _completion(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    usage_source: str = "provider_observed",
) -> ProviderChatCompletion:
    return ProviderChatCompletion(
        text="ok",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        token_usage_source=usage_source,
    )
