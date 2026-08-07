"""Canonical SQLAlchemy adapter for the feature-owned memory_facts lifecycle."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import ClassVar

from infinity_context_core.features.memory_facts.public import (
    FEATURE_ID,
    FactEligibilityPolicy,
    FactTemporalExtent,
    MemoryFactClockPort,
    MemoryFactIdempotencyConflict,
    MemoryFactIdentity,
    MemoryFactOperationReceipt,
    MemoryFactOutboxMessage,
    MemoryFactRepositoryPort,
    MemoryFactScope,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactUnitOfWorkFactoryPort,
)
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
    memory_fact_row_to_snapshot,
    memory_fact_snapshot_from_json,
    memory_fact_snapshot_row_values,
    memory_fact_snapshot_to_json,
    memory_fact_snapshot_to_row,
    memory_fact_source_ref_row_to_domain,
    memory_fact_source_ref_to_row,
)
from infinity_context_adapters.features.memory_facts.postgres_temporal_decision_store import (
    PostgresFactSupersessionRepository,
    PostgresFactTemporalDecisionRepository,
)
from infinity_context_adapters.postgres.fact_selection_conditions import (
    memory_fact_selection_conditions,
)
from infinity_context_adapters.postgres.feature_models import (
    MemoryFactOperationReceiptRow,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryOutboxRow,
    MemorySourceRefRow,
)


class PostgresMemoryFactStore:
    """MemoryFactRepositoryPort backed by canonical Postgres tables."""

    adapter_name: ClassVar[str] = "postgres"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        self._session.add(memory_fact_snapshot_to_row(fact))
        await self._write_version(fact)
        await self._write_source_refs(fact)
        return fact

    async def get(self, identity: MemoryFactIdentity) -> MemoryFactSnapshot | None:
        row = (
            await self._session.execute(
                select(MemoryFactRow).where(*_identity_conditions(identity))
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        refs = await self._load_source_refs(row.id, row.version)
        return memory_fact_row_to_snapshot(row, refs)

    async def get_for_update(
        self,
        identity: MemoryFactIdentity,
    ) -> MemoryFactSnapshot | None:
        row = (
            await self._session.execute(
                select(MemoryFactRow).where(*_identity_conditions(identity)).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        refs = await self._load_source_refs(row.id, row.version)
        return memory_fact_row_to_snapshot(row, refs)

    async def get_many_for_update(
        self,
        identities: tuple[MemoryFactIdentity, ...],
    ) -> tuple[MemoryFactSnapshot, ...]:
        locked: list[MemoryFactSnapshot] = []
        for identity in identities:
            fact = await self.get_for_update(identity)
            if fact is not None:
                locked.append(fact)
        return tuple(locked)

    async def save(self, fact: MemoryFactSnapshot) -> MemoryFactSnapshot:
        expected_version = fact.visibility.version - 1
        if expected_version < 1:
            raise ValueError("Memory fact version conflict")
        await self._materialize_prior_version(fact.identity, expected_version)
        values = memory_fact_snapshot_row_values(fact)
        result = await self._session.execute(
            update(MemoryFactRow)
            .where(
                *_identity_conditions(fact.identity),
                MemoryFactRow.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount == 0:
            existing = (
                await self._session.execute(
                    select(MemoryFactRow.id, MemoryFactRow.version).where(
                        *_identity_conditions(fact.identity)
                    )
                )
            ).one_or_none()
            if existing is None:
                raise KeyError("memory_fact_not_found")
            raise ValueError(
                "Memory fact version conflict: "
                f"expected {expected_version}, actual {existing.version}"
            )
        await self._write_version(fact)
        await self._write_source_refs(fact)
        return fact

    async def _materialize_prior_version(
        self,
        identity: MemoryFactIdentity,
        expected_version: int,
    ) -> None:
        """Freeze legacy partial history before any canonical mutation changes current state."""

        row = (
            await self._session.execute(
                select(MemoryFactRow).where(*_identity_conditions(identity)).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise KeyError("memory_fact_not_found")
        if row.version != expected_version:
            raise ValueError(
                f"Memory fact version conflict: expected {expected_version}, actual {row.version}"
            )
        version_row = (
            await self._session.execute(
                select(MemoryFactVersionRow).where(
                    MemoryFactVersionRow.fact_id == identity.fact_id,
                    MemoryFactVersionRow.version == expected_version,
                )
            )
        ).scalar_one_or_none()
        refs = await self._load_source_refs(identity.fact_id, expected_version)
        snapshot = memory_fact_row_to_snapshot(row, refs)
        payload = memory_fact_snapshot_to_json(snapshot)
        if version_row is None:
            self._session.add(
                MemoryFactVersionRow(
                    fact_id=identity.fact_id,
                    version=expected_version,
                    text=snapshot.text,
                    status=snapshot.visibility.status,
                    source_refs_json=payload["source_refs"],
                    snapshot_json=payload,
                    reason="canonical_history_materialization",
                    created_at=_required_datetime("updated_at", snapshot.updated_at),
                )
            )
        elif not version_row.snapshot_json:
            version_row.snapshot_json = payload

    async def list_versions(
        self,
        identity: MemoryFactIdentity,
    ) -> tuple[MemoryFactSnapshot, ...]:
        current_row = (
            await self._session.execute(
                select(MemoryFactRow).where(*_identity_conditions(identity))
            )
        ).scalar_one_or_none()
        if current_row is None:
            return ()
        rows = tuple(
            (
                await self._session.execute(
                    select(MemoryFactVersionRow)
                    .where(MemoryFactVersionRow.fact_id == identity.fact_id)
                    .order_by(MemoryFactVersionRow.version)
                )
            ).scalars()
        )
        current_refs = await self._load_source_refs(current_row.id, current_row.version)
        current = memory_fact_row_to_snapshot(current_row, current_refs)
        return tuple(_version_snapshot(row, current) for row in rows)

    async def find_eligible(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[MemoryFactSnapshot, ...]:
        rows = tuple(
            (
                await self._session.execute(
                    select(MemoryFactRow)
                    .where(*_selection_conditions(query))
                    .order_by(MemoryFactRow.id)
                    .limit(query.limit)
                )
            ).scalars()
        )
        if not rows:
            return ()
        ref_rows = tuple(
            (
                await self._session.execute(
                    select(MemorySourceRefRow)
                    .where(MemorySourceRefRow.fact_id.in_(tuple(row.id for row in rows)))
                    .order_by(
                        MemorySourceRefRow.fact_id,
                        MemorySourceRefRow.fact_version,
                        MemorySourceRefRow.id,
                    )
                )
            ).scalars()
        )
        refs_by_version: dict[tuple[str, int], list[MemorySourceRefRow]] = {}
        for ref in ref_rows:
            refs_by_version.setdefault((ref.fact_id, ref.fact_version), []).append(ref)
        policy = FactEligibilityPolicy()
        snapshots = tuple(
            memory_fact_row_to_snapshot(
                row,
                refs_by_version.get((row.id, row.version), []),
            )
            for row in rows
        )
        return tuple(
            fact
            for fact in snapshots
            if policy.assess(
                fact,
                mode=query.temporal_mode,
                reference_time=query.reference_time,
            ).eligible
        )

    async def _write_version(self, fact: MemoryFactSnapshot) -> None:
        payload = memory_fact_snapshot_to_json(fact)
        existing = (
            await self._session.execute(
                select(MemoryFactVersionRow).where(
                    MemoryFactVersionRow.fact_id == fact.identity.fact_id,
                    MemoryFactVersionRow.version == fact.visibility.version,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.snapshot_json == payload:
                return
            raise ValueError("Canonical fact version is append-only")
        self._session.add(
            MemoryFactVersionRow(
                fact_id=fact.identity.fact_id,
                version=fact.visibility.version,
                text=fact.text,
                status=fact.visibility.status,
                source_refs_json=payload["source_refs"],
                snapshot_json=payload,
                reason=None,
                created_at=_required_datetime("updated_at", fact.updated_at),
            )
        )

    async def _write_source_refs(self, fact: MemoryFactSnapshot) -> None:
        existing = tuple(
            (
                await self._session.execute(
                    select(MemorySourceRefRow)
                    .where(
                        MemorySourceRefRow.fact_id == fact.identity.fact_id,
                        MemorySourceRefRow.fact_version == fact.visibility.version,
                    )
                    .order_by(MemorySourceRefRow.id)
                )
            ).scalars()
        )
        if existing:
            persisted = tuple(memory_fact_source_ref_row_to_domain(row) for row in existing)
            if persisted == fact.source_refs:
                return
            raise ValueError("Canonical source refs are append-only per fact version")
        for ref in fact.source_refs:
            self._session.add(
                memory_fact_source_ref_to_row(
                    fact.identity.fact_id,
                    fact.visibility.version,
                    ref,
                )
            )

    async def _load_source_refs(
        self,
        fact_id: str,
        fact_version: int,
    ) -> list[MemorySourceRefRow]:
        return list(
            (
                await self._session.execute(
                    select(MemorySourceRefRow)
                    .where(
                        MemorySourceRefRow.fact_id == fact_id,
                        MemorySourceRefRow.fact_version == fact_version,
                    )
                    .order_by(MemorySourceRefRow.id)
                )
            ).scalars()
        )


class PostgresMemoryFactOutbox:
    """Provider-neutral outbox writer sharing the canonical transaction."""

    adapter_name: ClassVar[str] = "postgres"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self._session = session
        self._now = now

    async def enqueue(self, message: MemoryFactOutboxMessage) -> None:
        self._session.add(
            MemoryOutboxRow(
                message_key=message.message_id,
                event_type=message.event_type,
                aggregate_type="fact",
                aggregate_id=message.aggregate_id,
                aggregate_version=message.aggregate_version,
                workload_class="projection",
                fairness_key=f"fact:{message.aggregate_id}",
                payload_json={
                    "message_id": message.message_id,
                    "fact_id": message.aggregate_id,
                    "version": message.aggregate_version,
                    "space_id": message.scope.space_id,
                    "memory_scope_id": message.scope.memory_scope_id,
                    "thread_id": message.scope.thread_id,
                    "occurred_at": (
                        message.occurred_at.isoformat() if message.occurred_at is not None else None
                    ),
                },
                status="pending",
                attempt_count=0,
                next_attempt_at=self._now,
                created_at=message.occurred_at or self._now,
                updated_at=self._now,
            )
        )


class PostgresMemoryFactOperationReceiptRepository:
    """Immutable exact-result receipts for retried lifecycle commands."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        receipt: MemoryFactOperationReceipt,
    ) -> MemoryFactOperationReceipt:
        existing = await self.get(
            space_id=receipt.space_id,
            memory_scope_id=receipt.memory_scope_id,
            thread_id=receipt.thread_id,
            operation=receipt.operation,
            idempotency_key=receipt.idempotency_key,
        )
        if existing is not None:
            if existing == receipt:
                return existing
            raise MemoryFactIdempotencyConflict(
                "A concurrent fact operation already committed this idempotency key"
            )
        self._session.add(
            MemoryFactOperationReceiptRow(
                id=_operation_receipt_id(receipt),
                space_id=receipt.space_id,
                memory_scope_id=receipt.memory_scope_id,
                thread_id=receipt.thread_id,
                thread_scope_key=_thread_scope_key(receipt.thread_id),
                idempotency_key=receipt.idempotency_key,
                operation=receipt.operation,
                request_fingerprint=receipt.request_fingerprint,
                result_fact_id=receipt.result_fact.identity.fact_id,
                result_fact_version=receipt.result_fact.visibility.version,
                result_snapshot_json=memory_fact_snapshot_to_json(receipt.result_fact),
                outbox_message_ids_json=list(receipt.outbox_message_ids),
                tombstone_id=receipt.tombstone_id,
                created_at=receipt.created_at,
            )
        )
        return receipt

    async def get(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> MemoryFactOperationReceipt | None:
        thread_condition = (
            MemoryFactOperationReceiptRow.thread_id.is_(None)
            if thread_id is None
            else MemoryFactOperationReceiptRow.thread_id == thread_id
        )
        row = (
            await self._session.execute(
                select(MemoryFactOperationReceiptRow).where(
                    MemoryFactOperationReceiptRow.space_id == space_id,
                    MemoryFactOperationReceiptRow.memory_scope_id == memory_scope_id,
                    MemoryFactOperationReceiptRow.thread_scope_key == _thread_scope_key(thread_id),
                    thread_condition,
                    MemoryFactOperationReceiptRow.operation == operation,
                    MemoryFactOperationReceiptRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        result_fact = memory_fact_snapshot_from_json(row.result_snapshot_json)
        result_scope = result_fact.identity.scope
        if (
            result_fact.identity.fact_id != row.result_fact_id
            or result_fact.visibility.version != row.result_fact_version
            or result_scope.space_id != row.space_id
            or result_scope.memory_scope_id != row.memory_scope_id
            or result_scope.thread_id != row.thread_id
        ):
            raise ValueError("Fact operation receipt snapshot identity mismatch")
        return MemoryFactOperationReceipt(
            space_id=row.space_id,
            memory_scope_id=row.memory_scope_id,
            thread_id=row.thread_id,
            idempotency_key=row.idempotency_key,
            operation=row.operation,
            request_fingerprint=row.request_fingerprint,
            result_fact=result_fact,
            outbox_message_ids=tuple(row.outbox_message_ids_json),
            tombstone_id=row.tombstone_id,
            created_at=_aware(row.created_at),
        )


class PostgresMemoryFactTransaction:
    """Canonical fact repositories bound to an already-owned Postgres session."""

    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self._session = session
        self.facts = PostgresMemoryFactStore(session)
        self.temporal_decisions = PostgresFactTemporalDecisionRepository(session)
        self.supersessions = PostgresFactSupersessionRepository(session)
        self.operation_receipts = PostgresMemoryFactOperationReceiptRepository(session)
        self.outbox = PostgresMemoryFactOutbox(session, now=now)

    async def lock_scope(self, scope: MemoryFactScope) -> None:
        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_identity = (
            f"memory-facts:{scope.space_id}:{scope.memory_scope_id}:{scope.thread_id or ''}"
        )
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": lock_identity},
        )


class PostgresMemoryFactUnitOfWork:
    """One transaction for fact snapshots, version history and outbox intents."""

    adapter_name: ClassVar[str] = "postgres"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: MemoryFactClockPort,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> PostgresMemoryFactUnitOfWork:
        self._session = self._session_factory()
        now = self._clock.now()
        self._transaction = PostgresMemoryFactTransaction(self._session, now=now)
        self.facts = self._transaction.facts
        self.temporal_decisions = self._transaction.temporal_decisions
        self.supersessions = self._transaction.supersessions
        self.operation_receipts = self._transaction.operation_receipts
        self.outbox = self._transaction.outbox
        return self

    async def lock_scope(self, scope: MemoryFactScope) -> None:
        if self._session is None:
            raise RuntimeError("Memory fact unit of work is not open")
        await self._transaction.lock_scope(scope)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc_type is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()
        self._session = None
        self._committed = False

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Memory fact unit of work is not open")
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _is_idempotency_integrity_error(exc):
                raise MemoryFactIdempotencyConflict(
                    "Canonical memory fact idempotency write conflicted"
                ) from exc
            raise
        self._committed = True

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()
        self._committed = False


class PostgresMemoryFactUnitOfWorkFactory:
    """Create feature-owned Postgres units of work without exposing sessions to core."""

    adapter_name: ClassVar[str] = "postgres"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: MemoryFactClockPort,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    def __call__(self) -> PostgresMemoryFactUnitOfWork:
        return PostgresMemoryFactUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
        )


def create_postgres_memory_fact_store(
    session: AsyncSession,
) -> MemoryFactRepositoryPort:
    return PostgresMemoryFactStore(session)


def create_postgres_memory_fact_unit_of_work_factory(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    clock: MemoryFactClockPort,
) -> MemoryFactUnitOfWorkFactoryPort:
    return PostgresMemoryFactUnitOfWorkFactory(
        session_factory=session_factory,
        clock=clock,
    )


def _identity_conditions(identity: MemoryFactIdentity) -> tuple[object, ...]:
    scope = identity.scope
    thread_condition = (
        MemoryFactRow.thread_id.is_(None)
        if scope.thread_id is None
        else MemoryFactRow.thread_id == scope.thread_id
    )
    return (
        MemoryFactRow.id == identity.fact_id,
        MemoryFactRow.space_id == scope.space_id,
        MemoryFactRow.memory_scope_id == scope.memory_scope_id,
        thread_condition,
    )


def _operation_receipt_id(receipt: MemoryFactOperationReceipt) -> str:
    identity = "\0".join(
        (
            receipt.space_id,
            receipt.memory_scope_id,
            _thread_scope_key(receipt.thread_id),
            receipt.operation,
            receipt.idempotency_key,
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _thread_scope_key(thread_id: str | None) -> str:
    return f"thread:{thread_id}" if thread_id is not None else "global"


def _is_idempotency_integrity_error(exc: IntegrityError) -> bool:
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if constraint_name in {
        "uq_memory_fact_operation_receipt_idempotency",
        "uq_memory_fact_temporal_decision_idempotency",
    }:
        return True
    message = str(original or exc).casefold()
    return ("memory_fact_operation_receipts" in message and "idempotency_key" in message) or (
        "memory_fact_temporal_decisions" in message and "idempotency_key" in message
    )


def _selection_conditions(query: MemoryFactSelectionQuery) -> tuple[object, ...]:
    return memory_fact_selection_conditions(
        space_id=query.space_id,
        memory_scope_ids=query.memory_scope_ids,
        thread_id=query.thread_id,
        repository_id=query.repository_id,
        code_scope_id=query.code_scope_id,
        temporal_mode=query.temporal_mode.value,
        reference_time=query.reference_time,
        fact_ids=query.fact_ids,
    )


def _version_snapshot(
    row: MemoryFactVersionRow,
    current: MemoryFactSnapshot,
) -> MemoryFactSnapshot:
    payload = row.snapshot_json or {}
    if payload:
        return memory_fact_snapshot_from_json(payload)
    observed_at = _aware(current.created_at or row.created_at)
    return replace(
        current,
        text=row.text,
        source_refs=tuple(_legacy_source_ref(item) for item in row.source_refs_json),
        visibility=replace(
            current.visibility,
            status=row.status,
            version=row.version,
        ),
        updated_at=_aware(row.created_at),
        temporal_extent=FactTemporalExtent(
            kind="state",
            observed_at=observed_at,
            valid_from=observed_at,
            basis="migrated_legacy",
            precision="unknown",
        ),
    )


def _legacy_source_ref(payload: dict[str, object]) -> MemoryFactSourceRef:
    bbox = payload.get("bbox")
    return MemoryFactSourceRef(
        source_type=str(payload["source_type"]),
        source_id=str(payload["source_id"]),
        chunk_id=str(payload["chunk_id"]) if payload.get("chunk_id") is not None else None,
        char_start=int(payload["char_start"]) if payload.get("char_start") is not None else None,
        char_end=int(payload["char_end"]) if payload.get("char_end") is not None else None,
        quote_preview=(
            str(payload["quote_preview"]) if payload.get("quote_preview") is not None else None
        ),
        page_number=int(payload["page_number"]) if payload.get("page_number") is not None else None,
        time_start_ms=int(payload["time_start_ms"])
        if payload.get("time_start_ms") is not None
        else None,
        time_end_ms=int(payload["time_end_ms"]) if payload.get("time_end_ms") is not None else None,
        bbox=tuple(float(value) for value in bbox) if isinstance(bbox, list | tuple) else None,
    )


def _required_datetime(field_name: str, value: datetime | None) -> datetime:
    if value is None:
        raise ValueError(f"Memory fact snapshot requires {field_name}")
    return _aware(value)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


__all__ = (
    "PostgresMemoryFactOutbox",
    "PostgresMemoryFactStore",
    "PostgresMemoryFactTransaction",
    "PostgresMemoryFactUnitOfWork",
    "PostgresMemoryFactUnitOfWorkFactory",
    "create_postgres_memory_fact_store",
    "create_postgres_memory_fact_unit_of_work_factory",
)
