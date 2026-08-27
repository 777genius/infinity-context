from __future__ import annotations

import asyncio
import hashlib
import tracemalloc
from datetime import UTC, datetime, timedelta

import pytest

from infinity_context_core.features.context_building.application.retrieval_profile_lifecycle import (  # noqa: E501
    RetrievalProfileLifecycle,
)
from infinity_context_core.features.context_building.domain.retrieval_profile_lifecycle import (
    ProfileActivationEvidence,
    ProfileAttestationLease,
    ProfileCoverageAttestation,
    ProfileLaneHealth,
    ProfileQueueHealth,
    ProfileTombstoneHealth,
    RetrievalProfileIdentity,
    accumulate_attestation_digest,
    assess_profile_activation,
    finalize_attestation_digest,
)
from infinity_context_core.features.context_building.ports.retrieval_profile_lifecycle import (
    CanonicalProjectionItem,
    CanonicalProjectionPage,
    ExactVersionDeletionProof,
    ProfileTombstoneDeleteAuthorization,
)

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def test_tombstone_authority_and_readback_proof_bind_exact_observed_generation() -> None:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "locator")
    authorization = ProfileTombstoneDeleteAuthorization(identity, "chunk-a", 8, 4)
    proof = ExactVersionDeletionProof(("chunk-a",), 7, (None,), 6)

    assert authorization.canonical_id == "chunk-a"
    assert authorization.canonical_version == 8
    assert authorization.provider_mutation_epoch == 4
    assert proof.canonical_version == 7
    assert proof.remaining_canonical_versions == (None,)
    assert proof.provider_mutation_epoch == 6
    with pytest.raises(ValueError):
        ExactVersionDeletionProof(("chunk-a",), True, (None,))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExactVersionDeletionProof(("chunk-a", "chunk-a"), 7, (None, None))


def test_activation_requires_every_exact_operational_gate() -> None:
    evidence = ProfileActivationEvidence(
        coverage=ProfileCoverageAttestation(2, 1, "a" * 64, "b" * 64, 9, 9, False),
        queue=ProfileQueueHealth(3, 1, NOW - timedelta(minutes=6), NOW),
        lanes=(ProfileLaneHealth("dense", True, False, False),),
        tombstones=ProfileTombstoneHealth(2, 1),
    )
    decision = assess_profile_activation(evidence, maximum_queue_lag=timedelta(minutes=5))
    assert decision.accepted is False
    assert decision.rejection_reasons == (
        "backfill_incomplete",
        "coverage_count_mismatch",
        "coverage_digest_mismatch",
        "projection_jobs_dead",
        "projection_queue_lag_exceeded",
        "required_lane_unhealthy",
        "required_lane_unqualified",
        "retained_profile_tombstones_incomplete",
    )


def test_resumable_backfill_projects_and_checkpoints_one_bounded_page() -> None:
    registry = _Registry()
    source = _Source()
    projection = _Projection()
    diagnostics = _Diagnostics()
    lifecycle = RetrievalProfileLifecycle(registry, source, projection, diagnostics, page_size=2)

    result = asyncio.run(lifecycle.rebuild_page(now=NOW))

    assert result.projected_count == 1
    assert result.next_cursor == "chunk-a"
    assert projection.prepared == ["profile-a"]
    assert projection.profile_ids == ["profile-a"]
    assert registry.checkpoint == ("chunk-a", 7, False)
    assert diagnostics.events == [("profile-a", "backfill_projected", 1)]


def test_backfill_version_fenced_cleanup_removes_a_write_that_raced_canonical_state() -> None:
    registry = _Registry()
    registry.stale = True
    projection = _Projection()
    lifecycle = RetrievalProfileLifecycle(
        registry, _Source(), projection, _Diagnostics(), page_size=2
    )

    try:
        asyncio.run(lifecycle.rebuild_page(now=NOW))
    except RuntimeError as exc:
        assert str(exc) == "retrieval_profile_stale_projection_write"
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("stale projection receipt was accepted")

    assert projection.deletes == [("profile-a", ("chunk-a",), 1)]
    assert registry.checkpoint is None


def test_attestation_digest_is_streaming_resumable_and_page_size_independent() -> None:
    rows = (("c", 3, "c" * 64), ("a", 1, "a" * 64), ("b", 2, "b" * 64))

    def digest(pages):
        accumulator = "0" * 64
        count = 0
        for page in pages:
            for identity, version, payload_digest in page:
                accumulator = accumulate_attestation_digest(
                    accumulator, identity, version, payload_digest
                )
                count += 1
        return finalize_attestation_digest(count, accumulator)

    assert digest((rows,)) == digest((rows[:1], rows[1:]))
    assert digest((rows,)) == digest((tuple(reversed(rows)),))
    independent_sum = sum(
        int(hashlib.sha256(f"{identity}\0{version}\0{payload_digest}\n".encode()).hexdigest(), 16)
        for identity, version, payload_digest in rows
    ) % (1 << 256)
    independent = hashlib.sha256(f"{len(rows)}\0{independent_sum:064x}".encode()).hexdigest()
    assert digest((rows,)) == independent


def test_activation_lease_expires_fail_closed() -> None:
    lease = ProfileAttestationLease(
        "lease-a",
        "profile-a",
        "generation-a",
        "a" * 64,
        NOW,
        NOW + timedelta(seconds=30),
    )
    assert lease.valid_at(NOW + timedelta(seconds=29)) is True
    assert lease.valid_at(NOW + timedelta(seconds=30)) is False


def test_large_attestation_stream_has_constant_memory() -> None:
    def streamed_digest(page_size: int) -> str:
        accumulator = "0" * 64
        count = 0
        for page_start in range(0, 10_000, page_size):
            page_end = min(page_start + page_size, 10_000)
            for index in range(page_start, page_end):
                accumulator = accumulate_attestation_digest(
                    accumulator, f"chunk-{index:08d}", 1, "a" * 64
                )
                count += 1
        return finalize_attestation_digest(count, accumulator)

    tracemalloc.start()
    small_pages = streamed_digest(7)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert small_pages == streamed_digest(997)
    assert peak < 1_000_000


class _Registry:
    identity = RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "c-a")
    checkpoint = None

    def __init__(self):
        self.checkpoint = None
        self.stale = False

    async def building(self):
        return self.identity

    async def backfill_cursor(self, profile_id):
        assert profile_id == "profile-a"
        return None

    async def backfill_complete(self, profile_id):
        return False

    async def record_projection(self, profile_id, items, *, projected_at):
        assert profile_id == "profile-a" and len(items) == 1
        assert projected_at == NOW
        if self.stale:
            raise RuntimeError("retrieval_profile_stale_projection_write")

    async def checkpoint_backfill(
        self, profile_id, *, previous_cursor, cursor, watermark, complete, now
    ):
        assert previous_cursor is None
        self.checkpoint = (cursor, watermark, complete)


class _Source:
    async def page_eligible(self, *, after, limit):
        assert after is None and limit == 2
        return CanonicalProjectionPage(
            (
                CanonicalProjectionItem(
                    "chunk-a",
                    1,
                    7,
                    "b" * 64,
                    "space-a",
                    "scope-a",
                    None,
                    "safe projection text",
                    (),
                ),
            ),
            "chunk-a",
            7,
        )


class _Projection:
    def __init__(self):
        self.prepared = []
        self.profile_ids = []
        self.deletes = []

    async def prepare_profile(self, identity):
        self.prepared.append(identity.profile_id)

    async def upsert_profile(self, identity, items):
        self.profile_ids.append(identity.profile_id)

    async def delete_profile_if_version(self, identity, canonical_ids, *, canonical_version):
        self.deletes.append((identity.profile_id, canonical_ids, canonical_version))


class _Diagnostics:
    def __init__(self):
        self.events = []

    def record(self, profile_id, event, value=1):
        self.events.append((profile_id, event, value))
