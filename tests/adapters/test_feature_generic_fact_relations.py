"""Generic relation parity and transaction behavior through the feature public API."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from infinity_context_adapters.features.memory_facts.in_memory_fact_store import (
    InMemoryMemoryFactUnitOfWorkFactory,
)
from infinity_context_core.domain.entities import (
    FactRelationType as LegacyType,
)
from infinity_context_core.domain.entities import (
    MemoryFactRelation as LegacyRelation,
)
from infinity_context_core.features.memory_facts.public import (
    FactCodeScopeReference,
    FactRelationConflict,
    FactRelationSnapshot,
    FactRelationStatus,
    FactRelationType,
    FactSupersessionRelation,
    LinkFactsCommand,
    LinkFactsHandler,
    ListFactRelationsHandler,
    ListFactRelationsQuery,
    MemoryFactScope,
    UnlinkFactRelationCommand,
    UnlinkFactRelationHandler,
    link_facts_in_transaction,
)
from memory_fact_test_support import EARLIER, LATER, NOW, FakeClock, FakeIds, _fact_snapshot

SOURCE = _fact_snapshot(fact_id="source")
TARGET = _fact_snapshot(fact_id="target")
COMMAND = LinkFactsCommand(SOURCE.identity, TARGET.identity, "supports", " evidence ")


def _handler(factory, *ids):
    return LinkFactsHandler(factory, FakeClock(NOW), FakeIds(fact_relation_ids=ids))


def _relation(**changes):
    value = FactRelationSnapshot.create(
        relation_id="relation",
        source=SOURCE,
        target=TARGET,
        relation_type=FactRelationType.SUPPORTS,
        reason=" evidence ",
        now=NOW,
    )
    return replace(value, **changes)


@pytest.mark.parametrize("kind", list(FactRelationType))
def test_allowed_enum_and_creation_match_legacy_domain(kind):
    assert {item.value for item in FactRelationType} == {item.value for item in LegacyType}
    if kind in {FactRelationType.SUPERSEDES, FactRelationType.CONTRADICTS}:
        with pytest.raises(ValueError, match="audited"):
            FactRelationSnapshot.create(
                relation_id="relation",
                source=SOURCE,
                target=TARGET,
                relation_type=kind,
                reason=" evidence ",
                now=NOW,
            )
        return
    feature = FactRelationSnapshot.create(
        relation_id="relation",
        source=SOURCE,
        target=TARGET,
        relation_type=kind,
        reason=" evidence ",
        now=NOW,
        observed_at=EARLIER,
        valid_from=EARLIER,
        valid_to=LATER,
    )
    legacy = LegacyRelation.create(
        relation_id="relation",
        space_id="space-1",
        memory_scope_id="scope-1",
        source_fact_id="source",
        target_fact_id="target",
        relation_type=LegacyType(kind),
        reason=" evidence ",
        now=NOW,
        observed_at=EARLIER,
        valid_from=EARLIER,
        valid_to=LATER,
    )
    for name in (
        "space_id",
        "memory_scope_id",
        "source_fact_id",
        "target_fact_id",
        "relation_type",
        "reason",
        "status",
        "observed_at",
        "valid_from",
        "valid_to",
        "created_at",
        "updated_at",
    ):
        assert getattr(feature, name) == getattr(legacy, name)
    assert feature.delete(now=LATER).updated_at == legacy.delete(now=LATER).updated_at
    deleted = feature.delete(now=LATER)
    assert deleted.delete(now=LATER + timedelta(days=1)) is deleted


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"relation_type": "wrong"}, "Unknown"),
        ({"relation_type": "supersedes"}, "audited"),
        ({"relation_type": "contradicts"}, "audited"),
        ({"target_identity": SOURCE.identity}, "distinct"),
        ({"reason": "  "}, "reason"),
        ({"valid_from": NOW, "valid_to": NOW}, "after"),
        ({"valid_from": LATER, "valid_to": NOW}, "after"),
    ],
)
def test_invalid_link_rolls_back(changes, match):
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        with pytest.raises(ValueError, match=match):
            await _handler(factory, "relation").execute(replace(COMMAND, **changes))
        result = await ListFactRelationsHandler(factory).execute(
            ListFactRelationsQuery(SOURCE.identity)
        )
        assert result.items == ()
        assert factory.facts == (SOURCE, TARGET)
        assert factory.outbox_messages == ()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change,match",
    [
        ({"status": "deleted"}, "Deleted"),
        ({"classification": "restricted"}, "Restricted"),
    ],
)
@pytest.mark.parametrize("endpoint", ["source", "target"])
def test_ineligible_endpoint_rejected_even_on_replay(change, match, endpoint):
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        handler = _handler(factory, "relation")
        await handler.execute(COMMAND)
        fact = SOURCE if endpoint == "source" else TARGET
        async with factory() as uow:
            await uow.facts.save(
                replace(fact, visibility=replace(fact.visibility, version=2, **change))
            )
            await uow.commit()
        with pytest.raises(FactRelationConflict, match=match):
            await handler.execute(COMMAND)

    asyncio.run(run())


@pytest.mark.parametrize(
    "scope", [MemoryFactScope("other", "scope-1"), MemoryFactScope("space-1", "other")]
)
def test_cross_scope_rejected(scope):
    async def run():
        other = replace(TARGET, identity=replace(TARGET.identity, scope=scope))
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, other))
        with pytest.raises(FactRelationConflict, match="boundaries"):
            await _handler(factory, "relation").execute(
                replace(COMMAND, target_identity=other.identity)
            )

    asyncio.run(run())


def test_replay_temporal_conflict_unlink_and_relink_leave_facts_untouched():
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        handler = _handler(factory, "first", "second")
        command = replace(COMMAND, observed_at=EARLIER, valid_from=NOW, valid_to=LATER)
        first = await handler.execute(command)
        assert first.relation.reason == "evidence"
        assert await handler.execute(replace(COMMAND, reason="")) == first
        assert (
            await handler.execute(replace(command, observed_at=EARLIER.replace(tzinfo=None)))
            == first
        )
        for field in ("observed_at", "valid_from", "valid_to"):
            with pytest.raises(FactRelationConflict, match=field):
                await handler.execute(replace(command, **{field: LATER + timedelta(days=1)}))
        unlink = UnlinkFactRelationHandler(factory, FakeClock(LATER))
        deleted = await unlink.execute(UnlinkFactRelationCommand("first", SOURCE.identity.scope))
        assert deleted.relation.status == FactRelationStatus.DELETED
        assert (
            await unlink.execute(UnlinkFactRelationCommand("first", SOURCE.identity.scope))
            == deleted
        )
        second = await handler.execute(COMMAND)
        assert second.relation.relation_id == "second"
        for fact in (SOURCE, TARGET):
            async with factory() as uow:
                assert await uow.facts.list_versions(fact.identity) == (fact,)
        assert factory.facts == (SOURCE, TARGET)
        assert factory.outbox_messages == ()
        assert factory.temporal_decisions == ()

    asyncio.run(run())


def test_shared_transaction_does_not_commit_and_conflicting_snapshots_cannot_duplicate():
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        async with factory() as uow:
            await link_facts_in_transaction(
                uow, COMMAND, now=NOW, ids=FakeIds(fact_relation_ids=("rollback",))
            )
        query = ListFactRelationsQuery(SOURCE.identity)
        assert (await ListFactRelationsHandler(factory).execute(query)).items == ()
        async with factory() as first, factory() as second:
            for transaction, relation_id in ((first, "first"), (second, "second")):
                await link_facts_in_transaction(
                    transaction, COMMAND, now=NOW, ids=FakeIds(fact_relation_ids=(relation_id,))
                )
            await first.commit()
            with pytest.raises(ValueError, match="transaction conflict"):
                await second.commit()
        assert len((await ListFactRelationsHandler(factory).execute(query)).items) == 1

    asyncio.run(run())


@pytest.mark.parametrize("limit", [0, 101])
def test_limit_validation(limit):
    with pytest.raises(ValueError, match="between 1 and 100"):
        asyncio.run(
            ListFactRelationsHandler(InMemoryMemoryFactUnitOfWorkFactory()).execute(
                ListFactRelationsQuery(SOURCE.identity, limit=limit)
            )
        )


def test_missing_and_wrong_scope_do_not_expose_relations():
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        await _handler(factory, "relation").execute(COMMAND)
        with pytest.raises(LookupError):
            await UnlinkFactRelationHandler(factory, FakeClock(NOW)).execute(
                UnlinkFactRelationCommand("relation", MemoryFactScope("other", "scope-1"))
            )
        missing = replace(SOURCE.identity, fact_id="missing")
        with pytest.raises(LookupError):
            await _handler(factory).execute(replace(COMMAND, source_identity=missing))
        with pytest.raises(LookupError):
            await ListFactRelationsHandler(factory).execute(ListFactRelationsQuery(missing))

    asyncio.run(run())


def test_order_direction_status_code_scope_and_post_limit_eligibility():
    async def run():
        # Restricted/deleted filtering intentionally follows the legacy row-limit
        # boundary except restricted facts excluded by the code-scope SQL join.
        restricted = replace(
            _fact_snapshot(fact_id="restricted"),
            visibility=replace(SOURCE.visibility, classification="restricted"),
        )
        deleted = replace(
            _fact_snapshot(fact_id="deleted"),
            visibility=replace(SOURCE.visibility, status="deleted"),
        )
        project = replace(
            _fact_snapshot(fact_id="project"), code_scope=FactCodeScopeReference("repo", "branch")
        )
        unknown = replace(
            _fact_snapshot(fact_id="unknown"),
            visibility=replace(SOURCE.visibility, classification="unknown", status="disputed"),
        )
        factory = InMemoryMemoryFactUnitOfWorkFactory(
            (SOURCE, TARGET, restricted, deleted, project, unknown)
        )
        async with factory() as uow:
            for relation in (
                _relation(relation_id="a"),
                _relation(relation_id="b", source_fact_id="target", target_fact_id="source"),
                _relation(relation_id="c", target_fact_id="project"),
                _relation(relation_id="d", target_fact_id="deleted"),
                _relation(relation_id="e", target_fact_id="restricted"),
                _relation(relation_id="f", target_fact_id="unknown"),
                _relation(
                    relation_id="g", target_fact_id="target", status=FactRelationStatus.DELETED
                ),
            ):
                # Seeding existing rows includes facts that became ineligible later.
                uow.relations._relations[relation.relation_id] = relation
            await uow.commit()
        handler = ListFactRelationsHandler(factory)
        result = await handler.execute(ListFactRelationsQuery(SOURCE.identity))
        assert [item.relation.relation_id for item in result.items] == ["f", "c", "b", "a"]
        assert [item.direction for item in result.items] == [
            "outgoing",
            "outgoing",
            "incoming",
            "outgoing",
        ]
        assert result.items[-1].related_fact.source_refs == TARGET.source_refs
        assert (await handler.execute(ListFactRelationsQuery(SOURCE.identity, limit=2))).items[
            0
        ].relation.relation_id == "f"
        assert (
            len((await handler.execute(ListFactRelationsQuery(SOURCE.identity, limit=2))).items)
            == 1
        )
        for repo, branch, expected in [
            (None, None, ["f", "b", "a"]),
            ("repo", None, ["f", "b", "a"]),
            ("repo", "branch", ["f", "c", "b", "a"]),
            ("other", "branch", ["f", "b", "a"]),
        ]:
            selected = await handler.execute(
                ListFactRelationsQuery(
                    SOURCE.identity,
                    enforce_code_scope=True,
                    repository_id=repo,
                    code_scope_id=branch,
                )
            )
            assert [item.relation.relation_id for item in selected.items] == expected
        deleted_result = await handler.execute(
            ListFactRelationsQuery(SOURCE.identity, status="deleted")
        )
        assert [item.relation.relation_id for item in deleted_result.items] == ["g"]
        assert (
            len((await handler.execute(ListFactRelationsQuery(SOURCE.identity, status=None))).items)
            == 5
        )
        assert (
            await handler.execute(ListFactRelationsQuery(SOURCE.identity, status="unknown"))
        ).items == ()

    asyncio.run(run())


def test_temporal_owned_rows_visible_but_supersession_unlink_is_immutable():
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        async with factory() as uow:
            await uow.supersessions.create(
                FactSupersessionRelation(
                    "supersession",
                    SOURCE.identity.scope,
                    "source",
                    2,
                    "target",
                    2,
                    NOW,
                    "decision",
                    NOW,
                )
            )
            await uow.relations.create(
                _relation(relation_id="contradiction", relation_type=FactRelationType.CONTRADICTS)
            )
            await uow.commit()
        items = (
            await ListFactRelationsHandler(factory).execute(ListFactRelationsQuery(SOURCE.identity))
        ).items
        assert {item.relation.relation_type for item in items} == {
            FactRelationType.SUPERSEDES,
            FactRelationType.CONTRADICTS,
        }
        unlink = UnlinkFactRelationHandler(factory, FakeClock(LATER))
        with pytest.raises(ValueError, match="immutable"):
            await unlink.execute(UnlinkFactRelationCommand("supersession", SOURCE.identity.scope))
        await unlink.execute(UnlinkFactRelationCommand("contradiction", SOURCE.identity.scope))
        assert factory.facts == (SOURCE, TARGET)

    asyncio.run(run())


def test_link_locks_scope_then_unique_facts_in_stable_identity_order():
    async def run():
        factory = InMemoryMemoryFactUnitOfWorkFactory((SOURCE, TARGET))
        async with factory() as uow:
            calls = []
            get_many = uow.facts.get_many_for_update

            async def lock_scope(scope):
                calls.append(("scope", scope))

            async def get_many_for_update(identities):
                calls.append(("facts", identities))
                return await get_many(identities)

            uow.lock_scope = lock_scope
            uow.facts.get_many_for_update = get_many_for_update
            await link_facts_in_transaction(
                uow,
                replace(COMMAND, source_identity=TARGET.identity, target_identity=SOURCE.identity),
                now=NOW,
                ids=FakeIds(fact_relation_ids=("reverse",)),
            )
            assert calls == [
                ("scope", SOURCE.identity.scope),
                ("facts", (SOURCE.identity, TARGET.identity)),
            ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "source_thread,target_thread", [(None, "one"), ("one", None), ("one", "two")]
)
def test_thread_mismatch_rejected_before_replay(source_thread, target_thread):
    async def run():
        source = replace(
            SOURCE,
            identity=replace(
                SOURCE.identity, scope=replace(SOURCE.identity.scope, thread_id=source_thread)
            ),
        )
        target = replace(
            TARGET,
            identity=replace(
                TARGET.identity, scope=replace(TARGET.identity.scope, thread_id=target_thread)
            ),
        )
        factory = InMemoryMemoryFactUnitOfWorkFactory((source, target))
        # Simulate an old invalid row: endpoint validation must still precede replay.
        async with factory() as uow:
            uow.relations._relations["relation"] = _relation()
            await uow.commit()
        with pytest.raises(FactRelationConflict, match="cross thread boundaries"):
            await _handler(factory).execute(
                replace(COMMAND, source_identity=source.identity, target_identity=target.identity)
            )
        assert factory.facts == (source, target)
        assert factory.outbox_messages == ()
        assert factory.temporal_decisions == ()
        async with factory() as uow:
            assert await uow.relations.get("relation", scope=source.identity.scope) == _relation()

    asyncio.run(run())
