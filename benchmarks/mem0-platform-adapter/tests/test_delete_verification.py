from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from mem0_platform_adapter.models import EventSnapshot
from mem0_platform_adapter.service import AdapterError, Mem0CompatibilityService, PollingPolicy


@dataclass
class DeletePlatform:
    deleted: bool = True
    readbacks: list[Mapping[str, Any]] = field(default_factory=lambda: [{"results": []}])
    calls: list[tuple[str, object]] = field(default_factory=list)
    configured: bool = True

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        self.calls.append(("delete", (user_id, run_id)))
        return self.deleted

    def get_all(
        self,
        *,
        filters: Mapping[str, Any],
        page: int,
        page_size: int,
    ) -> Mapping[str, Any]:
        self.calls.append(
            (
                "get_all",
                {"filters": filters, "page": page, "page_size": page_size},
            )
        )
        return self.readbacks.pop(0)

    def add(self, **_: Any) -> Mapping[str, Any]:
        raise AssertionError("unused")

    def get_event(self, event_id: str) -> EventSnapshot:
        raise AssertionError("unused")

    def search(self, **_: Any) -> Mapping[str, Any]:
        raise AssertionError("unused")


def test_delete_returns_proof_only_after_exact_scoped_absence_readback() -> None:
    platform = DeletePlatform()
    service = Mem0CompatibilityService(platform, sleeper=lambda _: None)

    proof = service.delete(user_id="user-1", run_id="run-1")

    assert proof.deleted is True
    assert proof.verified_absent is True
    assert platform.calls == [
        ("delete", ("user-1", "run-1")),
        (
            "get_all",
            {
                "filters": {"AND": [{"user_id": "user-1"}, {"run_id": "run-1"}]},
                "page": 1,
                "page_size": 200,
            },
        ),
    ]


def test_negative_delete_ack_fails_before_readback() -> None:
    platform = DeletePlatform(deleted=False)
    service = Mem0CompatibilityService(platform, sleeper=lambda _: None)

    with pytest.raises(AdapterError, match="not acknowledged"):
        service.delete(user_id="user-1", run_id="run-1")

    assert platform.calls == [("delete", ("user-1", "run-1"))]


def test_residual_scope_fails_after_bounded_readback() -> None:
    residual = {"results": [{"id": "still-present"}]}
    platform = DeletePlatform(readbacks=[residual, residual])
    sleeps: list[float] = []
    service = Mem0CompatibilityService(
        platform,
        policy=PollingPolicy(max_attempts=2, interval_seconds=0.25),
        sleeper=sleeps.append,
    )

    with pytest.raises(AdapterError, match="remained present"):
        service.delete(user_id="user-1", run_id="run-1")

    assert sleeps == [0.25]
    assert [name for name, _ in platform.calls] == ["delete", "get_all", "get_all"]


def test_malformed_readback_never_counts_as_absence() -> None:
    platform = DeletePlatform(readbacks=[{"results": ["malformed"]}])
    service = Mem0CompatibilityService(platform, sleeper=lambda _: None)

    with pytest.raises(AdapterError, match="malformed"):
        service.delete(user_id="user-1", run_id="run-1")


def test_delete_follows_empty_page_continuation_before_proving_absence() -> None:
    platform = DeletePlatform(
        readbacks=[
            {
                "count": 1,
                "next": "https://api.mem0.ai/v3/memories/?page=2",
                "results": [],
            },
            {
                "count": 1,
                "next": None,
                "results": [{"id": "still-present"}],
            },
        ]
    )
    service = Mem0CompatibilityService(
        platform,
        policy=PollingPolicy(max_attempts=1),
        sleeper=lambda _: None,
    )

    with pytest.raises(AdapterError, match="remained present"):
        service.delete(user_id="user-1", run_id="run-1")

    assert [payload["page"] for name, payload in platform.calls if name == "get_all"] == [1, 2]


def test_delete_fails_closed_on_count_continuation_inconsistency() -> None:
    platform = DeletePlatform(
        readbacks=[
            {
                "count": 0,
                "next": "https://api.mem0.ai/v3/memories/?page=2",
                "results": [],
            }
        ]
    )
    service = Mem0CompatibilityService(platform, sleeper=lambda _: None)

    with pytest.raises(AdapterError, match="continuation contradicted count"):
        service.delete(user_id="user-1", run_id="run-1")

    assert [name for name, _ in platform.calls] == ["delete", "get_all"]


def test_delete_rejects_repeated_non_advancing_page_two_continuation() -> None:
    platform = DeletePlatform(
        readbacks=[
            {
                "next": "https://api.mem0.ai/v3/memories/?page=2",
                "results": [],
            },
            {
                "next": "https://api.mem0.ai/v3/memories/?page=2",
                "results": [],
            },
        ]
    )
    service = Mem0CompatibilityService(platform, sleeper=lambda _: None)

    with pytest.raises(AdapterError, match="page was invalid"):
        service.delete(user_id="user-1", run_id="run-1")

    assert [payload["page"] for name, payload in platform.calls if name == "get_all"] == [1, 2]
