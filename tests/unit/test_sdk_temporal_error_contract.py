from datetime import UTC, datetime

import httpx
import pytest
from infinity_context_sdk import InfinityContextClient, InfinityContextError


def _confirm(client: InfinityContextClient) -> None:
    client.confirm_fact(
        "fact-1",
        expected_version=1,
        confirmed_at=datetime(2026, 8, 5, tzinfo=UTC),
        confirmation_basis="primary_evidence",
        evidence_refs=[{"source_type": "manual", "source_id": "review-1"}],
        idempotency_key="same-key-on-retry",
        actor_id="reviewer-1",
        space_id="space-1",
        memory_scope_id="scope-1",
    )


@pytest.mark.parametrize(
    "handler",
    (
        lambda _request: httpx.Response(503, json={"error": {}}),
        lambda _request: httpx.Response(200, text="not-json"),
    ),
)
def test_sdk_marks_ambiguous_temporal_mutation_response_unknown(handler) -> None:
    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InfinityContextError) as raised:
        _confirm(client)

    assert raised.value.retryable is True
    assert raised.value.unknown_commit_state is True


def test_sdk_connect_failure_is_known_not_committed_for_mutation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InfinityContextError) as raised:
        _confirm(client)

    assert raised.value.retryable is True
    assert raised.value.unknown_commit_state is False
