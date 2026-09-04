from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.document_reconciliation import (
    PostgresExactDocumentObservationAdapter,
)
from infinity_context_adapters.postgres.locator_models import (
    MemoryLocatorProfileLaneRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileRow,
)
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_core.features.context_building.public import (
    ProfileQueryAdmissionStatus,
    RuntimeFenceOwner,
)
from infinity_context_core.features.document_ingestion.public import (
    DocumentIngestionScope,
    ExactDocumentIdentity,
    SourceDocumentOrigin,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

NOW = datetime(2026, 8, 26, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def test_exact_reconciliation_equals_real_query_admission_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_equivalence(database_url))


async def _assert_equivalence(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="exact_admission_equivalence", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        await _seed(sessions)
        # Canonical receipt/lane triggers invalidate any lease that predates
        # their evidence. Reissue the fixture lease only after those writes.
        await _apply_mode(sessions, "queryable")
        registry = PostgresRetrievalProfileRegistry(sessions)
        observer = PostgresExactDocumentObservationAdapter(sessions)
        owner = RuntimeFenceOwner.unrecoverable_current(
            instance_id="exact-admission-runtime",
            generation="exact-admission-generation",
            key_id="equivalence-unrecoverable",
        )
        await registry.register_runtime_incarnation(owner, now=NOW)

        await _assert_same(registry, observer, owner, "queryable", admitted=True)
        for mode in (
            "missing_lease",
            "expired_lease",
            "missing_evidence",
            "drift",
            "epoch_mismatch",
            "active_mutation",
            "provider_loss",
        ):
            await _apply_mode(sessions, mode)
            await _assert_same(registry, observer, owner, mode, admitted=False)
        await registry.retire_runtime_incarnation(owner, now=NOW)
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_same(registry, observer, owner, operation_id: str, *, admitted: bool) -> None:
    observation = (await observer.observe_exact_document(_identity()))[0]
    admission = await registry.begin_profile_query(
        f"query-{operation_id}", owner=owner, now=NOW, expires_at=FUTURE
    )
    assert (observation.visibility == "indexed") is admitted, (observation, admission)
    assert (admission.status is ProfileQueryAdmissionStatus.ADMITTED) is admitted, (
        observation,
        admission,
    )
    if admitted:
        assert admission.identity is not None
        assert admission.activation_lease_id is not None
        await registry.finish_profile_query(
            admission.identity.profile_id,
            f"query-{operation_id}",
            owner=owner,
            activation_lease_id=admission.activation_lease_id,
        )


async def _apply_mode(sessions, mode: str) -> None:
    async with sessions.begin() as session:
        profile = await session.get(MemoryLocatorProfileRow, "profile-id")
        lane = await session.get(MemoryLocatorProfileLaneRow, ("profile-id", "qdrant_dense"))
        assert profile is not None and lane is not None
        profile.activation_lease_id = "lease-1"
        profile.activation_evidence_digest = "d" * 64
        profile.activation_lease_issued_at = NOW
        profile.activation_lease_expires_at = FUTURE
        profile.activation_evidence_version = 1
        profile.reconciliation_drifted = False
        profile.activation_mutation_epoch = 4
        profile.provider_mutation_epoch = 4
        lane.healthy = True
        lane.profile_qualified = True
        await session.execute(
            delete(MemoryLocatorProfileProviderMutationRow).where(
                MemoryLocatorProfileProviderMutationRow.profile_id == "profile-id"
            )
        )
        if mode == "missing_lease":
            profile.activation_lease_id = None
            profile.activation_evidence_digest = None
            profile.activation_lease_issued_at = None
            profile.activation_lease_expires_at = None
        elif mode == "expired_lease":
            profile.activation_lease_issued_at = datetime(1999, 1, 1, tzinfo=UTC)
            profile.activation_lease_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
        elif mode == "missing_evidence":
            profile.activation_evidence_version = 0
        elif mode == "drift":
            profile.reconciliation_drifted = True
        elif mode == "epoch_mismatch":
            profile.provider_mutation_epoch = 5
        elif mode == "provider_loss":
            lane.healthy = False
            lane.profile_qualified = False
        elif mode == "active_mutation":
            session.add(
                MemoryLocatorProfileProviderMutationRow(
                    profile_id="profile-id",
                    operation_id="mutation-1",
                    owner_instance_id=owner_id(),
                    owner_generation="exact-admission-generation",
                    started_epoch=4,
                    started_at=NOW,
                    expires_at=FUTURE,
                )
            )


def owner_id() -> str:
    return "exact-admission-runtime"


async def _seed(sessions) -> None:
    async with sessions.begin() as session:
        document = MemoryDocumentRow(
            id="doc-1",
            space_id="space",
            memory_scope_id="scope",
            thread_id="thread",
            title="Evidence",
            source_type="opaque-kind",
            source_external_id="target",
            content_hash="hash-1",
            classification="internal",
            status="active",
            retrieval_projected=True,
            created_at=NOW,
            updated_at=NOW,
        )
        chunk = MemoryChunkRow(
            id="chunk-1",
            space_id="space",
            memory_scope_id="scope",
            thread_id="thread",
            document_id=document.id,
            episode_id=None,
            source_type="opaque-kind",
            source_external_id="target",
            source_hash="source-1",
            kind="paragraph",
            text="evidence",
            normalized_text="evidence",
            status="active",
            sequence=0,
            char_start=0,
            char_end=8,
            token_estimate=2,
            classification="internal",
            created_at=NOW,
            updated_at=NOW,
            metadata_json={},
            retrieval_locator="locator-1",
            retrieval_source_key="source",
            retrieval_projection_generation="projection-1",
            retrieval_sequence_ordinal=0,
            retrieval_kind="document",
            retrieval_version=3,
            retrieval_actor_keys_json=[],
            retrieval_category="document",
            retrieval_tags_json=[],
            retrieval_commit_watermark=3,
        )
        session.add(document)
        await session.flush()
        session.add(chunk)
        profile = MemoryLocatorProfileRow(
            profile_id="profile-id",
            generation="profile-1",
            profile_digest="a" * 64,
            collection_name="collection",
            state="active",
            backfill_complete=True,
            canonical_watermark=3,
            projected_watermark=3,
            expected_count=1,
            projected_count=1,
            expected_digest="b" * 64,
            projected_digest="b" * 64,
            created_at=NOW,
            reconciliation_drifted=False,
            activation_lease_id="lease-1",
            activation_evidence_digest="d" * 64,
            activation_lease_issued_at=NOW,
            activation_lease_expires_at=FUTURE,
            activation_evidence_version=1,
            activation_mutation_epoch=4,
            provider_mutation_epoch=4,
        )
        session.add(profile)
        await session.flush()
        await session.refresh(chunk)
        session.add_all(
            [
                MemoryLocatorProfileLaneRow(
                    profile_id="profile-id",
                    lane_id="qdrant_dense",
                    required=True,
                    healthy=True,
                    profile_qualified=True,
                    checked_at=NOW,
                    observed_count=1,
                    observed_digest="b" * 64,
                ),
                MemoryLocatorProfileProjectionReceiptRow(
                    profile_id="profile-id",
                    chunk_id=chunk.id,
                    canonical_version=chunk.retrieval_version,
                    canonical_watermark=3,
                    payload_digest="c" * 64,
                    projected_at=NOW,
                ),
            ]
        )


def _identity() -> ExactDocumentIdentity:
    return ExactDocumentIdentity(
        DocumentIngestionScope("space", "scope", "thread"),
        SourceDocumentOrigin("opaque-kind", "target"),
        "projection-1",
        "profile-1",
    )
