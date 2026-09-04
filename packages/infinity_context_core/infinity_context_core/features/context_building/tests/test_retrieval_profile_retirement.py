from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from infinity_context_core.features.context_building.application.retrieval_profile_retirement import (  # noqa: E501
    RetrievalProfileRetirement,
)
from infinity_context_core.features.context_building.domain.retrieval_profile_lifecycle import (
    RetainedProfile,
    RetrievalProfileIdentity,
    retained_profiles_to_retire,
)
from infinity_context_core.features.context_building.ports.retrieval_profile_lifecycle import (
    ProfileCleanup,
    ProfileCollectionDeleteAuthorization,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)
IDENTITY = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "collection_a")


def test_retained_bound_deterministically_selects_oldest_profiles() -> None:
    profiles = (
        RetainedProfile("profile-c", NOW),
        RetainedProfile("profile-b", NOW - timedelta(days=1)),
        RetainedProfile("profile-a", NOW - timedelta(days=1)),
    )
    assert retained_profiles_to_retire(profiles, maximum_retained=1) == (
        "profile-a",
        "profile-b",
    )


def test_cleanup_is_resumable_and_repeated_completion_is_idempotent() -> None:
    registry = _Registry()
    collections = _Collections()
    lifecycle = RetrievalProfileRetirement(registry, collections, _Diagnostics())

    first = asyncio.run(lifecycle.delete("profile-a", now=NOW))
    second = asyncio.run(lifecycle.cleanup_step("profile-a", now=NOW))
    third = asyncio.run(lifecycle.cleanup_step("profile-a", now=NOW))
    repeated = asyncio.run(lifecycle.cleanup_step("profile-a", now=NOW))

    assert [first.phase, second.phase, third.phase, repeated.phase] == [
        "collection_deleted",
        "postgres_cleaned",
        "complete",
        "complete",
    ]
    assert collections.deleted == ["profile-a"]
    assert registry.postgres_cleanup_count == 1


def test_provider_failure_resumes_after_restart() -> None:
    registry = _Registry()
    collections = _Collections()
    collections.fail_once = True
    lifecycle = RetrievalProfileRetirement(registry, collections, _Diagnostics())

    try:
        asyncio.run(lifecycle.delete("profile-a", now=NOW))
    except RuntimeError as exc:
        assert str(exc) == "retrieval_profile_qdrant_collection_delete_failed"
    else:  # pragma: no cover
        raise AssertionError("provider failure was acknowledged")

    assert registry.phase == "requested"
    assert registry.last_error_code == "retrieval_profile_qdrant_collection_delete_failed"
    restarted = RetrievalProfileRetirement(registry, collections, _Diagnostics())
    assert asyncio.run(restarted.cleanup_step("profile-a", now=NOW)).phase == ("collection_deleted")


def test_crash_after_collection_delete_repeats_provider_delete_before_advancing() -> None:
    registry = _Registry()
    registry.fail_mark_once = True
    collections = _Collections()
    lifecycle = RetrievalProfileRetirement(registry, collections, _Diagnostics())

    try:
        asyncio.run(lifecycle.delete("profile-a", now=NOW))
    except RuntimeError as exc:
        assert str(exc) == "retrieval_profile_cleanup_phase_write_failed"
    else:  # pragma: no cover
        raise AssertionError("durable phase failure was acknowledged")

    assert registry.phase == "requested"
    restarted = RetrievalProfileRetirement(registry, collections, _Diagnostics())
    assert asyncio.run(restarted.cleanup_step("profile-a", now=NOW)).phase == ("collection_deleted")
    assert collections.deleted == ["profile-a", "profile-a"]


def test_reconcile_is_bounded_and_contains_per_profile_failure() -> None:
    registry = _Registry()
    collections = _Collections()
    lifecycle = RetrievalProfileRetirement(registry, collections, _Diagnostics())
    result = asyncio.run(lifecycle.reconcile(now=NOW, limit=1))
    assert result.examined == 1
    assert result.pending == 1
    assert collections.deleted == ["profile-a"]


class _Registry:
    def __init__(self):
        self.phase = "requested"
        self.attempt_count = 0
        self.last_error_code = None
        self.postgres_cleanup_count = 0
        self.fail_mark_once = False

    def value(self):
        return ProfileCleanup(IDENTITY, self.phase, self.attempt_count, self.last_error_code)

    async def request_cleanup(self, profile_id, *, now):
        return self.value()

    async def cleanup(self, profile_id):
        return self.value()

    async def cleanup_candidates(self, *, limit):
        return ("profile-a",)[:limit]

    async def reconcile_retained_profiles(self, *, now, maximum_retained):
        return ()

    async def authorize_collection_delete(self, profile_id, *, now):
        self.attempt_count += 1
        return ProfileCollectionDeleteAuthorization(IDENTITY, "delete-token", 3)

    async def mark_collection_deleted(self, authorization, *, now):
        if self.fail_mark_once:
            self.fail_mark_once = False
            raise RuntimeError("retrieval_profile_cleanup_phase_write_failed")
        self.phase = "collection_deleted"
        self.last_error_code = None

    async def cleanup_postgres(self, profile_id, *, now):
        self.postgres_cleanup_count += 1
        self.phase = "postgres_cleaned"

    async def complete_cleanup(self, profile_id, *, now):
        self.phase = "complete"

    async def record_cleanup_failure(self, profile_id, *, error_code, now):
        self.last_error_code = error_code


class _Collections:
    def __init__(self):
        self.deleted = []
        self.fail_once = False

    async def delete_profile(self, authorization):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("retrieval_profile_qdrant_collection_delete_failed")
        self.deleted.append(authorization.identity.profile_id)


class _Diagnostics:
    def record(self, profile_id, event, value=1):
        pass
