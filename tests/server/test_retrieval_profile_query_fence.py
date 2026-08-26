"""Complete-operation fencing for profile-aware Retrieval V2 queries."""

from __future__ import annotations

import asyncio

import pytest
from infinity_context_core.features.context_building.public import (
    ProfileQueryAdmission,
    ProfileQueryAdmissionStatus,
    RetrievalProfileIdentity,
)
from infinity_context_server.retrieval_profile_composition import (
    ProfileAwareLocatorRetrievalService,
)


def test_profile_query_fence_spans_delegate_and_releases_on_failure(monkeypatch) -> None:
    events: list[str] = []
    registry = _QueryFenceRegistry(events)
    service = ProfileAwareLocatorRetrievalService(
        fallback=object(),
        registry=registry,
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
    )
    monkeypatch.setattr(
        ProfileAwareLocatorRetrievalService,
        "_service_for_active",
        lambda _self, _active: _FailingQueryDelegate(events),
    )

    with pytest.raises(RuntimeError, match="synthetic_query_failure"):
        asyncio.run(service.execute(object()))

    assert events == ["begin", "execute", "finish:lease-active"]


def test_profile_query_registers_runtime_before_admission(monkeypatch) -> None:
    events: list[str] = []
    registry = _QueryFenceRegistry(events)
    service = ProfileAwareLocatorRetrievalService(
        fallback=object(),
        registry=registry,
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
        runtime_lifecycle=_StartingRuntime(events),
    )
    monkeypatch.setattr(
        ProfileAwareLocatorRetrievalService,
        "_service_for_active",
        lambda _self, _active: _SuccessfulQueryDelegate(),
    )

    assert asyncio.run(service.execute(object())) == "profile"
    assert events == ["register", "begin", "finish:lease-active"]


def test_fallback_requires_atomic_no_profile_and_unavailable_fails_closed() -> None:
    fallback = _Fallback()
    no_profile = ProfileAwareLocatorRetrievalService(
        fallback=fallback,
        registry=_AdmissionRegistry(ProfileQueryAdmissionStatus.NO_PROFILE),
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
    )
    assert asyncio.run(no_profile.execute(object())) == "fallback"
    assert fallback.calls == 1

    unavailable = ProfileAwareLocatorRetrievalService(
        fallback=fallback,
        registry=_AdmissionRegistry(ProfileQueryAdmissionStatus.UNAVAILABLE),
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
    )
    with pytest.raises(RuntimeError, match="query_unavailable"):
        asyncio.run(unavailable.execute(object()))
    assert fallback.calls == 1


def test_exact_close_mismatch_fails_closed_and_is_observable(monkeypatch) -> None:
    diagnostics = _Diagnostics()
    fallback = _Fallback(diagnostics)
    registry = _QueryFenceRegistry([], close_error=True)
    service = ProfileAwareLocatorRetrievalService(
        fallback=fallback,
        registry=registry,
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
    )
    monkeypatch.setattr(
        ProfileAwareLocatorRetrievalService,
        "_service_for_active",
        lambda _self, _active: _SuccessfulQueryDelegate(),
    )
    with pytest.raises(RuntimeError, match="query_fenced"):
        asyncio.run(service.execute(object()))
    assert diagnostics.events == [("active-a", "query_fence_close_failed")]


class _QueryFenceRegistry:
    identity = RetrievalProfileIdentity(
        "active-a", "generation-active", "a" * 64, "collection-active"
    )

    def __init__(self, events, close_error=False):
        self.events = events
        self.close_error = close_error

    async def begin_profile_query(self, operation_id, *, owner, now, expires_at):
        assert operation_id.startswith("profile-query-")
        assert owner.instance_id.startswith("retrieval-runtime-")
        assert expires_at > now
        self.events.append("begin")
        return ProfileQueryAdmission(
            ProfileQueryAdmissionStatus.ADMITTED, self.identity, "lease-active"
        )

    async def finish_profile_query(self, profile_id, operation_id, *, owner, activation_lease_id):
        assert profile_id == self.identity.profile_id
        assert owner.instance_id.startswith("retrieval-runtime-")
        assert operation_id.startswith("profile-query-")
        if self.close_error:
            raise RuntimeError("retrieval_profile_query_fenced")
        self.events.append(f"finish:{activation_lease_id}")


class _FailingQueryDelegate:
    def __init__(self, events):
        self.events = events

    async def execute(self, _request):
        self.events.append("execute")
        raise RuntimeError("synthetic_query_failure")


class _SuccessfulQueryDelegate:
    async def execute(self, _request):
        return "profile"


class _StartingRuntime:
    def __init__(self, events):
        self.events = events

    async def start(self, *, now):
        assert now.tzinfo is not None
        self.events.append("register")


class _AdmissionRegistry:
    def __init__(self, status):
        self.status = status

    async def begin_profile_query(self, *_args, **_kwargs):
        return ProfileQueryAdmission(self.status)


class _Fallback:
    def __init__(self, diagnostics=None):
        self.calls = 0
        self.diagnostics = diagnostics

    async def execute(self, _request):
        self.calls += 1
        return "fallback"


class _Diagnostics:
    def __init__(self):
        self.events = []

    def record(self, profile_id, event):
        self.events.append((profile_id, event))
