from __future__ import annotations

import json

import httpx
import pytest

from mem0_oss_adapter.subscription_llm import (
    ExtractionCallLimitError,
    SubscriptionBridgeConfig,
    SubscriptionOpenAICompatibleLlm,
    UsageLedger,
    validate_loopback_bridge_url,
)
from mem0_oss_adapter.usage import UsageEvidenceError


def _subscription_llm(
    handler: httpx.MockTransport,
) -> tuple[SubscriptionOpenAICompatibleLlm, UsageLedger]:
    ledger = UsageLedger()
    config = SubscriptionBridgeConfig(
        bridge_url="http://127.0.0.1:19090/v1",
        bearer_token="explicit-token",
        mode="subscription_llm",
        usage_ledger=ledger,
        request_max_bytes=1024,
        response_max_bytes=1024,
    )
    llm = SubscriptionOpenAICompatibleLlm(config)
    llm._client.close()
    llm._client = httpx.Client(transport=handler, trust_env=False)
    return llm, ledger


def test_subscription_bridge_is_narrow_bounded_and_ledgered() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    llm, ledger = _subscription_llm(httpx.MockTransport(handler))
    with ledger.operation(
        run_id="run-1",
        mode="subscription_llm",
        max_calls=1,
        request_max_bytes=1024,
        response_max_bytes=1024,
    ):
        assert llm.generate_response([{"role": "user", "content": "extract"}]) == "{}"
        with pytest.raises(ExtractionCallLimitError):
            llm.generate_response([{"role": "user", "content": "extract again"}])
    llm.close()

    assert len(requests) == 1
    assert requests[0].url == "http://127.0.0.1:19090/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer explicit-token"
    assert json.loads(requests[0].content)["model"] == "gpt-5.6-sol"
    assert ledger.entries[-1].extraction_calls == 1
    assert ledger.entries[-1].request_bytes > 0
    assert ledger.entries[-1].response_bytes > 0
    aggregate = ledger.aggregate_for_run(run_id="run-1")
    assert aggregate.mode == "subscription_llm"
    assert aggregate.operation_count == 1
    assert aggregate.extraction_calls == 1
    assert set(aggregate.as_dict()) == {
        "mode",
        "operation_count",
        "extraction_calls",
        "request_bytes",
        "response_bytes",
        "model",
        "first_operation_at",
        "last_operation_at",
    }


def test_raw_mode_has_no_bridge_or_extraction_budget() -> None:
    ledger = UsageLedger()
    config = SubscriptionBridgeConfig(
        bridge_url=None,
        bearer_token=None,
        mode="raw_passthrough",
        usage_ledger=ledger,
        request_max_bytes=1024,
        response_max_bytes=1024,
    )
    llm = SubscriptionOpenAICompatibleLlm(config)
    with (
        ledger.operation(
            run_id="run-1",
            mode="raw_passthrough",
            max_calls=0,
            request_max_bytes=1024,
            response_max_bytes=1024,
        ),
        pytest.raises(ExtractionCallLimitError),
    ):
        llm.generate_response([{"role": "user", "content": "never call"}])
    llm.close()
    assert ledger.entries[-1].extraction_calls == 0
    aggregate = ledger.aggregate_for_run(run_id="run-1")
    assert aggregate.mode == "raw_passthrough"
    assert aggregate.extraction_calls == 0
    assert aggregate.request_bytes == 0
    assert aggregate.response_bytes == 0


def test_usage_evidence_rejects_missing_run_and_aggregates_bounded_raw_adds() -> None:
    ledger = UsageLedger()
    with pytest.raises(UsageEvidenceError, match="unavailable"):
        ledger.aggregate_for_run(run_id="missing-run")
    for _ in range(2):
        with ledger.operation(
            run_id="reused-run",
            mode="raw_passthrough",
            max_calls=0,
            request_max_bytes=1024,
            response_max_bytes=1024,
        ):
            pass

    aggregate = ledger.aggregate_for_run(run_id="reused-run")
    assert aggregate.mode == "raw_passthrough"
    assert aggregate.operation_count == 2
    assert aggregate.extraction_calls == 0
    assert aggregate.request_bytes == 0
    assert aggregate.response_bytes == 0


@pytest.mark.parametrize(
    "value", ["http://localhost:8080/v1", "https://127.0.0.1/v1", "http://8.8.8.8/v1"]
)
def test_subscription_bridge_rejects_non_loopback_or_wrong_scheme(value: str) -> None:
    with pytest.raises(ValueError):
        validate_loopback_bridge_url(value)
