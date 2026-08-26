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
        profile = next(
            (item for item in await self.registry.routable() if item.profile_id == profile_id),
            None,
        )
        if profile is None:
            return
        items = await self.source.items_by_ids((job.aggregate_id,))
        if not items:
            return
        await self.projection.upsert_profile(profile, items)
        try:
            await self.registry.record_projection(profile_id, items, projected_at=now)
        except RuntimeError as exc:
            if str(exc) not in {
                "retrieval_profile_stale_projection_write",
                "retrieval_profile_projection_digest_drift",
            }:
                raise
            for version in sorted({item.canonical_version for item in items}):
                await self.projection.delete_profile_if_version(
                    profile,
                    tuple(
                        item.canonical_identity
                        for item in items
                        if item.canonical_version == version
                    ),
                    canonical_version=version,
                )
            raise

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
            return

        deleted_version = observed_version
        remaining_version = None
        if deleted_version is not None:
            proof = await self.projection.delete_profile_if_version(
                authorization.identity,
                (job.aggregate_id,),
                canonical_version=deleted_version,
            )
            if (
                proof.canonical_ids != (job.aggregate_id,)
                or proof.canonical_version != deleted_version
                or len(proof.remaining_canonical_versions) != 1
            ):
                raise RuntimeError("retrieval_profile_delete_proof_mismatch")
            remaining_version = proof.remaining_canonical_versions[0]

        if remaining_version is not None:
            if remaining_version > authorization.canonical_version:
                return
            raise RuntimeError("retrieval_profile_forbidden_generation_remains")
        await self.registry.complete_tombstone(
            profile_id,
            job.aggregate_id,
            canonical_version=authorization.canonical_version,
            deleted_canonical_version=deleted_version,
            provider_observed_at=now,
            completed_at=now,
        )


def _profile_id(job: ClaimedOutboxJob) -> str:
    value = job.payload_json.get("profile_id")
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError("retrieval_profile_id_missing")
    return value


__all__ = ("RetrievalProfileOutboxCoordinator",)
