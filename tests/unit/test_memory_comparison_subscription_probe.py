from __future__ import annotations

import copy
import json
import pickle
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server import memory_comparison_subscription_probe as probe
from infinity_context_server.memory_comparison_subscription_chat import (
    SubscriptionRuntimeChatCompletions,
)
from infinity_context_server.memory_comparison_subscription_live_probe import (
    SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
    run_subscription_runtime_live_probe,
)


def _issue(
    *,
    checked_at: datetime | None = None,
    bearer_token: str | None = None,
) -> probe.VerifiedSubscriptionRuntimeProbe:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 2},
            },
        )

    adapter = SubscriptionRuntimeChatCompletions(
        bearer_token=bearer_token,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    return run_subscription_runtime_live_probe(
        adapter,
        expected_route=adapter.route_attestation,
        model="gpt-5.6-sol",
        clock=lambda: checked_at or datetime.now(UTC),
    )


def test_only_concrete_live_probe_can_issue_sealed_evidence() -> None:
    assert not hasattr(probe, "issue_verified_subscription_runtime_probe")
    assert "issue_verified_subscription_runtime_probe" not in probe.__all__

    with pytest.raises(probe.SubscriptionRuntimeProbeError, match="authoritatively"):
        probe.VerifiedSubscriptionRuntimeProbe(commitment="0" * 64, _token=object())


def test_probe_is_exactly_one_call_sealed_fresh_and_integrity_checked() -> None:
    now = datetime.now(UTC)
    evidence = _issue(checked_at=now)

    observation = probe.inspect_verified_subscription_runtime_probe(
        evidence,
        now=now + timedelta(seconds=1),
    )
    assert observation.model == "gpt-5.6-sol"
    assert observation.total_tokens == 42
    assert observation.public_payload()["provider_call_count"] == 1
    assert repr(evidence) == "VerifiedSubscriptionRuntimeProbe(<sealed>)"
    assert "READY" not in json.dumps(observation.public_payload(), sort_keys=True)

    with pytest.raises(probe.SubscriptionRuntimeProbeError, match="stale"):
        probe.inspect_verified_subscription_runtime_probe(
            evidence,
            now=now + timedelta(seconds=probe.SUBSCRIPTION_RUNTIME_PROBE_MAX_AGE_SECONDS + 1),
        )
    with pytest.raises(TypeError):
        copy.copy(evidence)
    with pytest.raises(TypeError):
        pickle.dumps(evidence)
    with pytest.raises(TypeError):

        class _Subclass(probe.VerifiedSubscriptionRuntimeProbe):
            pass

    tampered = _issue(checked_at=now)
    object.__setattr__(
        tampered,
        "_VerifiedSubscriptionRuntimeProbe__commitment",
        "0" * 64,
    )
    with pytest.raises(probe.SubscriptionRuntimeProbeError, match="integrity"):
        probe.inspect_verified_subscription_runtime_probe(tampered, now=now)


@pytest.mark.parametrize("bearer_token", (None, "private-test-token"))
def test_live_bridge_accepts_optional_credential_commitment(
    bearer_token: str | None,
) -> None:
    now = datetime.now(UTC)
    evidence = _issue(checked_at=now, bearer_token=bearer_token)

    observation = probe.inspect_verified_subscription_runtime_probe(evidence, now=now)

    assert (
        observation.route.credential_binding_id is not None
        if bearer_token
        else (observation.route.credential_binding_id is None)
    )


def test_probe_reservation_is_atomic_one_shot_but_remains_inspectable() -> None:
    now = datetime.now(UTC)
    evidence = _issue(checked_at=now)

    reserved = probe.reserve_verified_subscription_runtime_probe(evidence, now=now)
    inspected = probe.inspect_verified_subscription_runtime_probe(evidence, now=now)

    assert reserved is inspected
    with pytest.raises(probe.SubscriptionRuntimeProbeError, match="already reserved"):
        probe.reserve_verified_subscription_runtime_probe(evidence, now=now)


def test_probe_rejects_future_live_observation() -> None:
    now = datetime.now(UTC)
    evidence = _issue(checked_at=now + timedelta(seconds=2))

    with pytest.raises(probe.SubscriptionRuntimeProbeError, match="future"):
        probe.inspect_verified_subscription_runtime_probe(evidence, now=now)
