"""Complete-operation fencing for profile-aware Retrieval queries."""

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
        registry=registry,
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
        service_revision="1" * 40,
    )
    monkeypatch.setattr(
        ProfileAwareLocatorRetrievalService,
        "_service_for_active",
        lambda _self, _active, **_kwargs: _FailingQueryDelegate(events),
    )

    with pytest.raises(RuntimeError, match="synthetic_query_failure"):
        asyncio.run(service.execute(object()))

    assert events == ["begin", "execute", "finish:lease-active"]


def test_profile_query_registers_runtime_before_admission(monkeypatch) -> None:
    events: list[str] = []
    registry = _QueryFenceRegistry(events)
    service = ProfileAwareLocatorRetrievalService(
        registry=registry,
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
        runtime_lifecycle=_StartingRuntime(events),
        service_revision="1" * 40,
    )
    monkeypatch.setattr(
        ProfileAwareLocatorRetrievalService,
        "_service_for_active",
        lambda _self, _active, **_kwargs: _SuccessfulQueryDelegate(),
    )

    assert asyncio.run(service.execute(object())) == "profile"
    assert events == ["register", "begin", "finish:lease-active"]


def test_query_cancellation_waits_for_durable_fence_close(monkeypatch) -> None:
    async def scenario() -> None:
        events: list[str] = []
        registry = _SlowCloseRegistry(events)
        delegate = _BlockingQueryDelegate(events)
        service = ProfileAwareLocatorRetrievalService(
            registry=registry,
            projection=object(),
            sessions=object(),
            query_embeddings=object(),
            service_revision="1" * 40,
        )
        monkeypatch.setattr(
            ProfileAwareLocatorRetrievalService,
            "_service_for_active",
            lambda _self, _active, **_kwargs: delegate,
        )

        query = asyncio.create_task(service.execute(object()))
        await delegate.started.wait()
        query.cancel()
        await registry.close_started.wait()
        assert not query.done()
        query.cancel()
        await asyncio.sleep(0)
        assert not query.done()
        registry.allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await query
        assert events == ["begin", "execute", "finish:lease-active"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status",
    [ProfileQueryAdmissionStatus.NO_PROFILE, ProfileQueryAdmissionStatus.UNAVAILABLE],
)
def test_absent_or_unavailable_admitted_profile_fails_closed(status) -> None:
    service = ProfileAwareLocatorRetrievalService(
        registry=_AdmissionRegistry(status),
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
        service_revision="1" * 40,
    )
    with pytest.raises(RuntimeError, match="retrieval_profile_query_unavailable"):
        asyncio.run(service.execute(object()))


def test_descriptor_without_active_profile_fails_closed() -> None:
    service = ProfileAwareLocatorRetrievalService(
        registry=_ActiveRegistry(None),
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
        service_revision="1" * 40,
    )
    with pytest.raises(RuntimeError, match="retrieval_profile_query_unavailable"):
        asyncio.run(service.descriptor())


def test_exact_close_mismatch_fails_closed_and_is_observable(monkeypatch) -> None:
    diagnostics = _Diagnostics()
    registry = _QueryFenceRegistry([], close_error=True)
    service = ProfileAwareLocatorRetrievalService(
        registry=registry,
        projection=object(),
        sessions=object(),
        query_embeddings=object(),
        service_revision="1" * 40,
        diagnostics=diagnostics,
    )
    monkeypatch.setattr(
        ProfileAwareLocatorRetrievalService,
        "_service_for_active",
        lambda _self, _active, **_kwargs: _SuccessfulQueryDelegate(),
    )
    with pytest.raises(RuntimeError, match="query_fenced"):
        asyncio.run(service.execute(object()))
    assert diagnostics.events == [("active-a", "query_fence_close_failed")]


def test_admitted_query_does_not_repeat_cold_provider_health_probe() -> None:
    identity = RetrievalProfileIdentity(
        "active-a", "generation-active", "a" * 64, "collection-active"
    )
    service = ProfileAwareLocatorRetrievalService(
        registry=object(),
        projection=_NeverProbeProjection(),
        sessions=object(),
        query_embeddings=object(),
        service_revision="1" * 40,
    )

    descriptor = asyncio.run(
        service._service_for_active(identity, admission_proven=True).descriptor()
    )

    assert all(lane.healthy for lane in descriptor.provider_lanes)
    assert all(lane.profile_qualified for lane in descriptor.provider_lanes)


class _NeverProbeProjection:
    def adapter_for(self, _identity):
        return _NeverProbeAdapter()


class _NeverProbeAdapter:
    async def capabilities(self):  # pragma: no cover - fail-closed assertion
        raise AssertionError("admitted Retrieval repeated a cold provider health probe")


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


class _SlowCloseRegistry(_QueryFenceRegistry):
    def __init__(self, events):
        super().__init__(events)
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def finish_profile_query(self, *args, **kwargs):
        self.close_started.set()
        await self.allow_close.wait()
        await super().finish_profile_query(*args, **kwargs)


class _FailingQueryDelegate:
    def __init__(self, events):
        self.events = events

    async def execute(self, _request):
        self.events.append("execute")
        raise RuntimeError("synthetic_query_failure")


class _SuccessfulQueryDelegate:
    async def execute(self, _request):
        return "profile"


class _BlockingQueryDelegate:
    def __init__(self, events):
        self.events = events
        self.started = asyncio.Event()

    async def execute(self, _request):
        self.events.append("execute")
        self.started.set()
        await asyncio.Future()


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


class _ActiveRegistry:
    def __init__(self, active):
        self._active = active

    async def active(self):
        return self._active


class _Diagnostics:
    def __init__(self):
        self.events = []

    def record(self, profile_id, event):
        self.events.append((profile_id, event))
