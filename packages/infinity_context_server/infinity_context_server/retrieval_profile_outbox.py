"""Outbox application coordination for canonical Retrieval profile projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresCanonicalProjectionSource,
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.qdrant.profile_lifecycle import QdrantRetrievalProfileProjection

from infinity_context_server.processes.outbox import ClaimedOutboxJob


@dataclass(frozen=True, slots=True)
class RetrievalProfileOutboxCoordinator:
    """Apply derived mutations while PostgreSQL owns every completion decision."""

    registry: PostgresRetrievalProfileRegistry
    source: PostgresCanonicalProjectionSource
    projection: QdrantRetrievalProfileProjection

    async def upsert(self, job: ClaimedOutboxJob, *, now: datetime) -> None:
        profile_id = _profile_id(job)
        if job.aggregate_version is None:
            raise RuntimeError("retrieval_profile_upsert_version_missing")
        profile = next(
            (item for item in await self.registry.routable() if item.profile_id == profile_id),
            None,
        )
        if profile is None:
            return
        items = await self.source.items_by_ids((job.aggregate_id,))
        if not items or any(item.canonical_version != job.aggregate_version for item in items):
            await self.compensate_stale_write(
                profile, job.aggregate_id, job.aggregate_version, now=now
            )
            return
        try:
            await self.projection.upsert_profile(profile, items)
            await self.registry.record_projection(profile_id, items, projected_at=now)
        except RuntimeError as exc:
            if str(exc) not in {
                "retrieval_profile_stale_projection_write",
                "retrieval_profile_projection_digest_drift",
                "retrieval_profile_tombstone_projection_rejected",
            }:
                raise
            for item in items:
                await self.compensate_stale_write(
                    profile,
                    item.canonical_identity,
                    item.canonical_version,
                    now=now,
                )
            raise

    async def continue_tombstone_replay(self, job: ClaimedOutboxJob, *, now: datetime) -> None:
        await self.registry.continue_tombstone_replay(_profile_id(job), now=now)

    async def compensate_stale_write(
        self, profile, canonical_id: str, stale_version: int, *, now: datetime
    ) -> None:
        tombstone_version = await self.registry.reopen_stale_projection_tombstone(
            profile.profile_id,
            canonical_id,
            stale_version=stale_version,
            now=now,
        )
        if tombstone_version is None:
            return
        await self.delete(
            ClaimedOutboxJob(
                id=0,
                event_type="vector.delete_locator_profile",
                aggregate_id=canonical_id,
                aggregate_version=tombstone_version,
                attempt_count=0,
                workload_class="projection",
                fairness_key=f"profile:{profile.profile_id}",
                payload_json={
                    "profile_id": profile.profile_id,
                    "chunk_ids": [canonical_id],
                },
                aggregate_type="locator_profile_chunk",
            ),
            now=now,
        )

    async def delete(self, job: ClaimedOutboxJob, *, now: datetime) -> None:
        profile_id = _profile_id(job)
        if job.aggregate_version is None:
            raise RuntimeError("retrieval_profile_delete_version_missing")
        authorization = await self.registry.authorize_tombstone(
            profile_id,
            job.aggregate_id,
            canonical_version=job.aggregate_version,
        )
        if authorization is None:
            return

        observation = await self.projection.observe_profile_generation(
            authorization.identity,
            job.aggregate_id,
        )
        if observation.canonical_id != job.aggregate_id:
            raise RuntimeError("retrieval_profile_delete_observation_mismatch")
        observed_version = observation.canonical_version
        if observed_version is not None and observed_version > authorization.canonical_version:
            if (
                await self.registry.authorize_tombstone(
                    profile_id,
                    job.aggregate_id,
                    canonical_version=authorization.canonical_version,
                )
                is None
            ):
                return
            raise RuntimeError("retrieval_profile_newer_generation_requires_reconciliation")

        deleted_version = observed_version
        remaining_version = None
        completed_mutation_epoch = authorization.provider_mutation_epoch
        if deleted_version is not None:
            proof = await self.projection.delete_profile_if_version(
                authorization.identity,
                (job.aggregate_id,),
                canonical_version=deleted_version,
                tombstone_authorization=authorization,
            )
            if (
                proof.canonical_ids != (job.aggregate_id,)
                or proof.canonical_version != deleted_version
                or len(proof.remaining_canonical_versions) != 1
            ):
                raise RuntimeError("retrieval_profile_delete_proof_mismatch")
            if proof.provider_mutation_epoch is None:
                raise RuntimeError("retrieval_profile_delete_epoch_proof_missing")
            completed_mutation_epoch = proof.provider_mutation_epoch
            remaining_version = proof.remaining_canonical_versions[0]

        if remaining_version is not None:
            if remaining_version > authorization.canonical_version:
                if (
                    await self.registry.authorize_tombstone(
                        profile_id,
                        job.aggregate_id,
                        canonical_version=authorization.canonical_version,
                    )
                    is None
                ):
                    return
                raise RuntimeError("retrieval_profile_newer_generation_requires_reconciliation")
            raise RuntimeError("retrieval_profile_forbidden_generation_remains")
        completed = await self.registry.complete_tombstone(
            profile_id,
            job.aggregate_id,
            canonical_version=authorization.canonical_version,
            authorized_mutation_epoch=authorization.provider_mutation_epoch,
            completed_mutation_epoch=completed_mutation_epoch,
            deleted_canonical_version=deleted_version,
            provider_observed_at=now,
            completed_at=now,
        )
        if completed:
            return
        if (
            await self.registry.authorize_tombstone(
                profile_id,
                job.aggregate_id,
                canonical_version=authorization.canonical_version,
            )
            is not None
        ):
            raise RuntimeError("retrieval_profile_tombstone_completion_fenced")


def _profile_id(job: ClaimedOutboxJob) -> str:
    value = job.payload_json.get("profile_id")
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError("retrieval_profile_id_missing")
    return value


__all__ = ("RetrievalProfileOutboxCoordinator",)
