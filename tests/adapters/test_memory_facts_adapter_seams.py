"""Import and placeholder checks for memory_facts adapter seams."""

from __future__ import annotations

import asyncio
import importlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    FactCodeScopeReference,
    FactEpistemicContext,
    FactFreshness,
    FactRetention,
    FactTemporalExtent,
    FactTemporalQueryMode,
    ForgetFactCommand,
    ForgetFactHandler,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
    MemoryFactVisibility,
    RememberFactCommand,
    RememberFactHandler,
    SupersedeFactCommand,
    SupersedeFactHandler,
    UpdateFactCommand,
    UpdateFactHandler,
)
from infinity_context_core.ports.capabilities import CapabilityStatus
from memory_fact_test_support import (
    EARLIER,
    NOW,
    FakeClock,
    FakeIds,
    _fact_snapshot,
    _outbox_message,
    _scope,
    _source_ref,
)
from sdk_module_isolation import provider_sdk_modules_unloaded


def test_memory_facts_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")

    assert module.FEATURE_ID == FEATURE_ID == "memory_facts"
    assert module.InMemoryMemoryFactRepository.feature_id == FEATURE_ID
    assert module.InMemoryMemoryFactOutbox.feature_id == FEATURE_ID
    assert module.InMemoryMemoryFactUnitOfWork.feature_id == FEATURE_ID
    assert module.InMemoryMemoryFactUnitOfWorkFactory.feature_id == FEATURE_ID
    assert module.PostgresMemoryFactStore.feature_id == FEATURE_ID
    assert module.QdrantMemoryFactProjection.feature_id == FEATURE_ID
    assert module.GraphitiMemoryFactProjection.feature_id == FEATURE_ID


def test_memory_facts_adapter_imports_do_not_load_provider_sdks() -> None:
    with provider_sdk_modules_unloaded(
        "sqlalchemy", "qdrant_client", "graphiti", "openai", "fastapi"
    ):
        importlib.import_module("infinity_context_adapters.features.memory_facts")

        assert "sqlalchemy" not in sys.modules
        assert "qdrant_client" not in sys.modules
        assert "graphiti" not in sys.modules
        assert "openai" not in sys.modules
        assert "fastapi" not in sys.modules


def test_in_memory_fact_store_uses_full_identity_and_requires_existing_on_save() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    seed = _fact_snapshot(
        fact_id="fact-1",
        scope=_scope(thread_id="thread-1"),
    )
    store = module.create_in_memory_memory_fact_store((seed,))

    assert asyncio.run(store.get(seed.identity)) == seed
    assert asyncio.run(store.get_for_update(seed.identity)) == seed
    assert (
        asyncio.run(
            store.get(
                MemoryFactIdentity(
                    fact_id="fact-1",
                    scope=_scope(thread_id="thread-2"),
                )
            )
        )
        is None
    )

    with pytest.raises(ValueError, match="memory_fact_already_exists"):
        asyncio.run(store.create(seed))

    same_fact_id_in_other_scope = _fact_snapshot(
        fact_id="fact-1",
        scope=_scope(memory_scope_id="scope-2"),
    )
    created = _fact_snapshot(fact_id="fact-2")
    updated = replace(
        created,
        text="Ada owns the public API runbook.",
        visibility=replace(created.visibility, version=2),
    )

    assert asyncio.run(store.create(same_fact_id_in_other_scope)) == same_fact_id_in_other_scope
    assert asyncio.run(store.create(created)) == created
    assert asyncio.run(store.save(updated)) == updated

    with pytest.raises(KeyError, match="memory_fact_not_found"):
        asyncio.run(store.save(_fact_snapshot(fact_id="missing")))


def test_in_memory_fact_unit_of_work_factory_seeds_snapshots() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    seed = _fact_snapshot(fact_id="seed-fact")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory((seed,))

    async def load_seed() -> MemoryFactSnapshot | None:
        async with factory() as uow:
            return await uow.facts.get(seed.identity)

    assert asyncio.run(load_seed()) == seed


def test_in_memory_fact_uow_drives_core_lifecycle_handlers() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory()
    ids = FakeIds(
        fact_ids=("fact-1",),
        outbox_message_ids=("outbox-1", "outbox-2", "outbox-3"),
        tombstone_ids=("tombstone-1",),
    )
    clock = FakeClock(NOW)
    source_ref = _source_ref("doc-1")
    remember = RememberFactHandler(uow_factory=factory, clock=clock, ids=ids)

    remembered = asyncio.run(
        remember.execute(
            RememberFactCommand(
                scope=_scope(),
                text="Ada owns the API runbook.",
                source_refs=(source_ref,),
                kind="ownership",
                category="operations",
                tags=("api",),
            )
        )
    )
    updated = asyncio.run(
        UpdateFactHandler(uow_factory=factory, clock=clock, ids=ids).execute(
            UpdateFactCommand(
                identity=remembered.fact.identity,
                expected_version=1,
                text="Ada owns the public API runbook.",
                source_refs=(_source_ref("doc-2"),),
                kind="ownership",
                category="operations",
                tags=("api", "public"),
            )
        )
    )
    forgotten = asyncio.run(
        ForgetFactHandler(uow_factory=factory, clock=clock, ids=ids).execute(
            ForgetFactCommand(
                identity=remembered.fact.identity,
                expected_version=2,
            )
        )
    )

    async def load_current() -> MemoryFactSnapshot | None:
        async with factory() as uow:
            return await uow.facts.get(remembered.fact.identity)

    assert remembered.fact.visibility == MemoryFactVisibility(status="active", version=1)
    assert updated.fact.visibility == MemoryFactVisibility(status="active", version=2)
    assert forgotten.tombstone_id == "tombstone-1"
    assert forgotten.fact.visibility == MemoryFactVisibility(status="deleted", version=3)
    assert asyncio.run(load_current()) == forgotten.fact

    async def load_versions() -> tuple[MemoryFactSnapshot, ...]:
        async with factory() as uow:
            return await uow.facts.list_versions(remembered.fact.identity)

    assert asyncio.run(load_versions()) == (
        remembered.fact,
        updated.fact,
        forgotten.fact,
    )
    assert factory.outbox_messages == (
        _outbox_message("outbox-1", "fact.created", remembered.fact),
        _outbox_message("outbox-2", "fact.updated", updated.fact),
        _outbox_message("outbox-3", "fact.deleted", forgotten.fact),
    )


def test_lifecycle_idempotency_replays_exact_immutable_results() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory()
    ids = FakeIds(
        fact_ids=("fact-1",),
        outbox_message_ids=("outbox-1", "outbox-2", "outbox-3", "outbox-4"),
        tombstone_ids=("tombstone-1",),
    )
    clock = FakeClock(NOW)
    remember_handler = RememberFactHandler(uow_factory=factory, clock=clock, ids=ids)
    remember_command = RememberFactCommand(
        scope=_scope(),
        text="Ada owns the API runbook.",
        source_refs=(_source_ref("doc-1"),),
        idempotency_key="remember-1",
    )

    remembered = asyncio.run(remember_handler.execute(remember_command))
    remembered_replay = asyncio.run(remember_handler.execute(remember_command))
    assert remembered_replay.fact == remembered.fact
    assert remembered_replay.outbox_message_ids == remembered.outbox_message_ids
    assert remembered.replayed is False
    assert remembered_replay.replayed is True
    with pytest.raises(ValueError, match="different fact command"):
        asyncio.run(
            remember_handler.execute(
                replace(remember_command, text="A different fact."),
            )
        )

    update_handler = UpdateFactHandler(uow_factory=factory, clock=clock, ids=ids)
    first_update_command = UpdateFactCommand(
        identity=remembered.fact.identity,
        expected_version=1,
        text="Ada owns the public API runbook.",
        source_refs=(_source_ref("doc-2"),),
        idempotency_key="update-1",
    )
    first_update = asyncio.run(update_handler.execute(first_update_command))
    second_update = asyncio.run(
        update_handler.execute(
            UpdateFactCommand(
                identity=remembered.fact.identity,
                expected_version=2,
                text="Ada owns the public API and incident runbooks.",
                source_refs=(_source_ref("doc-3"),),
            )
        )
    )
    assert second_update.fact.visibility.version == 3
    first_update_replay = asyncio.run(update_handler.execute(first_update_command))
    assert first_update_replay.fact == first_update.fact
    assert first_update_replay.outbox_message_ids == first_update.outbox_message_ids
    assert first_update_replay.replayed is True

    forget_handler = ForgetFactHandler(uow_factory=factory, clock=clock, ids=ids)
    forget_command = ForgetFactCommand(
        identity=remembered.fact.identity,
        expected_version=3,
        idempotency_key="forget-1",
    )
    forgotten = asyncio.run(forget_handler.execute(forget_command))
    forgotten_replay = asyncio.run(forget_handler.execute(forget_command))
    assert forgotten_replay.fact == forgotten.fact
    assert forgotten_replay.tombstone_id == forgotten.tombstone_id
    assert forgotten_replay.outbox_message_ids == forgotten.outbox_message_ids
    assert forgotten_replay.replayed is True
    assert forgotten.tombstone_id == "tombstone-1"
    assert len(factory.facts) == 1
    assert len(factory.outbox_messages) == 4


def test_in_memory_fact_uow_rolls_back_facts_and_outbox_messages_unless_committed() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    factory = module.create_in_memory_memory_fact_unit_of_work_factory()
    rolled_back = _fact_snapshot(fact_id="fact-rolled-back")
    not_committed = _fact_snapshot(fact_id="fact-not-committed")
    committed = _fact_snapshot(fact_id="fact-committed")
    rolled_back_message = _outbox_message("outbox-rolled-back", "fact.created", rolled_back)
    not_committed_message = _outbox_message("outbox-not-committed", "fact.created", not_committed)
    committed_message = _outbox_message("outbox-committed", "fact.created", committed)

    async def exercise() -> None:
        async with factory() as uow:
            await uow.facts.create(rolled_back)
            await uow.outbox.enqueue(rolled_back_message)
            await uow.rollback()

        async with factory() as uow:
            await uow.facts.create(not_committed)
            await uow.outbox.enqueue(not_committed_message)

        async with factory() as uow:
            assert await uow.facts.get(rolled_back.identity) is None
            assert await uow.facts.get(not_committed.identity) is None
            await uow.facts.create(committed)
            await uow.outbox.enqueue(committed_message)
            await uow.commit()

        async with factory() as uow:
            assert await uow.facts.get(rolled_back.identity) is None
            assert await uow.facts.get(not_committed.identity) is None
            assert await uow.facts.get(committed.identity) == committed

    asyncio.run(exercise())

    assert factory.outbox_messages == (committed_message,)


def test_postgres_fact_store_persists_full_versions_and_outbox(tmp_path: Path) -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.postgres_fact_store"
    )
    from infinity_context_adapters.postgres import (  # noqa: PLC0415
        build_async_engine,
        build_session_factory,
        create_schema,
    )
    from infinity_context_adapters.postgres.models import MemoryOutboxRow  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'facts.db'}")
        try:
            await create_schema(engine)
            session_factory = build_session_factory(engine)
            factory = module.create_postgres_memory_fact_unit_of_work_factory(
                session_factory=session_factory,
                clock=FakeClock(NOW),
            )
            ids = FakeIds(
                fact_ids=("fact-1",),
                outbox_message_ids=("outbox-1", "outbox-2"),
            )
            temporal = FactTemporalExtent.ongoing_state(
                observed_at=EARLIER,
                valid_from=EARLIER,
                basis="primary_evidence",
            )
            freshness = FactFreshness(
                last_confirmed_at=EARLIER,
                confirmation_basis="primary_evidence",
            )
            retention = FactRetention(ttl_policy="durable")
            epistemic = FactEpistemicContext(asserted_by="user-1")
            code_scope = FactCodeScopeReference(
                repository_id="repo-1",
                code_scope_id="code-scope-1",
            )
            remembered = await RememberFactHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=ids,
            ).execute(
                RememberFactCommand(
                    scope=_scope(),
                    text="Ada owns the API runbook.",
                    source_refs=(_source_ref("doc-1"),),
                    temporal_extent=temporal,
                    freshness=freshness,
                    retention=retention,
                    epistemic_context=epistemic,
                    code_scope=code_scope,
                )
            )
            updated = await UpdateFactHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=ids,
            ).execute(
                UpdateFactCommand(
                    identity=remembered.fact.identity,
                    expected_version=1,
                    text="Ada owns the public API runbook.",
                    source_refs=(_source_ref("doc-2"),),
                    retention=retention,
                )
            )

            async with factory() as uow:
                current = await uow.facts.get(remembered.fact.identity)
                versions = await uow.facts.list_versions(remembered.fact.identity)

            assert current == updated.fact
            assert versions == (remembered.fact, updated.fact)
            assert versions[0].freshness == freshness
            assert versions[0].temporal_extent == temporal
            assert versions[0].epistemic_context == epistemic
            assert versions[0].code_scope == code_scope
            assert updated.fact.temporal_extent == temporal
            assert updated.fact.epistemic_context == epistemic
            assert updated.fact.code_scope == code_scope

            async with session_factory() as session:
                outbox = tuple((await session.execute(select(MemoryOutboxRow))).scalars())
            assert tuple(row.message_key for row in outbox) == (
                "outbox-1",
                "outbox-2",
            )
            assert tuple(row.event_type for row in outbox) == (
                "fact.created",
                "fact.updated",
            )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_postgres_lifecycle_receipt_replays_without_duplicate_fact(tmp_path: Path) -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.postgres_fact_store"
    )
    from infinity_context_adapters.postgres import (  # noqa: PLC0415
        build_async_engine,
        build_session_factory,
        create_schema,
    )
    from infinity_context_adapters.postgres.feature_models import (  # noqa: PLC0415
        MemoryFactOperationReceiptRow,
    )
    from infinity_context_adapters.postgres.models import MemoryFactRow  # noqa: PLC0415
    from sqlalchemy import func, select  # noqa: PLC0415

    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'receipts.db'}")
        try:
            await create_schema(engine)
            session_factory = build_session_factory(engine)
            factory = module.create_postgres_memory_fact_unit_of_work_factory(
                session_factory=session_factory,
                clock=FakeClock(NOW),
            )
            handler = RememberFactHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=FakeIds(fact_ids=("fact-1",), outbox_message_ids=("outbox-1",)),
            )
            command = RememberFactCommand(
                scope=_scope(),
                text="Ada owns the API runbook.",
                source_refs=(_source_ref("doc-1"),),
                idempotency_key="remember-1",
            )

            first = await handler.execute(command)
            replay = await handler.execute(command)

            assert replay.fact == first.fact
            assert replay.outbox_message_ids == first.outbox_message_ids
            assert first.replayed is False
            assert replay.replayed is True
            async with session_factory() as session:
                fact_count = await session.scalar(select(func.count()).select_from(MemoryFactRow))
                receipt = (
                    await session.execute(select(MemoryFactOperationReceiptRow))
                ).scalar_one()
            assert fact_count == 1
            assert receipt.result_fact_id == "fact-1"
            assert receipt.result_fact_version == 1
            assert receipt.result_snapshot_json["temporal_extent"]["kind"] == "state"

            async with session_factory() as session:
                receipt = (
                    await session.execute(select(MemoryFactOperationReceiptRow))
                ).scalar_one()
                receipt.result_snapshot_json = {
                    **receipt.result_snapshot_json,
                    "identity": {
                        **receipt.result_snapshot_json["identity"],
                        "fact_id": "fact-corrupt",
                    },
                }
                await session.commit()

            with pytest.raises(ValueError, match="snapshot identity mismatch"):
                await handler.execute(command)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_postgres_fact_selection_filters_temporal_rows_before_limit(tmp_path: Path) -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.postgres_fact_store"
    )
    from infinity_context_adapters.postgres import (  # noqa: PLC0415
        build_async_engine,
        build_session_factory,
        create_schema,
    )

    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'selection.db'}")
        try:
            await create_schema(engine)
            session_factory = build_session_factory(engine)
            factory = module.create_postgres_memory_fact_unit_of_work_factory(
                session_factory=session_factory,
                clock=FakeClock(NOW),
            )
            historical_extent = FactTemporalExtent(
                kind="state",
                observed_at=EARLIER,
                valid_from=EARLIER,
                valid_to=NOW,
            )
            current = replace(
                _fact_snapshot(fact_id="current"),
                temporal_extent=FactTemporalExtent.ongoing_state(
                    observed_at=EARLIER,
                    valid_from=EARLIER,
                ),
            )
            historical = tuple(
                replace(
                    _fact_snapshot(fact_id=f"historical-{index:02d}"),
                    updated_at=NOW,
                    temporal_extent=historical_extent,
                )
                for index in range(55)
            )
            async with factory() as uow:
                for fact in (*historical, current):
                    await uow.facts.create(fact)
                await uow.commit()

            query = MemoryFactSelectionQuery(
                space_id="space-1",
                memory_scope_ids=("scope-1",),
                temporal_mode=FactTemporalQueryMode.CURRENT,
                reference_time=NOW,
                limit=1,
            )
            async with factory() as uow:
                selected = await uow.facts.find_eligible(query)

            assert selected == (current,)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_fact_selection_never_leaks_repository_or_code_scope() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_facts")
    temporal = FactTemporalExtent.ongoing_state(
        observed_at=EARLIER,
        valid_from=EARLIER,
    )
    global_fact = replace(
        _fact_snapshot(fact_id="global"),
        temporal_extent=temporal,
    )
    repo_a = replace(
        _fact_snapshot(fact_id="repo-a"),
        temporal_extent=temporal,
        code_scope=FactCodeScopeReference(
            repository_id="repo-a",
            code_scope_id="branch-a",
        ),
    )
    repo_b = replace(
        _fact_snapshot(fact_id="repo-b"),
        temporal_extent=temporal,
        code_scope=FactCodeScopeReference(
            repository_id="repo-b",
            code_scope_id="branch-b",
        ),
    )
    store = module.create_in_memory_memory_fact_store((global_fact, repo_a, repo_b))

    def selected(
        *,
        repository_id: str | None,
        code_scope_id: str | None,
    ) -> tuple[str, ...]:
        facts = asyncio.run(
            store.find_eligible(
                MemoryFactSelectionQuery(
                    space_id="space-1",
                    memory_scope_ids=("scope-1",),
                    temporal_mode=FactTemporalQueryMode.CURRENT,
                    reference_time=NOW,
                    limit=10,
                    repository_id=repository_id,
                    code_scope_id=code_scope_id,
                )
            )
        )
        return tuple(sorted(fact.identity.fact_id for fact in facts))

    assert selected(repository_id=None, code_scope_id=None) == ("global",)
    assert selected(repository_id="repo-a", code_scope_id=None) == ("global",)
    assert selected(repository_id="repo-a", code_scope_id="branch-a") == (
        "global",
        "repo-a",
    )


def test_postgres_supersession_commits_or_rolls_back_the_whole_decision(
    tmp_path: Path,
) -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.postgres_fact_store"
    )
    from infinity_context_adapters.postgres import (  # noqa: PLC0415
        build_async_engine,
        build_session_factory,
        create_schema,
    )
    from infinity_context_adapters.postgres.models import (  # noqa: PLC0415
        MemoryFactRelationRow,
        MemoryFactTemporalDecisionRow,
        MemoryOutboxRow,
    )
    from sqlalchemy import func, select  # noqa: PLC0415
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    def pair(prefix: str) -> tuple[MemoryFactSnapshot, MemoryFactSnapshot]:
        predecessor = replace(
            _fact_snapshot(fact_id=f"{prefix}-old"),
            temporal_extent=FactTemporalExtent.ongoing_state(
                observed_at=EARLIER,
                valid_from=EARLIER,
                basis="primary_evidence",
            ),
        )
        successor = replace(
            _fact_snapshot(fact_id=f"{prefix}-new"),
            temporal_extent=FactTemporalExtent.ongoing_state(
                observed_at=NOW,
                valid_from=NOW,
                basis="primary_evidence",
            ),
        )
        return predecessor, successor

    def command(
        predecessor: MemoryFactSnapshot,
        successor: MemoryFactSnapshot,
        *,
        idempotency_key: str,
    ) -> SupersedeFactCommand:
        return SupersedeFactCommand(
            successor_identity=successor.identity,
            predecessor_identity=predecessor.identity,
            expected_successor_version=1,
            expected_predecessor_version=1,
            effective_at=NOW,
            evidence_refs=(
                MemoryFactEvidenceRef(
                    evidence_id="evidence-1",
                    source_ref=_source_ref("adr-3"),
                ),
            ),
            actor_id="reviewer-1",
            reason_code="accepted_replacement",
            idempotency_key=idempotency_key,
        )

    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'supersession.db'}")
        try:
            await create_schema(engine)
            session_factory = build_session_factory(engine)
            factory = module.create_postgres_memory_fact_unit_of_work_factory(
                session_factory=session_factory,
                clock=FakeClock(NOW),
            )
            first_old, first_new = pair("first")
            failed_old, failed_new = pair("failed")
            async with factory() as uow:
                for fact in (first_old, first_new, failed_old, failed_new):
                    await uow.facts.create(fact)
                await uow.commit()

            successful = SupersedeFactHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=FakeIds(
                    outbox_message_ids=("outbox-new", "outbox-old"),
                    temporal_decision_ids=("decision-1",),
                    fact_relation_ids=("relation-1",),
                ),
            )
            result = await successful.execute(
                command(first_old, first_new, idempotency_key="supersede-first")
            )
            replay = await successful.execute(
                command(first_old, first_new, idempotency_key="supersede-first")
            )

            assert result.predecessor.visibility.status == "superseded"
            assert replay.replayed

            failing = SupersedeFactHandler(
                uow_factory=factory,
                clock=FakeClock(NOW),
                ids=FakeIds(
                    outbox_message_ids=("outbox-new", "outbox-old"),
                    temporal_decision_ids=("decision-rollback",),
                    fact_relation_ids=("relation-rollback",),
                ),
            )
            with pytest.raises(IntegrityError, match="memory_outbox.message_key"):
                await failing.execute(
                    command(failed_old, failed_new, idempotency_key="supersede-failed")
                )

            async with factory() as uow:
                rolled_back_old = await uow.facts.get(failed_old.identity)
                rolled_back_new = await uow.facts.get(failed_new.identity)
            assert rolled_back_old == failed_old
            assert rolled_back_new == failed_new

            async with session_factory() as session:
                decision_count = await session.scalar(
                    select(func.count()).select_from(MemoryFactTemporalDecisionRow)
                )
                relation_count = await session.scalar(
                    select(func.count()).select_from(MemoryFactRelationRow)
                )
                outbox_count = await session.scalar(
                    select(func.count()).select_from(MemoryOutboxRow)
                )
            assert decision_count == 1
            assert relation_count == 1
            assert outbox_count == 2
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_fact_projection_seams_report_disabled_health() -> None:
    qdrant = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.qdrant_fact_projection"
    ).QdrantMemoryFactProjection()
    graphiti = importlib.import_module(
        "infinity_context_adapters.features.memory_facts.graphiti_fact_projection"
    ).GraphitiMemoryFactProjection()

    qdrant_health = asyncio.run(qdrant.health())
    graphiti_health = asyncio.run(graphiti.health())

    assert qdrant_health.status is CapabilityStatus.DISABLED
    assert graphiti_health.status is CapabilityStatus.DISABLED
    assert all(
        descriptor.metadata["feature_id"] == FEATURE_ID for descriptor in qdrant_health.capabilities
    )
    assert all(
        descriptor.metadata["feature_id"] == FEATURE_ID
        for descriptor in graphiti_health.capabilities
    )
