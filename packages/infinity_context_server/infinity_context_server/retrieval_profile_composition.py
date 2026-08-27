"""Server composition and outbox coordination for Retrieval profiles."""

from __future__ import annotations

import asyncio
import hashlib
from asyncio import timeout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

from infinity_context_adapters.features.context_building.qdrant_candidate_provider import (
    QdrantContextCandidateProvider,
)
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresCanonicalProjectionSource,
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.postgres.locator_retrieval import (
    PostgresCanonicalLocatorReader,
    PostgresLocatorCandidateProvider,
)
from infinity_context_adapters.qdrant.profile_lifecycle import QdrantRetrievalProfileProjection
from infinity_context_core.features.context_building.public import (
    ProfileActivationDecision,
    ProfileAttestationPageReceipt,
    ProfileQueryAdmissionStatus,
    ProfileReconciliationWriteOutcome,
    RetrievalProfileLifecycle,
    RetrievalProfileRetirement,
    RuntimeFenceOwner,
    accumulate_attestation_digest,
    assess_profile_activation,
    finalize_attestation_digest,
)
from sqlalchemy import text

from infinity_context_server.active_reconciliation import ActiveReconciliationResult
from infinity_context_server.features.context_building.retrieval_service import (
    LocatorRetrievalService,
    RetrievalLaneRuntime,
)
from infinity_context_server.retrieval_profile_attestation import (
    attestation_in_progress as _attestation_in_progress,
)
from infinity_context_server.retrieval_profile_attestation import (
    attestation_page_evidence as _attestation_page_evidence,
)
from infinity_context_server.retrieval_profile_attestation import (
    planned_projection_versions as _planned_projection_versions,
)
from infinity_context_server.retrieval_profile_attestation import (
    projection_item_manifest as _projection_item_manifest,
)
from infinity_context_server.retrieval_profile_outbox import RetrievalProfileOutboxCoordinator
from infinity_context_server.retrieval_runtime_lifecycle import RetrievalRuntimeLifecycle


@dataclass(frozen=True, slots=True)
class ProfileAwareLocatorRetrievalService:
    """Serve Retrieval only through an admitted canonical active profile."""

    registry: PostgresRetrievalProfileRegistry
    projection: QdrantRetrievalProfileProjection
    sessions: object
    query_embeddings: object
    service_revision: str
    runtime_lifecycle: RetrievalRuntimeLifecycle | None = None
    sdk_revision: str | None = None
    supports_neighbors: bool = True
    diagnostics: object | None = None
    runtime_owner: RuntimeFenceOwner = field(
        default_factory=lambda: RuntimeFenceOwner.unrecoverable_current(
            instance_id=f"retrieval-runtime-{uuid4().hex}",
            generation=f"generation-{uuid4().hex}",
        )
    )

    async def descriptor(self):
        return await (await self._delegate()).descriptor()

    async def start_runtime(self, *, now: datetime) -> None:
        """Register this exact process generation before any lifecycle operation."""

        owner = self.runtime_owner
        if not isinstance(owner, RuntimeFenceOwner):
            raise RuntimeError("retrieval_profile_runtime_identity_missing")
        await self.registry.register_runtime_incarnation(owner, now=now)

    async def close_runtime(self, *, now: datetime) -> None:
        """Retire only this generation after the process has drained its fences."""

        owner = self.runtime_owner
        if not isinstance(owner, RuntimeFenceOwner):
            raise RuntimeError("retrieval_profile_runtime_identity_missing")
        await self.registry.retire_runtime_incarnation(owner, now=now)

    async def execute(self, request):
        operation_id = f"profile-query-{uuid4().hex}"
        now = datetime.now(UTC)
        if self.runtime_lifecycle is not None:
            await self.runtime_lifecycle.start(now=now)
        admission = await self.registry.begin_profile_query(
            operation_id,
            owner=self.runtime_owner,
            now=now,
            expires_at=now + timedelta(seconds=5),
        )
        if admission.status in {
            ProfileQueryAdmissionStatus.NO_PROFILE,
            ProfileQueryAdmissionStatus.UNAVAILABLE,
        }:
            raise RuntimeError("retrieval_profile_query_unavailable")
        active = admission.identity
        activation_lease_id = admission.activation_lease_id
        if active is None or activation_lease_id is None:
            raise RuntimeError("retrieval_profile_query_admission_invalid")
        try:
            return await self._service_for_active(active, admission_proven=True).execute(request)
        finally:
            close_task = asyncio.create_task(
                self.registry.finish_profile_query(
                    active.profile_id,
                    operation_id,
                    owner=self.runtime_owner,
                    activation_lease_id=activation_lease_id,
                )
            )
            cancellation: asyncio.CancelledError | None = None
            try:
                while not close_task.done():
                    try:
                        await asyncio.shield(close_task)
                    except asyncio.CancelledError as exc:
                        # A deadline and disconnect can cancel this task more
                        # than once. Consume each request until the independent
                        # durable close finishes, then propagate cancellation.
                        cancellation = cancellation or exc
                        current = asyncio.current_task()
                        if current is not None:
                            current.uncancel()
                close_task.result()
            except BaseException:
                self._record_query_fence_close_failure(active.profile_id)
                raise
            if cancellation is not None:
                raise cancellation

    def _record_query_fence_close_failure(self, profile_id: str) -> None:
        record = getattr(self.diagnostics, "record", None)
        if callable(record):
            record(profile_id, "query_fence_close_failed")

    async def reconcile_active(
        self,
        *,
        now: datetime,
        lease_ttl: timedelta = timedelta(seconds=30),
        renew_before: timedelta = timedelta(seconds=15),
    ) -> ActiveReconciliationResult:
        """Renew the active lease from a bounded, restart-safe physical observation."""

        owner = self.runtime_owner
        if not isinstance(owner, RuntimeFenceOwner):
            raise RuntimeError("retrieval_profile_reconciliation_runtime_identity_missing")
        if self.runtime_lifecycle is not None:
            await self.runtime_lifecycle.start(now=now)
        await self.registry.verify_registered_runtime_owner(owner)
        active = await self.registry.active()
        if active is None:
            return ActiveReconciliationResult(False, False)
        current = await self.registry.active_lease(now=now)
        if current is not None and current.expires_at > now + renew_before:
            return ActiveReconciliationResult(True, False)
        operation = await self.registry.reconciliation_operation(
            active.profile_id, runtime_owner=owner
        )
        coverage = await self.registry.coverage(
            active.profile_id,
            reconciliation_operation=operation,
            runtime_owner=owner,
        )
        await self.registry.update_lane(
            active.profile_id,
            "postgres_keyword",
            required=True,
            healthy=True,
            profile_qualified=True,
            failure_code=None,
            checked_at=now,
            reconciliation_operation=operation,
            runtime_owner=owner,
        )
        try:
            count, digest, mutation_epoch = await _bounded_qdrant_attestation(
                self.registry,
                self.projection,
                active,
                operation_id=operation.operation_id,
                now=now,
                expected_count=coverage.expected_count,
                expected_digest=coverage.expected_digest,
                reconciliation_operation=operation,
                runtime_owner=owner,
            )
        except RuntimeError as exc:
            if _attestation_in_progress(exc):
                return ActiveReconciliationResult(False, False)
            drift_outcome = await self.registry.mark_reconciliation_drift(
                active.profile_id,
                operation=operation,
                runtime_owner=owner,
                now=now,
            )
            if drift_outcome in {
                ProfileReconciliationWriteOutcome.STALE,
                ProfileReconciliationWriteOutcome.CONFLICT,
            }:
                return ActiveReconciliationResult(False, False, outcome=drift_outcome.value)
            raise
        capability = await self.projection.adapter_for(active).capabilities()
        healthy = bool(
            capability.enabled
            and capability.healthy
            and capability.supports_search
            and capability.supports_filters
        )
        qualified = (
            healthy and count == coverage.expected_count and digest == coverage.expected_digest
        )
        await self.registry.update_lane(
            active.profile_id,
            "qdrant_dense",
            required=True,
            healthy=healthy,
            profile_qualified=qualified,
            failure_code=None if qualified else "qdrant_profile_reconciliation_drift",
            checked_at=now,
            observed_count=count,
            observed_digest=digest,
            reconciliation_operation=operation,
            runtime_owner=owner,
        )
        # Rebind after lane evidence invalidates the lease; later mutations still fail the CAS.
        operation = await self.registry.reconciliation_operation(
            active.profile_id, runtime_owner=owner
        )
        evidence = await self.registry.activation_evidence(
            active.profile_id,
            now=now,
            reconciliation_operation=operation,
            runtime_owner=owner,
        )
        decision = assess_profile_activation(evidence, maximum_queue_lag=timedelta(minutes=5))
        write_outcome = await self.registry.record_reconciliation(
            active.profile_id,
            evidence,
            operation=operation,
            runtime_owner=owner,
            now=now,
            expires_at=now + lease_ttl,
            drifted=not decision.accepted,
            mutation_epoch=mutation_epoch,
        )
        return ActiveReconciliationResult(
            complete=(
                decision.accepted
                and write_outcome
                in {
                    ProfileReconciliationWriteOutcome.APPLIED,
                    ProfileReconciliationWriteOutcome.IDEMPOTENT_REPLAY,
                }
            ),
            renewed=(
                decision.accepted and write_outcome is ProfileReconciliationWriteOutcome.APPLIED
            ),
            runtime_instance_id=(
                owner.instance_id
                if write_outcome is ProfileReconciliationWriteOutcome.APPLIED
                else None
            ),
            runtime_generation=(
                owner.generation
                if write_outcome is ProfileReconciliationWriteOutcome.APPLIED
                else None
            ),
            release_identity_sha256=(
                owner.installed_release.digest()
                if write_outcome is ProfileReconciliationWriteOutcome.APPLIED
                else None
            ),
            lifecycle_identity_sha256=(
                owner.lifecycle_identity_sha256()
                if write_outcome is ProfileReconciliationWriteOutcome.APPLIED
                else None
            ),
            outcome=write_outcome.value,
        )

    async def _delegate(self) -> LocatorRetrievalService:
        active = await self.registry.active()
        if active is None:
            raise RuntimeError("retrieval_profile_query_unavailable")
        return self._service_for_active(active)

    def _service_for_active(
        self, active, *, admission_proven: bool = False
    ) -> LocatorRetrievalService:
        adapter = self.projection.adapter_for(active)

        async def lease_current() -> bool:
            return await self.registry.active_lease(now=datetime.now(UTC)) is not None

        async def postgres_health() -> bool:
            # Query admission already verifies the current activation lease and
            # every required lane atomically. Re-probing providers here can
            # consume the complete Contract-C deadline on a cold SDK client.
            if admission_proven:
                return True
            try:
                if not await lease_current():
                    return False
                async with self.sessions() as session:
                    await session.execute(text("SELECT 1"))
                return True
            except Exception:
                return False

        async def qdrant_health() -> bool:
            if admission_proven:
                return True
            if not await lease_current():
                return False
            capability = await adapter.capabilities()
            return bool(
                capability.enabled
                and capability.healthy
                and capability.supports_search
                and capability.supports_filters
            )

        return LocatorRetrievalService(
            lanes=(
                RetrievalLaneRuntime(
                    "postgres_keyword",
                    PostgresLocatorCandidateProvider(self.sessions),
                    postgres_health,
                    True,
                ),
                RetrievalLaneRuntime(
                    "qdrant_dense",
                    QdrantContextCandidateProvider(adapter, self.query_embeddings),
                    qdrant_health,
                    True,
                    profile_qualification=qdrant_health,
                ),
            ),
            canonical_reader=PostgresCanonicalLocatorReader(self.sessions),
            service_revision=self.service_revision,
            sdk_revision=self.sdk_revision,
            index_profile_digest=active.profile_digest,
            profile_kind="full",
            supports_neighbors=self.supports_neighbors,
            diagnostics=self.diagnostics,
            profile_id_override=active.profile_id,
        )


@dataclass(frozen=True, slots=True)
class ComposedRetrievalProfileLifecycle:
    lifecycle: RetrievalProfileLifecycle
    registry: PostgresRetrievalProfileRegistry
    projection: QdrantRetrievalProfileProjection
    sessions: object
    retirement: RetrievalProfileRetirement

    def runtime_trust_provenance(self) -> dict[str, object]:
        owner = self.projection.runtime_owner
        payload = owner.lifecycle_identity_payload()
        payload["receipt_identity_sha256"] = owner.lifecycle_identity_sha256()
        return payload

    async def create_building(self, identity, *, now):
        return await self.lifecycle.create_building(identity, now=now)

    async def rebuild_page(self, *, now):
        return await self.lifecycle.rebuild_page(now=now)

    async def rebuild_profile_page(self, profile_id: str, *, now: datetime):
        building = await self.registry.building()
        if building is None or building.profile_id != profile_id:
            raise RuntimeError("retrieval_profile_building_mismatch")
        return await self.lifecycle.rebuild_page(now=now)

    async def rebuild_profile_page_atomic(
        self,
        profile_id: str,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        page_limit: int,
        now: datetime,
    ) -> dict[str, object]:
        """Recover or commit one provider-idempotent rebuild page and response."""

        plan = await self.registry.operator_rebuild_plan(
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        building = await self.registry.building()
        if building is None or building.profile_id != profile_id:
            raise RuntimeError("retrieval_profile_building_mismatch")
        if plan is None:
            previous_cursor = await self.registry.backfill_cursor(profile_id)
            cursor = previous_cursor
            pages = []
            projected_count = 0
            for _ in range(page_limit):
                page = await self.lifecycle.source.page_eligible(
                    after=cursor, limit=self.lifecycle.page_size
                )
                pages.append(
                    {
                        "previous_cursor": cursor,
                        "next_cursor": page.next_cursor,
                        "watermark": page.canonical_watermark,
                        "items": _projection_item_manifest(page.items),
                    }
                )
                projected_count += len(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    break
            complete = cursor is None
            result = {
                "operation": "rebuild",
                "profile_id": profile_id,
                "idempotency_key": idempotency_key,
                "phase": "complete" if complete else "pending",
                "projected_count": projected_count,
                "next_cursor": cursor,
                "runtime_trust_provenance": self.runtime_trust_provenance(),
            }
            plan = {
                "previous_cursor": previous_cursor,
                "next_cursor": cursor,
                "watermark": max(int(item["watermark"]) for item in pages),
                "complete": complete,
                "pages": pages,
                "result": result,
            }
            await self.registry.prepare_operator_rebuild(
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                profile_id=profile_id,
                plan=plan,
                now=now,
            )
        previous_cursor = plan.get("previous_cursor")
        if previous_cursor is not None and not isinstance(previous_cursor, str):
            raise RuntimeError("retrieval_profile_rebuild_journal_invalid")
        planned_pages = plan.get("pages")
        if not isinstance(planned_pages, list) or not planned_pages:
            raise RuntimeError("retrieval_profile_rebuild_journal_invalid")
        replay_cursor = previous_cursor
        all_items = []
        await self.lifecycle.projection.prepare_profile(building)
        try:
            for planned_page in planned_pages:
                if not isinstance(planned_page, dict):
                    raise RuntimeError("retrieval_profile_rebuild_journal_invalid")
                page = await self.lifecycle.source.page_eligible(
                    after=replay_cursor, limit=self.lifecycle.page_size
                )
                if (
                    planned_page.get("previous_cursor") != replay_cursor
                    or _projection_item_manifest(page.items) != planned_page.get("items")
                    or page.next_cursor != planned_page.get("next_cursor")
                    or page.canonical_watermark != planned_page.get("watermark")
                ):
                    raise RuntimeError("retrieval_profile_rebuild_journal_drift")
                if page.items:
                    await self.lifecycle.projection.upsert_profile(building, page.items)
                    all_items.extend(page.items)
                replay_cursor = page.next_cursor
        except RuntimeError as exc:
            if str(exc) in {
                "retrieval_profile_rebuild_journal_drift",
                "retrieval_profile_tombstone_projection_rejected",
            }:
                await self._compensate_rebuild_plan(building, planned_pages, now=now)
            raise
        result = plan.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("retrieval_profile_rebuild_journal_invalid")
        try:
            return await self.registry.commit_operator_rebuild(
                profile_id,
                tuple(all_items),
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                previous_cursor=previous_cursor,
                cursor=replay_cursor,
                watermark=int(plan.get("watermark", -1)),
                complete=bool(plan.get("complete")),
                result=result,
                now=now,
            )
        except RuntimeError as exc:
            if str(exc) in {
                "retrieval_profile_stale_projection_write",
                "retrieval_profile_projection_digest_drift",
            }:
                await self._compensate_rebuild_plan(building, planned_pages, now=now)
            raise

    async def _compensate_rebuild_plan(self, identity, planned_pages, *, now: datetime) -> None:
        """Replay exact stale deletes from the durable rebuild journal."""

        coordinator = RetrievalProfileOutboxCoordinator(
            self.registry, self.lifecycle.source, self.projection
        )
        for canonical_id, stale_version in _planned_projection_versions(planned_pages):
            await coordinator.compensate_stale_write(identity, canonical_id, stale_version, now=now)

    async def attest(
        self, profile_id: str, *, operation_id: str, now: datetime
    ) -> ProfileActivationDecision:
        return await self.activate(profile_id, now=now, operation_id=operation_id, _promote=False)

    async def activate(
        self,
        profile_id: str,
        *,
        now: datetime,
        operation_id: str | None = None,
        _promote: bool = True,
    ):
        transition_operation_id = operation_id or f"transition-{uuid4().hex}"
        consumed_profile_id = await self.registry.consumed_transition_profile(
            transition_operation_id
        )
        if consumed_profile_id is not None:
            if consumed_profile_id != profile_id:
                raise RuntimeError("retrieval_profile_idempotency_conflict")
            return ProfileActivationDecision(True, ())
        active = await self.registry.active()
        if active is not None and active.profile_id == profile_id:
            return ProfileActivationDecision(True, ())
        target = await self.registry.promotable(profile_id)
        if target is None:
            raise RuntimeError("retrieval_profile_not_promotable")
        postgres_healthy = False
        try:
            async with self.sessions() as session:
                await session.execute(text("SELECT 1"))
            postgres_healthy = True
        except Exception:
            pass
        qdrant_healthy = False
        qdrant_qualified = False
        observed_count = 0
        observed_digest = finalize_attestation_digest(0, "0" * 64)
        observed_epoch = 0
        failure_code = None
        try:
            capability = await self.projection.adapter_for(target).capabilities()
            qdrant_healthy = bool(
                capability.enabled
                and capability.healthy
                and capability.supports_upsert
                and capability.supports_delete
                and capability.supports_search
                and capability.supports_filters
            )
            if not qdrant_healthy:
                failure_code = capability.degraded_reason or "qdrant_profile_unhealthy"
            else:
                coverage = await self.registry.coverage(profile_id)
                observed_count, observed_digest, observed_epoch = await _bounded_qdrant_attestation(
                    self.registry,
                    self.projection,
                    target,
                    operation_id=transition_operation_id,
                    now=now,
                    expected_count=coverage.expected_count,
                    expected_digest=coverage.expected_digest,
                )
                qdrant_qualified = observed_count == coverage.expected_count and (
                    observed_digest == coverage.expected_digest
                )
                if not qdrant_qualified:
                    failure_code = "qdrant_profile_attestation_mismatch"
        except TimeoutError:
            raise
        except RuntimeError as exc:
            if _attestation_in_progress(exc):
                raise
            failure_code = "qdrant_profile_health_failed"
        except Exception:
            failure_code = "qdrant_profile_health_failed"
        await self.registry.update_lane(
            profile_id,
            "postgres_keyword",
            required=True,
            healthy=postgres_healthy,
            profile_qualified=postgres_healthy,
            failure_code=None if postgres_healthy else "postgres_profile_unhealthy",
            checked_at=now,
        )
        await self.registry.update_lane(
            profile_id,
            "qdrant_dense",
            required=True,
            healthy=qdrant_healthy,
            profile_qualified=qdrant_qualified,
            failure_code=failure_code,
            checked_at=now,
            observed_count=observed_count,
            observed_digest=observed_digest,
        )
        decision, lease = await self.lifecycle.qualify(
            profile_id,
            lease_id=transition_operation_id,
            mutation_epoch=observed_epoch,
            now=now,
        )
        if lease is None:
            return decision
        if not _promote:
            return decision
        # A second bounded physical observation closes the stale-boolean window.
        verified_count, verified_digest, verified_epoch = await _bounded_qdrant_attestation(
            self.registry,
            self.projection,
            target,
            operation_id=(f"{transition_operation_id}-promotion"),
            now=now,
            expected_count=observed_count,
            expected_digest=observed_digest,
        )
        await self.registry.update_lane(
            profile_id,
            "qdrant_dense",
            required=True,
            healthy=qdrant_healthy,
            profile_qualified=(
                qdrant_healthy
                and verified_count == observed_count
                and verified_digest == observed_digest
            ),
            failure_code=(
                None
                if verified_count == observed_count and verified_digest == observed_digest
                else "qdrant_profile_attestation_changed"
            ),
            checked_at=now,
            observed_count=verified_count,
            observed_digest=verified_digest,
        )
        exact_evidence = await self.registry.activation_evidence(profile_id, now=now)
        lease_now = datetime.now(UTC)
        exact_lease = await self.registry.issue_activation_lease(
            profile_id,
            exact_evidence,
            lease_id=transition_operation_id,
            now=lease_now,
            expires_at=lease_now + self.lifecycle.activation_lease_ttl,
            mutation_epoch=verified_epoch,
        )
        return await self.lifecycle.promote(exact_lease, exact_evidence, now=datetime.now(UTC))

    async def rollback(self, profile_id: str, *, now: datetime, operation_id: str | None = None):
        # Rollback activates a retained profile through the same qualification and lease
        # path, behind the same physical attestation, tombstone, fencing, CAS and audit gates.
        decision = await self.activate(
            profile_id,
            now=now,
            operation_id=operation_id or f"rollback-{uuid4().hex}",
        )
        if not decision.accepted:
            raise RuntimeError("retrieval_profile_rollback_not_qualified")
        self.lifecycle.diagnostics.record(profile_id, "profile_rolled_back")
        return ()

    async def retire(self, profile_id: str, *, now: datetime):
        return await self.retirement.retire(profile_id, now=now)

    async def delete(self, profile_id: str, *, now: datetime):
        return await self.retirement.delete(profile_id, now=now)

    async def reconcile(self, *, now: datetime, limit: int):
        return await self.retirement.reconcile(now=now, limit=limit)


def build_retrieval_profile_lifecycle(
    *, session_factory, settings, query_embeddings, diagnostics, runtime_owner=None
) -> tuple[ComposedRetrievalProfileLifecycle, RetrievalProfileOutboxCoordinator]:
    supervisor_trust = _supervisor_trust_from_settings(settings)
    registry = PostgresRetrievalProfileRegistry(session_factory, supervisor_trust)
    source = PostgresCanonicalProjectionSource(session_factory)
    projection = QdrantRetrievalProfileProjection(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        vector_size=settings.embeddings_dimensions,
        embedder=query_embeddings,
        mutation_registry=registry,
        runtime_owner=(runtime_owner or _runtime_owner_from_settings(settings)),
    )
    lifecycle = RetrievalProfileLifecycle(
        registry,
        source,
        projection,
        diagnostics,
        maximum_retained=settings.retrieval_profile_max_retained,
        runtime_owner=projection.runtime_owner,
    )
    retirement = RetrievalProfileRetirement(
        registry,
        projection,
        diagnostics,
        maximum_retained=settings.retrieval_profile_max_retained,
    )
    return (
        ComposedRetrievalProfileLifecycle(
            lifecycle, registry, projection, session_factory, retirement
        ),
        RetrievalProfileOutboxCoordinator(registry, source, projection),
    )


def _runtime_owner_from_settings(settings, *, expected_release=None) -> RuntimeFenceOwner:
    encoded = getattr(settings, "retrieval_runtime_launch_identity_json", None)
    if encoded:
        owner = RuntimeFenceOwner.from_launch_identity_json(encoded)
        owner.assert_current_process()
        trust = _supervisor_trust_from_settings(settings, expected_release=expected_release)
        if trust is None:
            raise RuntimeError("retrieval_profile_supervisor_trust_required")
        if owner.supervisor_key_id != getattr(settings, "retrieval_supervisor_key_id", None):
            raise RuntimeError("retrieval_profile_supervisor_key_id_mismatch")
        trust.verify_launch(owner, now=datetime.now(UTC))
        return owner
    return RuntimeFenceOwner.unrecoverable_current(
        instance_id=f"retrieval-runtime-{uuid4().hex}",
        generation=f"generation-{uuid4().hex}",
        key_id="unrecoverable-no-external-supervisor",
    )


def _supervisor_trust_from_settings(settings, *, expected_release=None):
    path = getattr(settings, "retrieval_supervisor_trust_registry_path", None)
    if not path:
        return None
    from infinity_context_adapters.postgres.supervisor_trust import (
        load_pinned_supervisor_trust,
    )

    from infinity_context_server.build_identity import verify_installed_build_identity

    release = expected_release
    if release is None:
        build = verify_installed_build_identity(
            getattr(settings, "service_build_identity_path", None)
        )
        if build is None:
            raise RuntimeError("retrieval_profile_installed_release_identity_required")
        release = build.installed_release()

    return load_pinned_supervisor_trust(
        path=path,
        expected_root_sha256=getattr(settings, "retrieval_supervisor_trust_root_sha256", "") or "",
        expected_key_id=getattr(settings, "retrieval_supervisor_key_id", "") or "",
        expected_generation=(
            getattr(settings, "retrieval_supervisor_trust_registry_generation", 0) or 0
        ),
        expected_release=release,
    )


async def _bounded_qdrant_attestation(
    registry,
    projection,
    identity,
    *,
    operation_id: str,
    now: datetime,
    expected_count: int | None = None,
    expected_digest: str | None = None,
    page_size: int = 256,
    maximum_pages: int = 32,
    maximum_bytes: int = 4 * 1024 * 1024,
    deadline: timedelta = timedelta(seconds=10),
    reconciliation_operation=None,
    runtime_owner: RuntimeFenceOwner | None = None,
) -> tuple[int, str, int]:
    """Content-address, then incrementally revalidate a bounded physical scan."""

    if not 1 <= page_size <= 1000 or not 1 <= maximum_pages <= 1000:
        raise ValueError("retrieval profile attestation work budget is invalid")
    if not 1024 <= maximum_bytes <= 64 * 1024 * 1024:
        raise ValueError("retrieval profile attestation byte budget is invalid")
    if not timedelta(milliseconds=1) <= deadline <= timedelta(minutes=1):
        raise ValueError("retrieval profile attestation deadline is invalid")
    content_count = -1 if expected_count is None else expected_count
    content_digest = identity.profile_digest if expected_digest is None else expected_digest
    address = hashlib.sha256(
        (
            "qdrant-attestation.v2\0"
            f"{identity.profile_id}\0{identity.generation}\0{identity.profile_digest}\0"
            f"{identity.collection_name}\0{operation_id}\0{content_count}\0{content_digest}\0"
            f"{page_size}"
        ).encode()
    ).hexdigest()
    checkpoint_id = f"qdrant-v2-{address}"
    checkpoint = await registry.attestation_checkpoint(identity.profile_id, checkpoint_id)
    started_at = now
    deadline_at = now + deadline
    stop_at = monotonic() + deadline.total_seconds()
    provider_epoch = await projection.attestation_epoch(identity, now=datetime.now(UTC))
    if checkpoint is not None and checkpoint.provider_epoch != provider_epoch:
        raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
    if checkpoint is not None and checkpoint.complete:
        return (
            checkpoint.item_count,
            finalize_attestation_digest(checkpoint.item_count, checkpoint.digest_accumulator),
            checkpoint.provider_epoch,
        )
    pages_used = 0
    bytes_used = 0
    cursor = checkpoint.cursor if checkpoint is not None else None
    count = checkpoint.item_count if checkpoint is not None else 0
    accumulator = checkpoint.digest_accumulator if checkpoint is not None else "0" * 64
    scan_complete = checkpoint.scan_complete if checkpoint is not None else False
    scan_page_count = checkpoint.scan_page_count if checkpoint is not None else 0
    validation_cursor = checkpoint.validation_cursor if checkpoint is not None else None
    validation_page = checkpoint.validation_page_number if checkpoint is not None else 0
    validation_count = checkpoint.validation_item_count if checkpoint is not None else 0
    validation_accumulator = (
        checkpoint.validation_accumulator if checkpoint is not None else "0" * 64
    )
    while not scan_complete and pages_used < maximum_pages:
        if monotonic() >= stop_at:
            raise RuntimeError("retrieval_profile_attestation_deadline")
        if await projection.attestation_epoch(identity, now=datetime.now(UTC)) != provider_epoch:
            raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
        remaining = stop_at - monotonic()
        async with timeout(remaining):
            rows, next_cursor = await projection.attestation_page(
                identity, cursor=cursor, limit=page_size
            )
        if await projection.attestation_epoch(identity, now=datetime.now(UTC)) != provider_epoch:
            raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
        page_bytes, page_digest = _attestation_page_evidence(cursor, next_cursor, rows)
        if bytes_used + page_bytes > maximum_bytes:
            raise RuntimeError("retrieval_profile_attestation_byte_budget")
        next_count = count
        next_accumulator = accumulator
        for canonical_identity, canonical_version, payload_digest in rows:
            next_accumulator = accumulate_attestation_digest(
                next_accumulator,
                canonical_identity,
                canonical_version,
                payload_digest,
            )
            next_count += 1
        completed = next_cursor is None
        observed_at = datetime.now(UTC)
        receipt = ProfileAttestationPageReceipt(
            scan_page_count,
            cursor,
            next_cursor,
            len(rows),
            page_bytes,
            page_digest,
        )
        await registry.checkpoint_attestation(
            identity.profile_id,
            checkpoint_id,
            previous_cursor=cursor,
            cursor=next_cursor,
            item_count=next_count,
            digest_accumulator=next_accumulator,
            started_at=started_at,
            deadline_at=deadline_at,
            now=observed_at,
            complete=False,
            scan_complete=completed,
            page_receipt=receipt,
            provider_epoch=provider_epoch,
            owner_operation_id=(
                reconciliation_operation.operation_id
                if reconciliation_operation is not None
                else None
            ),
            reconciliation_operation=reconciliation_operation,
            runtime_owner=runtime_owner,
        )
        cursor, count, accumulator = next_cursor, next_count, next_accumulator
        scan_page_count += 1
        scan_complete = completed
        pages_used += 1
        bytes_used += page_bytes
        if completed:
            break
    while scan_complete and validation_page < scan_page_count and pages_used < maximum_pages:
        if monotonic() >= stop_at:
            raise RuntimeError("retrieval_profile_attestation_deadline")
        receipt = await registry.attestation_page_receipt(
            identity.profile_id, checkpoint_id, validation_page
        )
        if receipt is None or receipt.start_cursor != validation_cursor:
            raise RuntimeError("retrieval_profile_attestation_checkpoint_unverifiable")
        if await projection.attestation_epoch(identity, now=datetime.now(UTC)) != provider_epoch:
            raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
        async with timeout(stop_at - monotonic()):
            rows, next_cursor = await projection.attestation_page(
                identity, cursor=validation_cursor, limit=page_size
            )
        if await projection.attestation_epoch(identity, now=datetime.now(UTC)) != provider_epoch:
            raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
        page_bytes, page_digest = _attestation_page_evidence(validation_cursor, next_cursor, rows)
        if bytes_used + page_bytes > maximum_bytes:
            raise RuntimeError("retrieval_profile_attestation_byte_budget")
        if (
            receipt.end_cursor != next_cursor
            or receipt.item_count != len(rows)
            or receipt.byte_count != page_bytes
            or receipt.page_digest != page_digest
        ):
            raise RuntimeError("retrieval_profile_attestation_checkpoint_drift")
        for canonical_identity, canonical_version, payload_digest in rows:
            validation_accumulator = accumulate_attestation_digest(
                validation_accumulator,
                canonical_identity,
                canonical_version,
                payload_digest,
            )
            validation_count += 1
        validation_cursor = next_cursor
        validation_page += 1
        pages_used += 1
        bytes_used += page_bytes
        validated = validation_page == scan_page_count
        if validated and (validation_count != count or validation_accumulator != accumulator):
            raise RuntimeError("retrieval_profile_attestation_checkpoint_drift")
        await registry.checkpoint_attestation(
            identity.profile_id,
            checkpoint_id,
            previous_cursor=cursor,
            cursor=cursor,
            item_count=count,
            digest_accumulator=accumulator,
            started_at=started_at,
            deadline_at=deadline_at,
            now=datetime.now(UTC),
            complete=validated,
            scan_complete=True,
            validation_cursor=validation_cursor,
            validation_page_number=validation_page,
            validation_item_count=validation_count,
            validation_accumulator=validation_accumulator,
            provider_epoch=provider_epoch,
            owner_operation_id=(
                reconciliation_operation.operation_id
                if reconciliation_operation is not None
                else None
            ),
            reconciliation_operation=reconciliation_operation,
            runtime_owner=runtime_owner,
        )
        if validated:
            if (
                await projection.attestation_epoch(identity, now=datetime.now(UTC))
                != provider_epoch
            ):
                raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
            return count, finalize_attestation_digest(count, accumulator), provider_epoch
    raise RuntimeError("retrieval_profile_attestation_incomplete")


__all__ = (
    "RetrievalProfileOutboxCoordinator",
    "ProfileAwareLocatorRetrievalService",
    "ComposedRetrievalProfileLifecycle",
    "build_retrieval_profile_lifecycle",
)
