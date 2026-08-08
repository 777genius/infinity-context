"""SDK contract for externally retryable suggestion approval."""

import httpx
import pytest
from infinity_context_sdk import InfinityContextClient


def test_sdk_sends_suggestion_approval_idempotency_key() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        return httpx.Response(200, json={"data": {"suggestion": {"id": "sug-1"}}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    client.approve_suggestion(
        "sug-1",
        reason="reviewed",
        idempotency_key="approve-sug-1",
    )

    assert seen == {
        "path": "/v1/suggestions/sug-1/approve",
        "idempotency_key": "approve-sug-1",
    }


@pytest.mark.parametrize("action", ("reject", "expire"))
def test_sdk_sends_terminal_review_idempotency_key(action: str) -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        return httpx.Response(200, json={"data": {"id": "sug-1"}})

    client = InfinityContextClient(
        base_url="http://memory.test",
        token="test-token",
        transport=httpx.MockTransport(handler),
    )
    getattr(client, f"{action}_suggestion")(
        "sug-1",
        reason="reviewed",
        idempotency_key=f"{action}-sug-1",
    )

    assert seen == {
        "path": f"/v1/suggestions/sug-1/{action}",
        "idempotency_key": f"{action}-sug-1",
    }
