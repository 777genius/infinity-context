from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from infinity_context_core.features.context_building.public import (
    CanonicalProjectionItem,
    ExactVersionDeletionProof,
    ProfileTombstoneDeleteAuthorization,
    ProjectedGenerationObservation,
    RetrievalProfileIdentity,
)
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.retrieval_profile_outbox import RetrievalProfileOutboxCoordinator

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def test_profile_outbox_upsert_targets_only_named_routable_profile() -> None:
    registry = _Registry()
    projection = _Projection()
    asyncio.run(_coordinator(registry, projection).upsert(_upsert_job(), now=NOW))

    assert projection.upserts == [("profile-a", "chunk-a", 2)]
    assert registry.receipts == [("profile-a", "chunk-a", 2)]


def test_profile_outbox_stale_delete_is_a_noop() -> None:
    registry = _Registry()
    registry.authorized = False
    projection = _Projection(current_version=1)

    asyncio.run(_coordinator(registry, projection).delete(_delete_job(2), now=NOW))

    assert projection.observations == []
    assert projection.deletes == []
    assert registry.completed == []


@pytest.mark.parametrize("observed_version", [1, 3])
def test_profile_outbox_deletes_actual_older_or_equal_generation(
    observed_version: int,
) -> None:
    registry = _Registry()
    projection = _Projection(current_version=observed_version)

    asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.deletes == [("profile-a", ("chunk-a",), observed_version)]
    assert registry.completed == [("profile-a", "chunk-a", 3, observed_version, NOW)]


def test_profile_outbox_canonical_three_deletes_receipted_generation_one() -> None:
    registry = _Registry()
    projection = _Projection(current_version=1)

    asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.deletes == [("profile-a", ("chunk-a",), 1)]
    assert registry.completed == [("profile-a", "chunk-a", 3, 1, NOW)]


def test_profile_outbox_absence_after_false_completion_needs_no_generation_guess() -> None:
    registry = _Registry()
    projection = _Projection(current_version=None)

    asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.deletes == []
    assert registry.completed == [("profile-a", "chunk-a", 3, None, NOW)]


def test_profile_outbox_preserves_newer_superseding_generation() -> None:
    registry = _Registry()
    registry.invalidate_on_reauthorize = True
    projection = _Projection(current_version=4)

    asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.deletes == []
    assert projection.current_version == 4
    assert registry.completed == []


def test_profile_outbox_delete_ineffective_keeps_tombstone_pending() -> None:
    registry = _Registry()
    projection = _Projection(current_version=1, ineffective_delete=True)

    with pytest.raises(RuntimeError, match="retrieval_profile_forbidden_generation_remains"):
        asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.current_version == 1
    assert registry.completed == []


def test_profile_outbox_newer_generation_racing_delete_is_preserved() -> None:
    registry = _Registry()
    registry.invalidate_on_reauthorize = True
    projection = _Projection(current_version=1, remaining_after_delete=4)

    asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.deletes == [("profile-a", ("chunk-a",), 1)]
    assert projection.current_version == 4
    assert registry.completed == []


def test_profile_outbox_observation_failure_is_not_completion() -> None:
    registry = _Registry()
    projection = _Projection(current_version=1, observation_error=True)

    with pytest.raises(RuntimeError, match="injected_observation_failure"):
        asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert projection.deletes == []
    assert registry.completed == []


def test_profile_outbox_crash_after_provider_effect_replays_from_observed_absence() -> None:
    registry = _Registry()
    projection = _Projection(current_version=1, crash_after_effect=True)
    coordinator = _coordinator(registry, projection)

    with pytest.raises(RuntimeError, match="injected_crash_after_provider_effect"):
        asyncio.run(coordinator.delete(_delete_job(3), now=NOW))
    assert projection.current_version is None
    assert registry.completed == []

    asyncio.run(coordinator.delete(_delete_job(3), now=NOW))
    assert projection.deletes == [("profile-a", ("chunk-a",), 1)]
    assert registry.completed == [("profile-a", "chunk-a", 3, None, NOW)]


def test_profile_outbox_rejects_unbound_absence_proof_without_completion() -> None:
    registry = _Registry()
    projection = _Projection(current_version=1, proof_version=2)

    with pytest.raises(RuntimeError, match="retrieval_profile_delete_proof_mismatch"):
        asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert registry.completed == []


def test_profile_outbox_rejects_delete_without_provider_epoch_proof() -> None:
    registry = _Registry()
    projection = _Projection(current_version=1, omit_mutation_epoch=True)

    with pytest.raises(RuntimeError, match="retrieval_profile_delete_epoch_proof_missing"):
        asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert registry.completed == []


def test_profile_outbox_retries_when_epoch_changes_before_completion() -> None:
    registry = _Registry()
    registry.complete_result = False
    projection = _Projection(current_version=1)

    with pytest.raises(RuntimeError, match="retrieval_profile_tombstone_completion_fenced"):
        asyncio.run(_coordinator(registry, projection).delete(_delete_job(3), now=NOW))

    assert registry.completed == []
    assert registry.authorization_calls == 2


def test_profile_outbox_upsert_cleans_up_a_canonical_race_by_version() -> None:
    registry = _Registry()
    registry.stale_upsert = True
    projection = _Projection(current_version=2)

    with pytest.raises(RuntimeError, match="retrieval_profile_stale_projection_write"):
        asyncio.run(_coordinator(registry, projection).upsert(_upsert_job(), now=NOW))

    assert projection.deletes == [("profile-a", ("chunk-a",), 2)]
    assert registry.receipts == []


class _Registry:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")

    def __init__(self) -> None:
        self.receipts: list[tuple[str, str, int]] = []
        self.completed: list[tuple[str, str, int, int | None, datetime]] = []
        self.authorized = True
        self.stale_upsert = False
        self.invalidate_on_reauthorize = False
        self.authorization_calls = 0
        self.complete_result = True

    async def routable(self):
        return (self.identity,)

    async def record_projection(self, profile_id, items, *, projected_at):
        del projected_at
        if self.stale_upsert:
            raise RuntimeError("retrieval_profile_stale_projection_write")
        self.receipts.extend(
            (profile_id, item.canonical_identity, item.canonical_version) for item in items
        )

    async def authorize_tombstone(self, profile_id, chunk_id, *, canonical_version):
        del profile_id
        self.authorization_calls += 1
        if self.invalidate_on_reauthorize and self.authorization_calls > 1:
            return None
        return (
            ProfileTombstoneDeleteAuthorization(self.identity, chunk_id, canonical_version, 4)
            if self.authorized
            else None
        )

    async def complete_tombstone(
        self,
        profile_id,
        chunk_id,
        *,
        canonical_version,
        authorized_mutation_epoch,
        completed_mutation_epoch,
        deleted_canonical_version,
        provider_observed_at,
        completed_at,
    ):
        assert provider_observed_at == completed_at
        assert authorized_mutation_epoch == 4
        assert completed_mutation_epoch == (4 if deleted_canonical_version is None else 6)
        if not self.complete_result:
            return False
        self.completed.append(
            (
                profile_id,
                chunk_id,
                canonical_version,
                deleted_canonical_version,
                completed_at,
            )
        )
        return True


class _Source:
    async def items_by_ids(self, canonical_ids):
        del canonical_ids
        return (
            CanonicalProjectionItem(
                "chunk-a",
                2,
                9,
                "b" * 64,
                "space-a",
                "scope-a",
                None,
                "projection text",
                (),
            ),
        )


class _Projection:
    def __init__(
        self,
        *,
        current_version: int | None = 1,
        proof_version: int | None = None,
        ineffective_delete: bool = False,
        remaining_after_delete: int | None = None,
        observation_error: bool = False,
        crash_after_effect: bool = False,
        omit_mutation_epoch: bool = False,
    ) -> None:
        self.current_version = current_version
        self.proof_version = proof_version
        self.ineffective_delete = ineffective_delete
        self.remaining_after_delete = remaining_after_delete
        self.observation_error = observation_error
        self.crash_after_effect = crash_after_effect
        self.omit_mutation_epoch = omit_mutation_epoch
        self.upserts: list[tuple[str, str, int]] = []
        self.deletes: list[tuple[str, tuple[str, ...], int]] = []
        self.observations: list[tuple[str, str]] = []

    async def upsert_profile(self, identity, items):
        self.upserts.extend(
            (identity.profile_id, item.canonical_identity, item.canonical_version) for item in items
        )

    async def observe_profile_generation(self, identity, canonical_id):
        if self.observation_error:
            raise RuntimeError("injected_observation_failure")
        self.observations.append((identity.profile_id, canonical_id))
        return ProjectedGenerationObservation(canonical_id, self.current_version)

    async def delete_profile_if_version(
        self,
        identity,
        canonical_ids,
        *,
        canonical_version,
        tombstone_authorization=None,
    ):
        self.deletes.append((identity.profile_id, canonical_ids, canonical_version))
        if self.current_version == canonical_version and not self.ineffective_delete:
            self.current_version = self.remaining_after_delete
        if self.crash_after_effect:
            self.crash_after_effect = False
            raise RuntimeError("injected_crash_after_provider_effect")
        return ExactVersionDeletionProof(
            canonical_ids,
            canonical_version if self.proof_version is None else self.proof_version,
            tuple(self.current_version for _ in canonical_ids),
            None
            if self.omit_mutation_epoch
            else (
                tombstone_authorization.provider_mutation_epoch + 2
                if tombstone_authorization is not None
                else None
            ),
        )


def _coordinator(registry: _Registry, projection: _Projection):
    return RetrievalProfileOutboxCoordinator(registry, _Source(), projection)


def _delete_job(canonical_version: int) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=3,
        event_type="vector.delete_locator_profile",
        aggregate_id="chunk-a",
        aggregate_version=canonical_version,
        attempt_count=0,
        workload_class="projection",
        fairness_key="profile:profile-a",
        payload_json={"profile_id": "profile-a", "chunk_ids": ["chunk-a"]},
    )


def _upsert_job() -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=1,
        event_type="vector.upsert_locator_profile",
        aggregate_id="chunk-a",
        aggregate_version=2,
        attempt_count=0,
        workload_class="projection",
        fairness_key="profile:profile-a",
        payload_json={"profile_id": "profile-a", "chunk_id": "chunk-a"},
    )
