from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactOutbox,
)
from infinity_context_adapters.postgres.benchmark_run_models import (
    MemoryComparisonBenchmarkRunRow,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemorySpaceRow
from infinity_context_adapters.postgres.orm import Base
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.postgres.projection_receipt_models import (
    MemoryCleanupV3ContextAuthorityRow,
    MemoryProjectionReceiptClaimRow,
    MemoryProjectionReceiptIdentityLinkRow,
    MemoryProjectionResultReceiptRow,
    MemoryProjectionTargetIdentityRow,
)
from infinity_context_adapters.postgres.projection_receipt_repository import (
    PostgresProjectionReceiptRepository,
    _validate_production_payload,
)
from infinity_context_adapters.postgres.repositories import PostgresOutbox
from infinity_context_adapters.qdrant.identity_evidence import qdrant_point_id_for_chunk
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.features.memory_facts.domain import MemoryFactScope
from infinity_context_core.features.memory_facts.ports import MemoryFactOutboxMessage
from infinity_context_core.features.projection_receipts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    ProjectionTargetIdentity,
    build_projection_result_receipt,
    ensure_projection_and_readback,
    ensure_projection_deleted_and_readback,
    projection_outbox_event_commitment,
    verify_projection_result_receipt,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    CHUNKER_POLICY_SHA256,
    LIMITS_POLICY_SHA256,
    LOCOMO_PROFILE,
    PROFILE_ORACLES,
    PROJECTOR_POLICY_SHA256,
    ManagedCleanupV3Authority,
    ManagedCleanupV3Error,
    build_context,
    commitment,
    merkle_root,
)
from infinity_context_server.projection_receipt_worker import ProjectionReceiptWorker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

D = "d" * 64
T = "a" * 64
RUN = "b" * 64
BINDING = "1" * 64
SPACE_SLUG = "memory-comparison-receipts"
SPACE_ID = f"benchmark-space-{RUN[:48]}"
CLEANUP_PLAN, CLEANUP_PLAN_SHA256 = cleanup_plan_pair(
    run_id=RUN,
    binding=BINDING,
    target=T,
    space_slug=SPACE_SLUG,
)
AUTHENTICATOR = ProjectionReceiptAuthenticator(b"r" * 32)
WHEN = datetime(2026, 8, 9, tzinfo=UTC)


def _managed_v3_context():
    qdrant_target = CLEANUP_PLAN["qdrant"]["target_commitment_sha256"]
    graphiti_target = CLEANUP_PLAN["graphiti"]["target_commitment_sha256"]
    qdrant_policy = "7" * 64
    graphiti_policy = "8" * 64
    return build_context(
        profile_id=LOCOMO_PROFILE,
        manifest_context_sha256="0" * 64,
        a1_terminal_commitment_sha256="1" * 64,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        publishable_profile_commitment_sha256="2" * 64,
        methodology_commitment_sha256="3" * 64,
        dataset_sha256=str(PROFILE_ORACLES[LOCOMO_PROFILE]["dataset_sha256"]),
        admission_commitment_sha256="4" * 64,
        ingestion_root_sha256=D,
        case_manifest_sha256="5" * 64,
        infinity_target_identity_sha256=T,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        cleanup_target_authority_sha256="6" * 64,
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": qdrant_target,
                "policy_commitment_sha256": qdrant_policy,
            },
        ),
        qdrant_target_commitment_sha256=qdrant_target,
        qdrant_policy_commitment_sha256=qdrant_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": graphiti_target,
                "policy_commitment_sha256": graphiti_policy,
            },
        ),
        graphiti_target_commitment_sha256=graphiti_target,
        graphiti_policy_commitment_sha256=graphiti_policy,
        cognee_policy_sha256="a" * 64,
        namespace_policy_sha256="b" * 64,
        cleanup_operation_stream_root_sha256="c" * 64,
        omitted_source_identity_root_sha256=str(
            PROFILE_ORACLES[LOCOMO_PROFILE]["omitted_source_identity_root_sha256"]
        ),
    )


V3_CONTEXT = _managed_v3_context()
CONTEXT = V3_CONTEXT.context_sha256


def _managed_v3_authority() -> ManagedCleanupV3Authority:
    oracle = PROFILE_ORACLES[LOCOMO_PROFILE]
    pages = ("e" * 64,)
    body = {
        "schema_version": "memory-comparison-paged-cleanup-authority.v4",
        "profile_id": LOCOMO_PROFILE,
        "context_sha256": CONTEXT,
        "a1_terminal_commitment_sha256": V3_CONTEXT.a1_terminal_commitment_sha256,
        "operation_count": oracle["operation_count"],
        "valid_message_count": oracle["valid_message_count"],
        "original_pair_slot_count": oracle["original_pair_slot_count"],
        "fully_invalid_pair_slot_count": oracle["fully_invalid_pair_slot_count"],
        "fragment_count": oracle["fragment_count"],
        "corpus_thread_identity_count": oracle["corpus_count"],
        "corpus_thread_identity_root_sha256": "1" * 64,
        "document_source_ref_count": 0,
        "document_source_ref_root_sha256": "2" * 64,
        "page_count": 1,
        "ordered_page_sha256": list(pages),
        "pages_merkle_root_sha256": merkle_root(pages),
        "a1_operation_stream_root_sha256": "f" * 64,
        "cleanup_operation_stream_root_sha256": (V3_CONTEXT.cleanup_operation_stream_root_sha256),
        "omitted_source_identity_root_sha256": (V3_CONTEXT.omitted_source_identity_root_sha256),
        "projector_policy_sha256": PROJECTOR_POLICY_SHA256,
        "chunker_policy_sha256": CHUNKER_POLICY_SHA256,
        "limits_policy_sha256": LIMITS_POLICY_SHA256,
    }
    return ManagedCleanupV3Authority(
        **{
            key: tuple(value) if key == "ordered_page_sha256" else value
            for key, value in body.items()
            if key != "schema_version"
        },
        terminal_commitment_sha256=commitment("authority/v4", body),
    )


V3_AUTHORITY = _managed_v3_authority()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("original_pair_slot_count", False),
        ("fully_invalid_pair_slot_count", False),
        ("fragment_count", False),
        ("document_source_ref_count", False),
        ("page_count", True),
    ),
)
def test_managed_v4_authority_rejects_boolean_counts(field: str, value: bool) -> None:
    body = V3_AUTHORITY.payload(False)
    body[field] = value
    with pytest.raises(ManagedCleanupV3Error, match="count_invalid"):
        ManagedCleanupV3Authority(
            **{
                key: tuple(item) if key == "ordered_page_sha256" else item
                for key, item in body.items()
                if key != "schema_version"
            },
            terminal_commitment_sha256=commitment("authority/v4", body),
        )


def _event_commitment(
    *,
    message_key: str | None,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int | None,
    payload: dict[str, object],
) -> str:
    return projection_outbox_event_commitment(
        message_key=message_key,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        payload=payload,
        created_at=WHEN.isoformat(),
    )


def _binding() -> ProjectionJobBinding:
    return ProjectionJobBinding(
        outbox_id=7,
        run_id_sha256=RUN,
        context_sha256=CONTEXT,
        lane="qdrant",
        space_id=SPACE_ID,
        memory_scope_id="scope-1",
        thread_id="thread-1",
        aggregate_type="chunk",
        aggregate_id="chunk-1",
        aggregate_version=None,
        target_authority_sha256=V3_CONTEXT.qdrant_authority_sha256,
        worker_authority_sha256=AUTHENTICATOR.authority_sha256,
        lineage_root_sha256=D,
        outbox_event_commitment_sha256=_event_commitment(
            message_key="projection-7",
            event_type="vector.upsert_chunk",
            aggregate_type="chunk",
            aggregate_id="chunk-1",
            aggregate_version=None,
            payload={"chunk_id": "chunk-1"},
        ),
    )


def _delete_binding() -> ProjectionJobBinding:
    return replace(
        _binding(),
        outbox_id=8,
        context_sha256=CONTEXT,
        aggregate_type="benchmark_run",
        aggregate_id=RUN,
        outbox_event_commitment_sha256=_event_commitment(
            message_key="projection-delete-8",
            event_type="vector.delete_chunks",
            aggregate_type="benchmark_run",
            aggregate_id=RUN,
            aggregate_version=None,
            payload={
                "chunk_ids": ["chunk-1"],
                "space_id": SPACE_ID,
                "cleanup_run_id_sha256": RUN,
            },
        ),
    )


def _identity(value: str = "chunk-1") -> ProjectionTargetIdentity:
    return ProjectionTargetIdentity(
        kind="qdrant_point_id",
        canonical_source_id=value,
        physical_identity=qdrant_point_id_for_chunk(value),
        lineage_root_sha256=D,
        target_authority_sha256=V3_CONTEXT.qdrant_authority_sha256,
    )


class FakeProvider:
    def __init__(self, reads: list[tuple[ProjectionMaterialization, ...]]) -> None:
        self.reads = reads
        self.upserts = 0
        self.deletes = 0

    async def read_exact(self, _binding):
        return self.reads.pop(0)

    async def upsert_exact(self, _binding, _identities):
        self.upserts += 1

    async def delete_exact(self, _binding, _identities):
        self.deletes += 1
        return WHEN


def _materialization(
    *identities: ProjectionTargetIdentity,
    binding: ProjectionJobBinding | None = None,
) -> ProjectionMaterialization:
    effective = binding or _binding()
    return ProjectionMaterialization(
        projection_key_sha256=effective.projection_key_sha256,
        identities=tuple(identities),
        completed_at=WHEN,
    )


def test_absent_projection_is_upserted_once_then_read_back_exactly() -> None:
    identity = _identity()
    provider = FakeProvider([(), (_materialization(identity),)])

    observed = asyncio.run(
        ensure_projection_and_readback(
            provider,
            binding=_binding(),
            expected_identities=(identity,),
        )
    )

    assert provider.upserts == 1
    assert observed.identities == (identity,)


def test_exact_existing_projection_replays_without_upsert_and_order_is_canonical() -> None:
    first = _identity("point-b")
    second = _identity("point-a")
    provider = FakeProvider([(_materialization(second, first),)])

    observed = asyncio.run(
        ensure_projection_and_readback(
            provider,
            binding=_binding(),
            expected_identities=(first, second),
        )
    )
    receipt = build_projection_result_receipt(
        binding=_binding(),
        materialization=observed,
        authenticator=ProjectionReceiptAuthenticator(b"k" * 32),
        persisted_at=WHEN,
    )

    assert provider.upserts == 0
    assert [item.identity_sha256 for item in receipt.identities] == sorted(
        item.identity_sha256 for item in receipt.identities
    )
    assert len(receipt.receipt_sha256) == 64
    assert len(receipt.receipt_mac_sha256) == 64


def test_existing_projection_is_deleted_once_and_fresh_absence_is_proved() -> None:
    identity = _identity()
    assert identity.canonical_source_id == "chunk-1"
    assert identity.physical_identity != identity.canonical_source_id
    provider = FakeProvider([(_materialization(identity),), ()])

    observed = asyncio.run(
        ensure_projection_deleted_and_readback(
            provider,
            binding=_binding(),
            expected_identities=(identity,),
            observed_at=WHEN,
        )
    )
    receipt = build_projection_result_receipt(
        binding=_binding(),
        materialization=observed,
        authenticator=ProjectionReceiptAuthenticator(b"r" * 32),
        persisted_at=WHEN,
        operation="delete",
        result_state="absent",
    )

    assert provider.deletes == 1
    assert receipt.operation == "delete"
    assert receipt.result_state == "absent"


def test_existing_absence_replays_without_delete() -> None:
    provider = FakeProvider([()])

    asyncio.run(
        ensure_projection_deleted_and_readback(
            provider,
            binding=_binding(),
            expected_identities=(_identity(),),
            observed_at=WHEN,
        )
    )

    assert provider.deletes == 0


@pytest.mark.parametrize(
    ("reads", "code"),
    [
        ([(), ()], "projection_receipt.readback_absent"),
        (
            [(_materialization(_identity()), _materialization(_identity()))],
            "projection_receipt.readback_multiple",
        ),
        (
            [(_materialization(_identity("other")),)],
            "projection_receipt.readback_divergent",
        ),
    ],
)
def test_readback_fails_closed(reads, code: str) -> None:
    with pytest.raises(ProjectionReceiptError) as caught:
        asyncio.run(
            ensure_projection_and_readback(
                FakeProvider(reads),
                binding=_binding(),
                expected_identities=(_identity(),),
            )
        )
    assert caught.value.diagnostic_code == code


def test_foreign_lineage_and_short_hmac_capability_fail_closed() -> None:
    foreign = replace(_identity(), lineage_root_sha256="f" * 64)
    with pytest.raises(ProjectionReceiptError, match="readback_foreign"):
        asyncio.run(
            ensure_projection_and_readback(
                FakeProvider([(_materialization(foreign),)]),
                binding=_binding(),
                expected_identities=(_identity(),),
            )
        )
    with pytest.raises(ProjectionReceiptError, match="hmac_capability_invalid"):
        ProjectionReceiptAuthenticator(b"short")


def test_physical_identity_is_globally_stable_while_commitment_binds_lineage() -> None:
    original = _identity()
    divergent = replace(original, lineage_root_sha256="f" * 64)

    assert original.identity_sha256 == divergent.identity_sha256
    assert original.identity_commitment_sha256 != divergent.identity_commitment_sha256


@pytest.mark.parametrize("field", ["identity_mac_sha256", "identity_commitment_sha256"])
def test_forged_identity_or_link_commitment_is_rejected(field: str) -> None:
    receipt = build_projection_result_receipt(
        binding=_binding(),
        materialization=_materialization(_identity()),
        authenticator=ProjectionReceiptAuthenticator(b"r" * 32),
        persisted_at=WHEN,
    )
    forged_item = replace(receipt.identities[0], **{field: "0" * 64})
    forged = replace(receipt, identities=(forged_item,))

    with pytest.raises(ProjectionReceiptError, match="authentication_invalid"):
        verify_projection_result_receipt(forged, ProjectionReceiptAuthenticator(b"r" * 32))


def _payload_outbox(
    payload: dict[str, object], *, message_key: str | None = None
) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        message_key=message_key,
        event_type="test",
        aggregate_type="test",
        aggregate_id="test",
        aggregate_version=None,
        workload_class="projection",
        fairness_key=None,
        payload_json=payload,
        status="running",
        attempt_count=0,
        next_attempt_at=WHEN,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=WHEN,
        updated_at=WHEN,
    )


def test_exact_production_payload_shapes_reject_invented_authority_fields() -> None:
    qdrant_upsert = build_projection_result_receipt(
        binding=_binding(),
        materialization=_materialization(_identity()),
        authenticator=AUTHENTICATOR,
        persisted_at=WHEN,
    )
    _validate_production_payload(_payload_outbox({"chunk_id": "chunk-1"}), qdrant_upsert)
    with pytest.raises(ProjectionReceiptError, match="outbox_payload_divergent"):
        _validate_production_payload(
            _payload_outbox({"chunk_id": "chunk-1", "run_id_sha256": RUN}), qdrant_upsert
        )

    graph_binding = replace(
        _binding(),
        lane="graphiti",
        aggregate_type="fact",
        aggregate_id="fact-1",
        aggregate_version=1,
        target_authority_sha256=V3_CONTEXT.graphiti_authority_sha256,
    )
    graph_identity = ProjectionTargetIdentity(
        kind="graphiti_episode_uuid",
        canonical_source_id="fact-1",
        physical_identity="episode-uuid-1",
        lineage_root_sha256=D,
        target_authority_sha256=V3_CONTEXT.graphiti_authority_sha256,
    )
    graph_upsert = build_projection_result_receipt(
        binding=graph_binding,
        materialization=_materialization(graph_identity, binding=graph_binding),
        authenticator=AUTHENTICATOR,
        persisted_at=WHEN,
    )
    _validate_production_payload(
        _payload_outbox(
            {
                "message_id": "message-1",
                "fact_id": "fact-1",
                "version": 1,
                "space_id": SPACE_ID,
                "memory_scope_id": "scope-1",
                "thread_id": "thread-1",
                "occurred_at": WHEN.isoformat(),
            },
            message_key="message-1",
        ),
        graph_upsert,
    )

    qdrant_delete = build_projection_result_receipt(
        binding=_delete_binding(),
        materialization=_materialization(_identity(), binding=_delete_binding()),
        authenticator=AUTHENTICATOR,
        persisted_at=WHEN,
        operation="delete",
        result_state="absent",
    )
    _validate_production_payload(
        _payload_outbox(
            {"chunk_ids": ["chunk-1"], "space_id": SPACE_ID, "cleanup_run_id_sha256": RUN}
        ),
        qdrant_delete,
    )

    graph_delete_binding = replace(
        graph_binding,
        outbox_id=9,
        aggregate_type="benchmark_run",
        aggregate_version=None,
    )
    graph_delete = build_projection_result_receipt(
        binding=graph_delete_binding,
        materialization=_materialization(graph_identity, binding=graph_delete_binding),
        authenticator=AUTHENTICATOR,
        persisted_at=WHEN,
        operation="delete",
        result_state="absent",
    )
    _validate_production_payload(
        _payload_outbox({"fact_id": "fact-1", "space_id": SPACE_ID, "cleanup_run_id_sha256": RUN}),
        graph_delete,
    )


def test_actual_postgres_outbox_writers_match_receipt_payload_validation() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: Base.metadata.create_all(sync, tables=(MemoryOutboxRow.__table__,))
            )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session, session.begin():
            await PostgresOutbox(session, WHEN).enqueue(
                OutboxEvent(
                    event_type="vector.upsert_chunk",
                    aggregate_type="chunk",
                    aggregate_id="chunk-1",
                    payload={"chunk_id": "chunk-1"},
                )
            )
            await PostgresMemoryFactOutbox(session, now=WHEN).enqueue(
                MemoryFactOutboxMessage(
                    message_id="message-1",
                    event_type="graph.upsert_fact",
                    aggregate_id="fact-1",
                    aggregate_version=1,
                    scope=MemoryFactScope(SPACE_ID, "scope-1", "thread-1"),
                    occurred_at=WHEN,
                )
            )
        async with sessions() as session:
            rows = list((await session.execute(select(MemoryOutboxRow))).scalars())
        qdrant_row, graphiti_row = rows
        _validate_production_payload(
            qdrant_row,
            build_projection_result_receipt(
                binding=_binding(),
                materialization=_materialization(_identity()),
                authenticator=AUTHENTICATOR,
                persisted_at=WHEN,
            ),
        )
        graph_binding = replace(
            _binding(),
            outbox_id=graphiti_row.id,
            lane="graphiti",
            aggregate_type="fact",
            aggregate_id="fact-1",
            aggregate_version=1,
            target_authority_sha256=V3_CONTEXT.graphiti_authority_sha256,
        )
        graph_identity = ProjectionTargetIdentity(
            kind="graphiti_episode_uuid",
            canonical_source_id="fact-1",
            physical_identity="episode-uuid-1",
            lineage_root_sha256=D,
            target_authority_sha256=V3_CONTEXT.graphiti_authority_sha256,
        )
        _validate_production_payload(
            graphiti_row,
            build_projection_result_receipt(
                binding=graph_binding,
                materialization=_materialization(graph_identity, binding=graph_binding),
                authenticator=AUTHENTICATOR,
                persisted_at=WHEN,
            ),
        )
        await engine.dispose()

    asyncio.run(scenario())


def test_repository_atomically_persists_receipt_links_and_done_status() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        tables = (
            MemorySpaceRow.__table__,
            MemoryComparisonBenchmarkRunRow.__table__,
            MemoryOutboxRow.__table__,
            MemoryChunkRow.__table__,
            MemoryCleanupV3ContextAuthorityRow.__table__,
            MemoryProjectionReceiptClaimRow.__table__,
            MemoryProjectionTargetIdentityRow.__table__,
            MemoryProjectionResultReceiptRow.__table__,
            MemoryProjectionReceiptIdentityLinkRow.__table__,
        )
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        await _seed_canonical_job(sessions)
        async with sessions() as session, session.begin():
            session.add(
                MemoryProjectionTargetIdentityRow(
                    run_id_sha256=RUN,
                    kind="qdrant_point_id",
                    identity_sha256="7" * 64,
                    identity_commitment_sha256="8" * 64,
                    canonical_source_id="",
                    physical_identity="physical",
                    lineage_root_sha256=D,
                    target_authority_sha256=V3_CONTEXT.qdrant_authority_sha256,
                    identity_mac_sha256="9" * 64,
                    created_at=WHEN,
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
        async with sessions() as session, session.begin():
            repository = PostgresProjectionReceiptRepository(session, AUTHENTICATOR)
            assert await repository.register_context_authority(
                context=V3_CONTEXT,
                authority=V3_AUTHORITY,
                registered_at=WHEN,
            )
        async with sessions() as session, session.begin():
            repository = PostgresProjectionReceiptRepository(session, AUTHENTICATOR)
            assert not await repository.register_context_authority(
                context=V3_CONTEXT,
                authority=V3_AUTHORITY,
                registered_at=WHEN + timedelta(seconds=1),
            )
        async with sessions() as session, session.begin():
            row = await session.get(MemoryCleanupV3ContextAuthorityRow, CONTEXT)
            assert row is not None
            original_context = row.context_json
            row.context_json = {**original_context, "unexpected": "field"}
            with pytest.raises(ProjectionReceiptError, match="context_authority_invalid"):
                await PostgresProjectionReceiptRepository(
                    session, AUTHENTICATOR
                ).register_context_authority(
                    context=V3_CONTEXT,
                    authority=V3_AUTHORITY,
                    registered_at=WHEN,
                )
            row.context_json = original_context
            original_mac = row.registration_mac_sha256
            row.registration_mac_sha256 = "0" * 64
            with pytest.raises(ProjectionReceiptError, match="context_authority_invalid"):
                await PostgresProjectionReceiptRepository(
                    session, AUTHENTICATOR
                ).register_context_authority(
                    context=V3_CONTEXT,
                    authority=V3_AUTHORITY,
                    registered_at=WHEN,
                )
            row.registration_mac_sha256 = original_mac
        identity = _identity()
        receipt = build_projection_result_receipt(
            binding=_binding(),
            materialization=_materialization(identity),
            authenticator=ProjectionReceiptAuthenticator(b"r" * 32),
            persisted_at=WHEN,
        )
        async with sessions() as session, session.begin():
            outbox = await session.get(MemoryOutboxRow, 7)
            assert outbox is not None
            outbox.event_type = "vector.upsert_chunks"
            with pytest.raises(ProjectionReceiptError, match="outbox_event_divergent"):
                await PostgresProjectionReceiptRepository(
                    session, ProjectionReceiptAuthenticator(b"r" * 32)
                ).persist_and_mark_done(receipt)
            outbox.event_type = "vector.upsert_chunk"
        async with sessions() as session, session.begin():
            with pytest.raises(ProjectionReceiptError, match="authentication_invalid"):
                await PostgresProjectionReceiptRepository(
                    session, ProjectionReceiptAuthenticator(b"r" * 32)
                ).persist_and_mark_done(replace(receipt, receipt_mac_sha256="0" * 64))
        async with sessions() as session, session.begin():
            created = await PostgresProjectionReceiptRepository(
                session, ProjectionReceiptAuthenticator(b"r" * 32)
            ).persist_and_mark_done(receipt)
        async with sessions() as session, session.begin():
            replayed = await PostgresProjectionReceiptRepository(
                session, ProjectionReceiptAuthenticator(b"r" * 32)
            ).persist_and_mark_done(receipt)
        async with sessions() as session:
            outbox = await session.get(MemoryOutboxRow, 7)
            stored = await session.get(MemoryProjectionResultReceiptRow, 7)
            links = list(
                (await session.execute(select(MemoryProjectionReceiptIdentityLinkRow))).scalars()
            )
        assert created is True
        assert replayed is False
        assert outbox is not None and outbox.status == "done"
        assert outbox.updated_at.replace(tzinfo=UTC) == WHEN
        assert stored is not None and stored.receipt_sha256 == receipt.receipt_sha256
        assert len(links) == 1
        await _seed_grouped_delete_job(sessions)
        delete_receipt = build_projection_result_receipt(
            binding=_delete_binding(),
            materialization=_materialization(identity, binding=_delete_binding()),
            authenticator=ProjectionReceiptAuthenticator(b"r" * 32),
            persisted_at=WHEN,
            operation="delete",
            result_state="absent",
        )
        async with sessions() as session, session.begin():
            deleted = await PostgresProjectionReceiptRepository(
                session, ProjectionReceiptAuthenticator(b"r" * 32)
            ).persist_and_mark_done(delete_receipt)
        async with sessions() as session:
            delete_outbox = await session.get(MemoryOutboxRow, 8)
        assert deleted is True
        assert delete_outbox is not None and delete_outbox.status == "done"
        await engine.dispose()

    asyncio.run(scenario())


def test_worker_durable_replay_skips_all_provider_io() -> None:
    class StatefulProvider:
        def __init__(self) -> None:
            self.value: ProjectionMaterialization | None = None
            self.reads = 0
            self.upserts = 0

        async def read_exact(self, _binding):
            self.reads += 1
            return () if self.value is None else (self.value,)

        async def upsert_exact(self, binding, identities):
            self.upserts += 1
            self.value = ProjectionMaterialization(
                projection_key_sha256=binding.projection_key_sha256,
                identities=identities,
                completed_at=WHEN,
            )

        async def delete_exact(self, _binding, _identities):
            raise AssertionError("delete is not expected")

    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        tables = (
            MemorySpaceRow.__table__,
            MemoryComparisonBenchmarkRunRow.__table__,
            MemoryOutboxRow.__table__,
            MemoryChunkRow.__table__,
            MemoryCleanupV3ContextAuthorityRow.__table__,
            MemoryProjectionReceiptClaimRow.__table__,
            MemoryProjectionTargetIdentityRow.__table__,
            MemoryProjectionResultReceiptRow.__table__,
            MemoryProjectionReceiptIdentityLinkRow.__table__,
        )
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        await _seed_canonical_job(sessions)
        async with sessions() as session, session.begin():
            await PostgresProjectionReceiptRepository(
                session, AUTHENTICATOR
            ).register_context_authority(
                context=V3_CONTEXT, authority=V3_AUTHORITY, registered_at=WHEN
            )
        provider = StatefulProvider()
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        first = await worker.ensure_projection_and_readback(
            binding=_binding(), expected_identities=(_identity(),)
        )
        calls = (provider.reads, provider.upserts)
        second = await worker.ensure_projection_and_readback(
            binding=_binding(), expected_identities=(_identity(),)
        )
        assert second == first
        assert (provider.reads, provider.upserts) == calls
        await engine.dispose()

    asyncio.run(scenario())


async def _seed_canonical_job(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session, session.begin():
        session.add(
            MemorySpaceRow(
                id=SPACE_ID,
                slug=SPACE_SLUG,
                name="Space One",
                status="active",
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
        await session.flush()
        session.add(
            MemoryComparisonBenchmarkRunRow(
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=T,
                space_id=SPACE_ID,
                space_slug=SPACE_SLUG,
                idempotency_key_sha256="2" * 64,
                registration_fingerprint_sha256="3" * 64,
                state="active",
                cleanup_plan_json=CLEANUP_PLAN,
                cleanup_plan_sha256=CLEANUP_PLAN_SHA256,
                cleanup_plan_state="sealed",
                projection_manifest_json=None,
                projection_manifest_sha256=None,
                projection_cleanup_state="unsealed",
                cleanup_fingerprint_sha256=None,
                cleanup_receipt_json=None,
                finalization_fingerprint_sha256=None,
                completion_receipt_json=None,
                completed_at=None,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
        await session.flush()
        session.add(
            MemoryChunkRow(
                id="chunk-1",
                space_id=SPACE_ID,
                memory_scope_id="scope-1",
                thread_id="thread-1",
                document_id="document-1",
                episode_id=None,
                source_type="document",
                source_external_id="source-1",
                source_hash="source-hash-1",
                kind="text",
                text="text",
                normalized_text="text",
                status="active",
                sequence=0,
                char_start=0,
                char_end=4,
                token_estimate=1,
                classification="internal",
                created_at=WHEN,
                updated_at=WHEN,
                metadata_json={},
            )
        )
        session.add(
            MemoryOutboxRow(
                id=7,
                message_key="projection-7",
                event_type="vector.upsert_chunk",
                aggregate_type="chunk",
                aggregate_id="chunk-1",
                aggregate_version=None,
                workload_class="projection",
                fairness_key=None,
                payload_json={"chunk_id": "chunk-1"},
                status="running",
                attempt_count=0,
                next_attempt_at=WHEN,
                last_safe_error=None,
                last_safe_diagnostic_code=None,
                created_at=WHEN,
                updated_at=WHEN - timedelta(hours=1),
            )
        )


async def _seed_grouped_delete_job(sessions: async_sessionmaker[AsyncSession]) -> None:
    binding = _delete_binding()
    async with sessions() as session, session.begin():
        chunk = await session.get(MemoryChunkRow, "chunk-1")
        registry = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        assert chunk is not None and registry is not None
        chunk.status = "deleted"
        registry.state = "cleanup_pending"
        registry.projection_cleanup_state = "pending"
        registry.projection_manifest_json = {"sealed": True}
        registry.projection_manifest_sha256 = "5" * 64
        registry.cleanup_fingerprint_sha256 = "6" * 64
        registry.cleanup_receipt_json = {"disposition": "cleanup_pending"}
        session.add(
            MemoryOutboxRow(
                id=8,
                message_key="projection-delete-8",
                event_type="vector.delete_chunks",
                aggregate_type="benchmark_run",
                aggregate_id=binding.aggregate_id,
                aggregate_version=None,
                workload_class="projection",
                fairness_key="benchmark_cleanup:space-1",
                payload_json={
                    "chunk_ids": ["chunk-1"],
                    "space_id": binding.space_id,
                    "cleanup_run_id_sha256": binding.run_id_sha256,
                },
                status="running",
                attempt_count=0,
                next_attempt_at=WHEN,
                last_safe_error=None,
                last_safe_diagnostic_code=None,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
