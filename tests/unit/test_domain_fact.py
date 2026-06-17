from datetime import UTC, datetime

import pytest
from memo_stack_core.domain.entities import (
    FactStatus,
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from memo_stack_core.domain.errors import MemoryConflictError, MemoryValidationError


def test_active_fact_requires_source_refs() -> None:
    with pytest.raises(MemoryValidationError):
        MemoryFact.create(
            fact_id=MemoryFactId("fact_1"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("memory_scope_1"),
            text="Postgres is canonical truth.",
            kind=MemoryKind.ARCHITECTURE_DECISION,
            source_refs=(),
            now=datetime(2026, 5, 25, tzinfo=UTC),
        )


def test_update_requires_expected_version() -> None:
    fact = MemoryFact.create(
        fact_id=MemoryFactId("fact_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        text="Postgres is canonical truth.",
        kind=MemoryKind.ARCHITECTURE_DECISION,
        source_refs=(SourceRef(source_type="manual", source_id="manual_1"),),
        now=datetime(2026, 5, 25, tzinfo=UTC),
    )

    with pytest.raises(MemoryConflictError):
        fact.update(
            expected_version=2,
            text="Postgres remains canonical truth.",
            source_refs=(SourceRef(source_type="manual", source_id="manual_2"),),
            reason="Correction",
            now=datetime(2026, 5, 25, tzinfo=UTC),
        )


def test_forget_is_idempotent() -> None:
    fact = MemoryFact.create(
        fact_id=MemoryFactId("fact_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        text="Postgres is canonical truth.",
        kind=MemoryKind.ARCHITECTURE_DECISION,
        source_refs=(SourceRef(source_type="manual", source_id="manual_1"),),
        now=datetime(2026, 5, 25, tzinfo=UTC),
    )

    forgotten = fact.forget(now=datetime(2026, 5, 25, tzinfo=UTC))
    forgotten_again = forgotten.forget(now=datetime(2026, 5, 25, tzinfo=UTC))

    assert forgotten_again == forgotten
    assert forgotten.version == 2


def test_mark_disputed_excludes_fact_from_active_currency() -> None:
    fact = MemoryFact.create(
        fact_id=MemoryFactId("fact_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("memory_scope_1"),
        text="Postgres is canonical truth.",
        kind=MemoryKind.ARCHITECTURE_DECISION,
        source_refs=(SourceRef(source_type="manual", source_id="manual_1"),),
        now=datetime(2026, 5, 25, tzinfo=UTC),
    )

    disputed = fact.mark_disputed(now=datetime(2026, 5, 26, tzinfo=UTC))
    disputed_again = disputed.mark_disputed(now=datetime(2026, 5, 27, tzinfo=UTC))

    assert disputed.status == FactStatus.DISPUTED
    assert disputed.version == 2
    assert disputed_again == disputed


def test_fact_rejects_unknown_classification_value() -> None:
    with pytest.raises(MemoryValidationError):
        MemoryFact.create(
            fact_id=MemoryFactId("fact_bad_classification"),
            space_id=SpaceId("space_1"),
            memory_scope_id=MemoryScopeId("memory_scope_1"),
            text="Invalid classification should be rejected.",
            kind=MemoryKind.NOTE,
            source_refs=(SourceRef(source_type="manual", source_id="manual_1"),),
            now=datetime(2026, 5, 25, tzinfo=UTC),
            classification="secret",
        )
