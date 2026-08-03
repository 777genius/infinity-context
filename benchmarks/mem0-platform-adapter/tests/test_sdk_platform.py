from __future__ import annotations

from typing import Any

import httpx
import pytest

from mem0_platform_adapter.sdk_platform import Mem0SdkPlatformPort


class FakeSdkClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.delete_response: object = {"message": "Memories deleted successfully!"}

    def add(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("add", args, kwargs))
        return {"event_id": "evt-1"}

    def get_all(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_all", (), kwargs))
        return {"results": []}

    def search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("search", args, kwargs))
        return {"results": []}

    def delete_all(self, **kwargs: Any) -> object:
        self.calls.append(("delete_all", (), kwargs))
        return self.delete_response


def test_sdk_port_forwards_timestamp_and_polls_documented_event_path() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "evt-1",
                "event_type": "ADD",
                "status": "SUCCEEDED",
                "results": [],
                "created_at": "2023-01-01T00:00:01Z",
            },
        )

    sdk = FakeSdkClient()
    event_client = httpx.Client(
        base_url="https://api.mem0.ai",
        transport=httpx.MockTransport(handler),
    )
    port = Mem0SdkPlatformPort(client=sdk, event_client=event_client)

    result = port.add(
        messages=[{"role": "user", "content": "memory"}],
        user_id="u1",
        agent_id=None,
        run_id="r1",
        metadata={"source_id": "s1"},
        timestamp=1672531200,
    )
    event = port.get_event(result["event_id"])

    assert sdk.calls[0][2]["timestamp"] == 1672531200
    assert sdk.calls[0][2]["run_id"] == "r1"
    assert event.status == "SUCCEEDED"
    assert requests[0].url.path == "/v1/event/evt-1/"


def test_sdk_port_deletes_only_the_requested_user_run_scope() -> None:
    sdk = FakeSdkClient()
    port = Mem0SdkPlatformPort(
        client=sdk,
        event_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    assert port.delete_memories(user_id="u1", run_id="r1") is True
    assert sdk.calls == [
        (
            "delete_all",
            (),
            {"filters": {"AND": [{"user_id": "u1"}, {"run_id": "r1"}]}},
        )
    ]


def test_sdk_port_forwards_bounded_pagination() -> None:
    sdk = FakeSdkClient()
    port = Mem0SdkPlatformPort(
        client=sdk,
        event_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    assert port.get_all(filters={"user_id": "u1"}, page=2, page_size=200) == {"results": []}
    assert sdk.calls == [
        (
            "get_all",
            (),
            {"filters": {"user_id": "u1"}, "page": 2, "page_size": 200},
        )
    ]


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"message": ""},
        {"message": "   "},
        {"message": None},
        {"message": False},
        {"message": "error"},
        {"message": "failure"},
        {"message": "false"},
        {"message": "request accepted"},
        {"error": "Memories deleted successfully!"},
    ],
)
def test_sdk_port_rejects_unproven_delete_ack(response: object) -> None:
    sdk = FakeSdkClient()
    sdk.delete_response = response
    port = Mem0SdkPlatformPort(
        client=sdk,
        event_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    assert port.delete_memories(user_id="u1", run_id="r1") is False


@pytest.mark.parametrize(
    "message",
    [
        "Memories deleted successfully!",
        "  MEMORIES   DELETED   SUCCESSFULLY!  ",
        "ok",
        "SUCCESS",
    ],
)
def test_sdk_port_accepts_only_known_positive_delete_ack(message: str) -> None:
    sdk = FakeSdkClient()
    sdk.delete_response = {"message": message}
    port = Mem0SdkPlatformPort(
        client=sdk,
        event_client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
    )

    assert port.delete_memories(user_id="u1", run_id="r1") is True
