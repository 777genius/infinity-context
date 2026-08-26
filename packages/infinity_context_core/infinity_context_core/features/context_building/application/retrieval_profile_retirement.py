"""Bounded, restart-safe profile retirement and cleanup use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.features.context_building.ports.retrieval_profile_lifecycle import (
    ProfileCleanup,
    RetrievalProfileCollectionCleanupPort,
    RetrievalProfileDiagnosticsPort,
    RetrievalProfileRetirementPort,
)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    examined: int
    completed: int
    pending: int
    failed: int


@dataclass(frozen=True, slots=True)
class RetrievalProfileRetirement:
    registry: RetrievalProfileRetirementPort
    collections: RetrievalProfileCollectionCleanupPort
    diagnostics: RetrievalProfileDiagnosticsPort
    maximum_retained: int = 2

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_retained, int)
            or isinstance(self.maximum_retained, bool)
            or not 0 <= self.maximum_retained <= 100
        ):
            raise ValueError("maximum_retained must be within 0..100")

    async def rollback(self, profile_id: str, *, now: datetime) -> tuple[str, ...]:
        retired = await self.registry.rollback(
            profile_id, now=now, maximum_retained=self.maximum_retained
        )
        self.diagnostics.record(profile_id, "profile_rolled_back")
        for retired_id in retired:
            self.diagnostics.record(retired_id, "profile_retired_by_bound")
        return retired

    async def retire(self, profile_id: str, *, now: datetime) -> tuple[str, ...]:
        retired = await self.registry.retire(
            profile_id, now=now, maximum_retained=self.maximum_retained
        )
        self.diagnostics.record(profile_id, "profile_retired")
        return retired

    async def delete(self, profile_id: str, *, now: datetime) -> ProfileCleanup:
        await self.registry.request_cleanup(profile_id, now=now)
        return await self.cleanup_step(profile_id, now=now)

    async def cleanup_step(self, profile_id: str, *, now: datetime) -> ProfileCleanup:
        cleanup = await self.registry.cleanup(profile_id)
        try:
            if cleanup.phase in {"requested", "waiting_for_jobs"}:
                authorization = await self.registry.authorize_collection_delete(profile_id, now=now)
                if authorization is None:
                    return await self.registry.cleanup(profile_id)
                await self.collections.delete_profile(authorization)
                await self.registry.mark_collection_deleted(authorization, now=now)
            elif cleanup.phase == "collection_deleted":
                await self.registry.cleanup_postgres(profile_id, now=now)
            elif cleanup.phase == "postgres_cleaned":
                await self.registry.complete_cleanup(profile_id, now=now)
        except Exception as exc:
            error_code = _safe_error_code(exc)
            await self.registry.record_cleanup_failure(profile_id, error_code=error_code, now=now)
            self.diagnostics.record(profile_id, "profile_cleanup_failed")
            raise
        result = await self.registry.cleanup(profile_id)
        self.diagnostics.record(profile_id, f"profile_cleanup:{result.phase}")
        return result

    async def reconcile(self, *, now: datetime, limit: int) -> ReconcileResult:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("reconcile limit must be within 1..100")
        retired = await self.registry.reconcile_retained_profiles(
            now=now, maximum_retained=self.maximum_retained
        )
        for profile_id in retired:
            self.diagnostics.record(profile_id, "profile_retired_by_reconcile")
        candidates = await self.registry.cleanup_candidates(limit=limit)
        completed = failed = 0
        for profile_id in candidates:
            try:
                result = await self.cleanup_step(profile_id, now=now)
                completed += result.phase == "complete"
            except Exception:
                failed += 1
        return ReconcileResult(
            examined=len(candidates),
            completed=completed,
            pending=len(candidates) - completed - failed,
            failed=failed,
        )


def _safe_error_code(exc: Exception) -> str:
    value = str(exc)
    if value.startswith("retrieval_profile_") and len(value) <= 120:
        return value
    return "retrieval_profile_cleanup_failed"


__all__ = ("ReconcileResult", "RetrievalProfileRetirement")
