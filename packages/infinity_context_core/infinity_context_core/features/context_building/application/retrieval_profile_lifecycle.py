"""Use cases for creating, rebuilding and activating Retrieval V2 profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from infinity_context_core.features.context_building.domain.retrieval_profile_lifecycle import (
    ProfileActivationDecision,
    ProfileActivationEvidence,
    ProfileAttestationLease,
    RetrievalProfileIdentity,
    assess_profile_activation,
)
from infinity_context_core.features.context_building.ports.retrieval_profile_lifecycle import (
    CanonicalProjectionSourcePort,
    RetrievalProfileDiagnosticsPort,
    RetrievalProfileProjectionPort,
    RetrievalProfileRegistryPort,
    RuntimeFenceOwner,
)


@dataclass(frozen=True, slots=True)
class RebuildPageResult:
    profile_id: str
    projected_count: int
    complete: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class RetrievalProfileLifecycle:
    registry: RetrievalProfileRegistryPort
    source: CanonicalProjectionSourcePort
    projection: RetrievalProfileProjectionPort
    diagnostics: RetrievalProfileDiagnosticsPort
    page_size: int = 256
    maximum_queue_lag: timedelta = timedelta(minutes=5)
    activation_lease_ttl: timedelta = timedelta(seconds=30)
    maximum_retained: int = 2
    runtime_owner: RuntimeFenceOwner | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.page_size, int)
            or isinstance(self.page_size, bool)
            or not 1 <= self.page_size <= 1000
        ):
            raise ValueError("Retrieval profile page_size must be within 1..1000")
        if self.maximum_queue_lag <= timedelta(0):
            raise ValueError("Retrieval profile maximum_queue_lag must be positive")
        if not timedelta(seconds=1) <= self.activation_lease_ttl <= timedelta(minutes=5):
            raise ValueError("Retrieval profile lease TTL must be within 1s..5m")
        if not 0 <= self.maximum_retained <= 100:
            raise ValueError("Retrieval profile maximum_retained must be within 0..100")
        if not callable(getattr(self.diagnostics, "record", None)):
            raise ValueError("Retrieval profile diagnostics port is invalid")

    async def create_building(self, identity: RetrievalProfileIdentity, *, now: datetime) -> None:
        await self.registry.create_building(identity, now=now)
        self.diagnostics.record(identity.profile_id, "profile_building_created")

    async def rebuild_page(self, *, now: datetime) -> RebuildPageResult:
        profile = await self.registry.building()
        if profile is None:
            raise RuntimeError("retrieval_profile_building_missing")
        if await self.registry.backfill_complete(profile.profile_id):
            return RebuildPageResult(profile.profile_id, 0, True, None)
        await self.projection.prepare_profile(profile)
        cursor = await self.registry.backfill_cursor(profile.profile_id)
        page = await self.source.page_eligible(after=cursor, limit=self.page_size)
        if page.items:
            await self.projection.upsert_profile(profile, page.items)
            try:
                await self.registry.record_projection(
                    profile.profile_id, page.items, projected_at=now
                )
            except RuntimeError as exc:
                if str(exc) not in {
                    "retrieval_profile_stale_projection_write",
                    "retrieval_profile_projection_digest_drift",
                }:
                    raise
                await self._remove_stale_projection(profile, page.items)
                raise
        complete = page.next_cursor is None
        await self.registry.checkpoint_backfill(
            profile.profile_id,
            previous_cursor=cursor,
            cursor=page.next_cursor,
            watermark=page.canonical_watermark,
            complete=complete,
            now=now,
        )
        self.diagnostics.record(profile.profile_id, "backfill_projected", len(page.items))
        return RebuildPageResult(profile.profile_id, len(page.items), complete, page.next_cursor)

    async def qualify(
        self, profile_id: str, *, lease_id: str, mutation_epoch: int = 0, now: datetime
    ) -> tuple[ProfileActivationDecision, ProfileAttestationLease | None]:
        evidence = await self.registry.activation_evidence(profile_id, now=now)
        self.diagnostics.record(profile_id, "coverage_expected", evidence.coverage.expected_count)
        self.diagnostics.record(profile_id, "coverage_projected", evidence.coverage.projected_count)
        self.diagnostics.record(
            profile_id, "coverage_watermark", evidence.coverage.canonical_watermark
        )
        self.diagnostics.record(
            profile_id,
            "projected_watermark",
            evidence.coverage.projected_watermark,
        )
        self.diagnostics.record(profile_id, "queue_retry", evidence.queue.retry_count)
        self.diagnostics.record(profile_id, "queue_dead", evidence.queue.dead_count)
        oldest_lag_ms = (
            0
            if evidence.queue.oldest_pending_at is None
            else max(
                0,
                int(
                    (evidence.queue.observed_at - evidence.queue.oldest_pending_at).total_seconds()
                    * 1000
                ),
            )
        )
        self.diagnostics.record(profile_id, "queue_oldest_lag_ms", oldest_lag_ms)
        self.diagnostics.record(
            profile_id, "tombstone_required", evidence.tombstones.required_count
        )
        self.diagnostics.record(
            profile_id, "tombstone_completed", evidence.tombstones.completed_count
        )
        decision = assess_profile_activation(evidence, maximum_queue_lag=self.maximum_queue_lag)
        if not decision.accepted:
            for reason in decision.rejection_reasons:
                self.diagnostics.record(profile_id, f"activation_rejected:{reason}")
            return decision, None
        lease = await self.registry.issue_activation_lease(
            profile_id,
            evidence,
            lease_id=lease_id,
            now=now,
            expires_at=now + self.activation_lease_ttl,
            mutation_epoch=mutation_epoch,
        )
        self.diagnostics.record(profile_id, "activation_lease_issued")
        return decision, lease

    async def promote(
        self,
        lease: ProfileAttestationLease,
        evidence: ProfileActivationEvidence,
        *,
        now: datetime,
    ) -> ProfileActivationDecision:
        decision = assess_profile_activation(evidence, maximum_queue_lag=self.maximum_queue_lag)
        if not decision.accepted:
            return decision
        try:
            retired = await self.registry.activate(
                lease,
                evidence,
                now=now,
                maximum_queue_lag=self.maximum_queue_lag,
                maximum_retained=self.maximum_retained,
                runtime_owner=self.runtime_owner,
            )
        except RuntimeError as exc:
            if str(exc) not in {
                "retrieval_profile_activation_raced",
                "retrieval_profile_activation_lease_invalid",
                "retrieval_profile_activation_lease_expired",
            }:
                raise
            self.diagnostics.record(lease.profile_id, "activation_rejected:concurrent_drift")
            return ProfileActivationDecision(False, ("concurrent_drift",))
        self.diagnostics.record(lease.profile_id, "profile_activated")
        for retired_id in retired:
            self.diagnostics.record(retired_id, "profile_retired_by_bound")
        return decision

    async def _remove_stale_projection(self, profile, items) -> None:
        versions = sorted({item.canonical_version for item in items})
        for version in versions:
            await self.projection.delete_profile_if_version(
                profile,
                tuple(
                    item.canonical_identity for item in items if item.canonical_version == version
                ),
                canonical_version=version,
            )


__all__ = ("RebuildPageResult", "RetrievalProfileLifecycle")
