from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_core.features.context_building.public import (
    CanonicalProjectionItem,
    ExactVersionDeletionProof,
    ProfileActivationDecision,
    ProfileAttestationCheckpoint,
    ProfileAttestationLease,
    ProfileReconciliationOperation,
    ProfileReconciliationWriteOutcome,
    ProfileTombstoneDeleteAuthorization,
    ProjectedGenerationObservation,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from infinity_context_server.metrics import RuntimeMetrics
from infinity_context_server.retrieval_profile_composition import (
    ComposedRetrievalProfileLifecycle,
    ProfileAwareLocatorRetrievalService,
    _bounded_qdrant_attestation,
)


def test_profile_metrics_reject_raw_or_high_cardinality_labels() -> None:
    metrics = RuntimeMetrics()
    metrics.record("profile-a", "request_outcome:available")
    metrics.record("profile-a", "profile_cleanup:collection_deleted")
    metrics.record("profile-a", "profile_cleanup_failed")
    metrics.record("profile-a", "activation_lease_issued")
    assert metrics.retrieval_profile_snapshot() == {
        "profile-a": {
            "activation_lease_issued": 1.0,
            "profile_cleanup:collection_deleted": 1.0,
            "profile_cleanup_failed": 1.0,
            "request_outcome:available": 1.0,
        }
    }
    for unsafe in (
        "raw query",
        "locator/a",
        "text\nvalue",
        "secretquerytext",
        "profile_cleanup:unknown",
        "profile_cleanup_failed:provider-message",
    ):
        try:
            metrics.record("profile-a", unsafe)
        except ValueError:
            pass
        else:  # pragma: no cover - fail-closed assertion
            raise AssertionError("unsafe profile label was accepted")


def test_qdrant_attestation_crash_resume_does_not_skip_or_double_count() -> None:
    registry = _CheckpointRegistry()
    projection = _PagedProjection()
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    try:
        asyncio.run(
            _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id="op",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                page_size=1,
                maximum_pages=1,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "retrieval_profile_attestation_incomplete"
    else:  # pragma: no cover
        raise AssertionError("bounded slice unexpectedly exhausted all work")

    count, digest, epoch = asyncio.run(
        _bounded_qdrant_attestation(
            registry,
            projection,
            identity,
            operation_id="op",
            now=datetime(2026, 8, 23, tzinfo=UTC),
            page_size=1,
            maximum_pages=5,
        )
    )
    assert count == 3
    assert epoch == 0
    assert len(digest) == 64
    # The provisional scan resumes, then every content-addressed page is replayed
    # before the checkpoint can become a trusted terminal result.
    assert projection.cursors == [None, "1", "2", None, "1", "2"]


def test_qdrant_attestation_retry_rejects_changed_checkpoint_prefix() -> None:
    registry = _CheckpointRegistry()
    projection = _PagedProjection()
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    with pytest.raises(RuntimeError, match="attestation_incomplete"):
        asyncio.run(
            _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id="content-addressed-retry",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                page_size=1,
                maximum_pages=1,
            )
        )
    projection.pages[None] = ((("a", 1, "f" * 64),), "1")
    with pytest.raises(RuntimeError, match="attestation_incomplete"):
        asyncio.run(
            _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id="content-addressed-retry",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                page_size=1,
                maximum_pages=2,
            )
        )
    with pytest.raises(RuntimeError, match="checkpoint_drift"):
        asyncio.run(
            _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id="content-addressed-retry",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                page_size=1,
                maximum_pages=2,
            )
        )


def test_qdrant_attestation_fails_closed_when_validated_page_epoch_changes() -> None:
    registry = _CheckpointRegistry()
    projection = _PagedProjection()
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    with pytest.raises(RuntimeError, match="attestation_incomplete"):
        asyncio.run(
            _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id="epoch-restart",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                page_size=1,
                maximum_pages=1,
            )
        )
    projection.epoch = 2
    with pytest.raises(RuntimeError, match="provider_epoch_drift"):
        asyncio.run(
            _bounded_qdrant_attestation(
                registry,
                projection,
                identity,
                operation_id="epoch-restart",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                page_size=1,
            )
        )


def test_qdrant_attestation_detects_mutation_during_page_read() -> None:
    projection = _PagedProjection()
    original = projection.attestation_page

    async def mutating_page(identity, *, cursor, limit):
        result = await original(identity, cursor=cursor, limit=limit)
        projection.epoch += 2
        return result

    projection.attestation_page = mutating_page
    with pytest.raises(RuntimeError, match="provider_epoch_drift"):
        asyncio.run(
            _bounded_qdrant_attestation(
                _CheckpointRegistry(),
                projection,
                RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a"),
                operation_id="epoch-concurrent",
                now=datetime(2026, 8, 23, tzinfo=UTC),
            )
        )


def test_qdrant_attestation_resumes_and_revalidates_beyond_16384_points() -> None:
    registry = _CheckpointRegistry()
    projection = _LargePagedProjection(16_385)
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")

    for _ in range(20):
        try:
            count, digest, epoch = asyncio.run(
                _bounded_qdrant_attestation(
                    registry,
                    projection,
                    identity,
                    operation_id="large-bounded-profile",
                    now=datetime(2026, 8, 23, tzinfo=UTC),
                    page_size=256,
                    maximum_pages=16,
                    maximum_bytes=1024 * 1024,
                )
            )
            break
        except RuntimeError as exc:
            assert str(exc) == "retrieval_profile_attestation_incomplete"
    else:  # pragma: no cover
        raise AssertionError("large bounded profile did not finish incrementally")

    assert count == 16_385
    assert epoch == 0
    assert len(digest) == 64
    assert registry.checkpoint.complete is True
    assert registry.checkpoint.validation_page_number == 65
    assert projection.calls == 130


def test_large_checkpoint_revalidation_detects_prefix_corruption() -> None:
    registry = _CheckpointRegistry()
    projection = _LargePagedProjection(16_385)
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    arguments = dict(
        registry=registry,
        projection=projection,
        identity=identity,
        operation_id="large-corruption",
        now=datetime(2026, 8, 23, tzinfo=UTC),
        page_size=256,
    )
    with pytest.raises(RuntimeError, match="attestation_incomplete"):
        asyncio.run(_bounded_qdrant_attestation(**arguments, maximum_pages=64))
    with pytest.raises(RuntimeError, match="attestation_incomplete"):
        asyncio.run(_bounded_qdrant_attestation(**arguments, maximum_pages=1))
    projection.corrupt_first = True

    with pytest.raises(RuntimeError, match="checkpoint_drift"):
        asyncio.run(_bounded_qdrant_attestation(**arguments, maximum_pages=1))


def test_qdrant_attestation_enforces_deadline_and_propagates_cancellation() -> None:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    with pytest.raises(TimeoutError):
        asyncio.run(
            _bounded_qdrant_attestation(
                _CheckpointRegistry(),
                _SlowProjection(),
                identity,
                operation_id="deadline",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                deadline=timedelta(milliseconds=1),
            )
        )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            _bounded_qdrant_attestation(
                _CheckpointRegistry(),
                _CancelledProjection(),
                identity,
                operation_id="cancelled",
                now=datetime(2026, 8, 23, tzinfo=UTC),
            )
        )


def test_qdrant_attestation_enforces_explicit_page_and_byte_bounds() -> None:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    with pytest.raises(ValueError, match="work budget"):
        asyncio.run(
            _bounded_qdrant_attestation(
                _CheckpointRegistry(),
                _PagedProjection(),
                identity,
                operation_id="invalid-pages",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                maximum_pages=0,
            )
        )
    with pytest.raises(RuntimeError, match="byte_budget"):
        asyncio.run(
            _bounded_qdrant_attestation(
                _CheckpointRegistry(),
                _OversizedProjection(),
                identity,
                operation_id="bounded-bytes",
                now=datetime(2026, 8, 23, tzinfo=UTC),
                maximum_bytes=1024,
            )
        )


def test_rollback_uses_fresh_operation_per_transition_and_replays_same_operation(
    monkeypatch,
) -> None:
    calls = []

    async def activate(self, profile_id, *, now, operation_id, **_values):
        calls.append((profile_id, now, operation_id))
        return ProfileActivationDecision(True, ())

    monkeypatch.setattr(ComposedRetrievalProfileLifecycle, "activate", activate)
    diagnostics = SimpleNamespace(record=lambda *values: calls.append(values))
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=SimpleNamespace(diagnostics=diagnostics),
        registry=object(),
        projection=object(),
        sessions=object(),
        retirement=object(),
    )
    now = datetime(2026, 8, 25, tzinfo=UTC)
    assert (
        asyncio.run(composed.rollback("retained-a", now=now, operation_id="rollback-request-a"))
        == ()
    )
    assert (
        asyncio.run(composed.rollback("retained-a", now=now, operation_id="rollback-request-a"))
        == ()
    )
    assert calls[0] == ("retained-a", now, "rollback-request-a")
    assert calls[2] == ("retained-a", now, "rollback-request-a")


def test_ordinary_rollbacks_do_not_reuse_consumed_profile_lease(monkeypatch) -> None:
    operation_ids = []

    async def activate(self, profile_id, *, now, operation_id, **_values):
        del profile_id, now
        operation_ids.append(operation_id)
        return ProfileActivationDecision(True, ())

    monkeypatch.setattr(ComposedRetrievalProfileLifecycle, "activate", activate)
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=SimpleNamespace(diagnostics=SimpleNamespace(record=lambda *_values: None)),
        registry=object(),
        projection=object(),
        sessions=object(),
        retirement=object(),
    )
    now = datetime(2026, 8, 25, tzinfo=UTC)

    asyncio.run(composed.rollback("retained-a", now=now))
    asyncio.run(composed.rollback("retained-a", now=now))

    assert len(operation_ids) == 2
    assert operation_ids[0].startswith("rollback-")
    assert operation_ids[1].startswith("rollback-")
    assert operation_ids[0] != operation_ids[1]


def test_active_profile_reconciliation_fails_closed_on_physical_drift(monkeypatch) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    registry = _ReconciliationRegistry(now)

    async def drift(*_args, **_kwargs):
        raise RuntimeError("retrieval_profile_attestation_checkpoint_drift")

    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition._bounded_qdrant_attestation",
        drift,
    )
    service = ProfileAwareLocatorRetrievalService(
        registry=registry,
        projection=_ReconciliationProjection(),
        sessions=object(),
        query_embeddings=object(),
        service_revision="1" * 40,
    )

    with pytest.raises(RuntimeError, match="checkpoint_drift"):
        asyncio.run(service.reconcile_active(now=now))

    assert registry.drifted == [("reconcile-seed-0", now)]


def test_atomic_rebuild_replays_exact_provider_page_after_commit_crash() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    registry = _AtomicRebuildRegistry()
    source = _AtomicRebuildSource()
    projection = _AtomicRebuildProjection()
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=SimpleNamespace(source=source, projection=projection, page_size=256),
        registry=registry,
        projection=projection,
        sessions=object(),
        retirement=object(),
    )
    arguments = {
        "profile_id": registry.identity.profile_id,
        "idempotency_key": "rebuild-crash",
        "request_fingerprint": "f" * 64,
        "page_limit": 1,
        "now": now,
    }

    with pytest.raises(RuntimeError, match="injected_commit_crash"):
        asyncio.run(composed.rebuild_profile_page_atomic(**arguments))

    assert registry.plan is not None
    assert registry.cursor is None
    assert projection.upserts == [("chunk-rebuild", 7)]

    result = asyncio.run(composed.rebuild_profile_page_atomic(**arguments))

    assert result == registry.plan["result"]
    assert result["next_cursor"] == "chunk-rebuild"
    assert registry.cursor == "chunk-rebuild"
    assert registry.commit_attempts == 2
    assert projection.upserts == [("chunk-rebuild", 7), ("chunk-rebuild", 7)]
    assert source.cursors == [None, None, None]


def test_atomic_rebuild_journal_drift_compensates_prior_exact_effect() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    registry = _CompensatingAtomicRebuildRegistry()
    source = _AtomicRebuildSource()
    projection = _CompensatingAtomicRebuildProjection()
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=SimpleNamespace(source=source, projection=projection, page_size=256),
        registry=registry,
        projection=projection,
        sessions=object(),
        retirement=object(),
    )
    arguments = {
        "profile_id": registry.identity.profile_id,
        "idempotency_key": "rebuild-stale-crash",
        "request_fingerprint": "e" * 64,
        "page_limit": 1,
        "now": now,
    }
    with pytest.raises(RuntimeError, match="injected_commit_crash"):
        asyncio.run(composed.rebuild_profile_page_atomic(**arguments))
    assert projection.current_version == 7

    source.item = CanonicalProjectionItem(
        "chunk-rebuild",
        8,
        12,
        "c" * 64,
        "space-a",
        "scope-a",
        None,
        "new active version",
        (),
    )
    with pytest.raises(RuntimeError, match="rebuild_journal_drift"):
        asyncio.run(composed.rebuild_profile_page_atomic(**arguments))

    assert projection.deletes == [("chunk-rebuild", 7)]
    assert projection.current_version is None


def test_atomic_rebuild_admission_rejection_compensates_prior_exact_effect() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    registry = _CompensatingAtomicRebuildRegistry()
    source = _AtomicRebuildSource()
    projection = _CompensatingAtomicRebuildProjection()
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=SimpleNamespace(source=source, projection=projection, page_size=256),
        registry=registry,
        projection=projection,
        sessions=object(),
        retirement=object(),
    )
    arguments = {
        "profile_id": registry.identity.profile_id,
        "idempotency_key": "rebuild-admission-crash",
        "request_fingerprint": "d" * 64,
        "page_limit": 1,
        "now": now,
    }
    with pytest.raises(RuntimeError, match="injected_commit_crash"):
        asyncio.run(composed.rebuild_profile_page_atomic(**arguments))
    projection.reject_writes = True

    with pytest.raises(RuntimeError, match="tombstone_projection_rejected"):
        asyncio.run(composed.rebuild_profile_page_atomic(**arguments))

    assert projection.deletes == [("chunk-rebuild", 7)]
    assert projection.current_version is None


def test_activation_waits_for_complete_fresh_promotion_validation(monkeypatch) -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    registry = _ActivationRegistry()
    lifecycle = _ActivationLifecycle(now)
    calls = []

    async def bounded(*_args, operation_id, **_kwargs):
        calls.append(operation_id)
        if operation_id.endswith("-promotion") and calls.count(operation_id) == 1:
            raise RuntimeError("retrieval_profile_attestation_incomplete")
        return 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 4

    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition._bounded_qdrant_attestation",
        bounded,
    )
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=lifecycle,
        registry=registry,
        projection=_ActivationProjection(),
        sessions=_HealthySessions,
        retirement=object(),
    )

    with pytest.raises(RuntimeError, match="attestation_incomplete"):
        asyncio.run(composed.activate("profile-building", now=now, operation_id="operator-stable"))
    assert lifecycle.promotions == 0

    decision = asyncio.run(
        composed.activate("profile-building", now=now, operation_id="operator-stable")
    )
    assert decision.accepted is True
    assert lifecycle.promotions == 1
    assert calls == [
        "operator-stable",
        "operator-stable-promotion",
        "operator-stable",
        "operator-stable-promotion",
    ]


def test_retained_rollback_replays_consumed_operation_without_advancing() -> None:
    class Registry:
        active_reads = 0

        async def consumed_transition_profile(self, lease_id):
            assert lease_id == "rollback-request-a"
            return "retained-a"

        async def active(self):  # pragma: no cover - replay must return first
            self.active_reads += 1
            raise AssertionError("consumed rollback advanced lifecycle")

    registry = Registry()
    composed = ComposedRetrievalProfileLifecycle(
        lifecycle=object(),
        registry=registry,
        projection=object(),
        sessions=object(),
        retirement=object(),
    )

    decision = asyncio.run(
        composed.activate(
            "retained-a",
            now=datetime(2026, 8, 25, tzinfo=UTC),
            operation_id="rollback-request-a",
        )
    )

    assert decision == ProfileActivationDecision(True, ())
    assert registry.active_reads == 0


class _CheckpointRegistry:
    def __init__(self):
        self.checkpoint = None
        self.receipts = {}

    async def attestation_checkpoint(self, profile_id, operation_id):
        return self.checkpoint

    async def checkpoint_attestation(self, profile_id, operation_id, **values):
        page_receipt = values.get("page_receipt")
        prior_pages = 0 if self.checkpoint is None else self.checkpoint.scan_page_count
        if page_receipt is not None:
            self.receipts[page_receipt.page_number] = page_receipt
            prior_pages += 1
        self.checkpoint = ProfileAttestationCheckpoint(
            values["cursor"],
            values["item_count"],
            values["digest_accumulator"],
            values["complete"],
            values.get("scan_complete", False),
            prior_pages,
            values.get("validation_cursor"),
            values.get("validation_page_number", 0),
            values.get("validation_item_count", 0),
            values.get("validation_accumulator", "0" * 64),
            values.get("provider_epoch", 0),
        )

    async def attestation_page_receipt(self, profile_id, operation_id, page_number):
        return self.receipts.get(page_number)


class _EpochProjection:
    epoch = 0

    async def attestation_epoch(self, identity, *, now):
        del identity, now
        return self.epoch


class _PagedProjection(_EpochProjection):
    def __init__(self):
        self.cursors = []
        self.pages = {
            None: ((("a", 1, "a" * 64),), "1"),
            "1": ((("b", 2, "b" * 64),), "2"),
            "2": ((("c", 3, "c" * 64),), None),
        }

    async def attestation_page(self, identity, *, cursor, limit):
        self.cursors.append(cursor)
        rows, next_cursor = self.pages[cursor]
        return rows, next_cursor


class _LargePagedProjection(_EpochProjection):
    def __init__(self, count):
        self.count = count
        self.calls = 0
        self.corrupt_first = False

    async def attestation_page(self, identity, *, cursor, limit):
        del identity
        self.calls += 1
        start = 0 if cursor is None else int(cursor)
        stop = min(self.count, start + limit)
        rows = tuple(
            (
                f"chunk-{index:06d}",
                1,
                (
                    "f" * 64
                    if self.corrupt_first and index == 0
                    else hashlib.sha256(str(index).encode()).hexdigest()
                ),
            )
            for index in range(start, stop)
        )
        return rows, None if stop == self.count else str(stop)


class _SlowProjection(_EpochProjection):
    async def attestation_page(self, identity, *, cursor, limit):
        await asyncio.sleep(1)


class _CancelledProjection(_EpochProjection):
    async def attestation_page(self, identity, *, cursor, limit):
        raise asyncio.CancelledError


class _OversizedProjection(_EpochProjection):
    async def attestation_page(self, identity, *, cursor, limit):
        del identity, cursor, limit
        return (("x" * 2048, 1, "a" * 64),), None


class _ReconciliationRegistry:
    identity = RetrievalProfileIdentity("profile-active", "gen-active", "a" * 64, "active")

    def __init__(self, now):
        self.seed = 0
        self.lease = ProfileAttestationLease(
            "activation", "profile-active", "gen-active", "b" * 64, now, now + timedelta(seconds=5)
        )
        self.recorded = []
        self.drifted = []

    async def verify_registered_runtime_owner(self, owner):
        assert isinstance(owner, RuntimeFenceOwner)

    async def active(self):
        return self.identity

    async def active_lease(self, *, now):
        return self.lease if now < self.lease.expires_at else None

    async def reconciliation_operation(self, profile_id, *, runtime_owner):
        assert profile_id == "profile-active"
        return ProfileReconciliationOperation(
            f"reconcile-seed-{self.seed}",
            profile_id,
            self.lease.lease_id,
            self.identity.generation,
            self.lease.evidence_digest,
            self.lease.issued_at,
            self.lease.expires_at,
            False,
            runtime_owner.instance_id,
            runtime_owner.generation,
            runtime_owner.lifecycle_identity_sha256(),
        )

    async def coverage(self, profile_id, **_kwargs):
        return SimpleNamespace(expected_count=0, expected_digest="e" * 64)

    async def update_lane(self, *_args, **_kwargs):
        return None

    async def activation_evidence(self, profile_id, *, now, **_kwargs):
        return SimpleNamespace()

    async def record_reconciliation(
        self,
        profile_id,
        evidence,
        *,
        operation,
        runtime_owner,
        now,
        expires_at,
        drifted,
        mutation_epoch,
    ):
        del profile_id, evidence, drifted
        assert mutation_epoch == 4
        self.recorded.append((operation.operation_id, now, expires_at, runtime_owner))
        self.seed += 1
        self.lease = ProfileAttestationLease(
            operation.operation_id, "profile-active", "gen-active", "b" * 64, now, expires_at
        )
        return ProfileReconciliationWriteOutcome.APPLIED

    async def mark_reconciliation_drift(self, profile_id, *, operation, runtime_owner, now):
        del profile_id
        assert isinstance(runtime_owner, RuntimeFenceOwner)
        self.drifted.append((operation.operation_id, now))
        self.seed += 1
        self.lease = ProfileAttestationLease(
            operation.operation_id,
            "profile-active",
            "gen-active",
            "b" * 64,
            now,
            now + timedelta(microseconds=1),
        )


class _ReconciliationProjection:
    def adapter_for(self, identity):
        del identity
        return self

    async def capabilities(self):
        return SimpleNamespace(
            enabled=True,
            healthy=True,
            supports_search=True,
            supports_filters=True,
        )


class _AtomicRebuildRegistry:
    identity = RetrievalProfileIdentity(
        "profile-rebuild", "generation-rebuild", "a" * 64, "collection-rebuild"
    )

    def __init__(self):
        self.plan = None
        self.cursor = None
        self.commit_attempts = 0

    async def operator_rebuild_plan(self, **_values):
        return self.plan

    async def building(self):
        return self.identity

    async def backfill_cursor(self, profile_id):
        assert profile_id == self.identity.profile_id
        return self.cursor

    async def prepare_operator_rebuild(self, *, plan, **_values):
        self.plan = plan
        return plan

    async def commit_operator_rebuild(self, profile_id, items, **values):
        assert profile_id == self.identity.profile_id
        assert tuple(item.canonical_identity for item in items) == ("chunk-rebuild",)
        assert values["previous_cursor"] is None
        assert values["cursor"] == "chunk-rebuild"
        self.commit_attempts += 1
        if self.commit_attempts == 1:
            raise RuntimeError("injected_commit_crash")
        self.cursor = values["cursor"]
        return dict(values["result"])


class _AtomicRebuildSource:
    def __init__(self):
        self.cursors = []
        self.item = CanonicalProjectionItem(
            "chunk-rebuild",
            7,
            11,
            "b" * 64,
            "space-a",
            "scope-a",
            None,
            "rebuild text",
            (),
        )

    async def page_eligible(self, *, after, limit):
        assert limit == 256
        self.cursors.append(after)
        return SimpleNamespace(
            items=(self.item,),
            next_cursor="chunk-rebuild",
            canonical_watermark=11,
        )


class _AtomicRebuildProjection:
    def __init__(self):
        self.upserts = []
        self.runtime_owner = RuntimeFenceOwner.unrecoverable_current(
            instance_id="atomic-rebuild-test", generation="atomic-rebuild-generation"
        )

    async def prepare_profile(self, identity):
        assert identity.profile_id == "profile-rebuild"

    async def upsert_profile(self, identity, items):
        assert identity.profile_id == "profile-rebuild"
        self.upserts.extend((item.canonical_identity, item.canonical_version) for item in items)


class _CompensatingAtomicRebuildRegistry(_AtomicRebuildRegistry):
    async def reopen_stale_projection_tombstone(
        self, profile_id, canonical_id, *, stale_version, now
    ):
        assert profile_id == self.identity.profile_id
        del canonical_id, stale_version, now
        return 8

    async def authorize_tombstone(self, profile_id, canonical_id, *, canonical_version):
        assert profile_id == self.identity.profile_id
        return ProfileTombstoneDeleteAuthorization(
            self.identity, canonical_id, canonical_version, 4
        )

    async def complete_tombstone(self, *_args, **_values):
        return True


class _CompensatingAtomicRebuildProjection(_AtomicRebuildProjection):
    def __init__(self):
        super().__init__()
        self.current_version = None
        self.deletes = []
        self.reject_writes = False

    async def upsert_profile(self, identity, items):
        if self.reject_writes:
            raise RuntimeError("retrieval_profile_tombstone_projection_rejected")
        await super().upsert_profile(identity, items)
        self.current_version = items[0].canonical_version

    async def delete_profile_if_version(
        self,
        identity,
        canonical_ids,
        *,
        canonical_version,
        tombstone_authorization,
    ):
        assert identity == self.runtime_identity
        del tombstone_authorization
        self.deletes.append((canonical_ids[0], canonical_version))
        if self.current_version == canonical_version:
            self.current_version = None
        return ExactVersionDeletionProof(
            canonical_ids, canonical_version, (self.current_version,), 6
        )

    async def observe_profile_generation(self, identity, canonical_id):
        assert identity == self.runtime_identity
        return ProjectedGenerationObservation(canonical_id, self.current_version)

    @property
    def runtime_identity(self):
        return _AtomicRebuildRegistry.identity


class _ActivationRegistry:
    identity = RetrievalProfileIdentity(
        "profile-building", "gen-building", "a" * 64, "collection-building"
    )

    async def consumed_transition_profile(self, operation_id):
        return None

    async def active(self):
        return None

    async def promotable(self, profile_id):
        return self.identity

    async def coverage(self, profile_id):
        return SimpleNamespace(expected_count=0, expected_digest="e" * 64)

    async def update_lane(self, *_args, **_kwargs):
        return None

    async def activation_evidence(self, profile_id, *, now):
        return SimpleNamespace()

    async def issue_activation_lease(
        self, profile_id, evidence, *, lease_id, now, expires_at, mutation_epoch
    ):
        del evidence
        assert profile_id == self.identity.profile_id
        assert mutation_epoch == 4
        return ProfileAttestationLease(
            lease_id,
            profile_id,
            self.identity.generation,
            "b" * 64,
            now,
            expires_at,
            1,
            mutation_epoch,
        )


class _ActivationLifecycle:
    def __init__(self, now):
        self.promotions = 0
        self.activation_lease_ttl = timedelta(seconds=30)
        self.lease = ProfileAttestationLease(
            "operator-stable",
            "profile-building",
            "gen-building",
            "b" * 64,
            now,
            now + timedelta(seconds=30),
        )

    async def qualify(self, profile_id, *, lease_id, mutation_epoch, now):
        assert mutation_epoch == 4
        return ProfileActivationDecision(True, ()), self.lease

    async def promote(self, lease, evidence, *, now):
        self.promotions += 1
        return ProfileActivationDecision(True, ())


class _ActivationProjection:
    def adapter_for(self, identity):
        del identity
        return self

    async def capabilities(self):
        return SimpleNamespace(
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
            degraded_reason=None,
        )


class _HealthySessions:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return None
