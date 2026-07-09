"""Concrete application handlers for the memory_facts lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from infinity_context_core.features.memory_facts.application.commands import (
    ForgetFactCommand,
    ForgetFactResult,
    RememberFactCommand,
    RememberFactResult,
    UpdateFactCommand,
    UpdateFactResult,
)
from infinity_context_core.features.memory_facts.domain import (
    MemoryFactIdentity,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)
from infinity_context_core.features.memory_facts.ports import (
    MemoryFactClockPort,
    MemoryFactIdPort,
    MemoryFactOutboxMessage,
    MemoryFactUnitOfWorkFactoryPort,
)

FACT_CREATED_EVENT: Final = "fact.created"
FACT_UPDATED_EVENT: Final = "fact.updated"
FACT_DELETED_EVENT: Final = "fact.deleted"


@dataclass(frozen=True, slots=True)
class RememberFactHandler:
    """Create one canonical fact through feature-owned ports."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: RememberFactCommand) -> RememberFactResult:
        _require_active_fact_content(command.text, command.source_refs)

        async with self.uow_factory() as uow:
            now = self.clock.now()
            fact = MemoryFactSnapshot(
                identity=MemoryFactIdentity(
                    fact_id=self.ids.new_fact_id(),
                    scope=command.scope,
                ),
                text=command.text,
                source_refs=command.source_refs,
                visibility=MemoryFactVisibility(status="active", version=1),
                kind=command.kind,
                evidence_refs=command.evidence_refs,
                category=command.category,
                tags=command.tags,
                created_at=now,
                updated_at=now,
            )

            saved = await uow.facts.create(fact)
            message = _outbox_message(
                ids=self.ids,
                fact=saved,
                event_type=FACT_CREATED_EVENT,
                occurred_at=now,
            )
            await uow.outbox.enqueue(message)
            await uow.commit()

        return RememberFactResult(
            fact=saved,
            outbox_message_ids=(message.message_id,),
        )


@dataclass(frozen=True, slots=True)
class UpdateFactHandler:
    """Replace one canonical fact version through feature-owned ports."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: UpdateFactCommand) -> UpdateFactResult:
        _require_active_fact_content(command.text, command.source_refs)

        async with self.uow_factory() as uow:
            current = await uow.facts.get_for_update(command.identity)
            if current is None:
                raise LookupError(f"Memory fact not found: {command.identity.fact_id}")
            if current.visibility.status == "deleted":
                raise ValueError(
                    f"Deleted memory fact cannot be updated: {command.identity.fact_id}"
                )
            _require_expected_version(
                current,
                expected_version=command.expected_version,
            )

            now = self.clock.now()
            updated = MemoryFactSnapshot(
                identity=current.identity,
                text=command.text,
                source_refs=command.source_refs,
                visibility=replace(
                    current.visibility,
                    status="active",
                    version=current.visibility.version + 1,
                ),
                kind=command.kind,
                evidence_refs=command.evidence_refs,
                category=command.category,
                tags=command.tags,
                created_at=current.created_at,
                updated_at=now,
            )

            saved = await uow.facts.save(updated)
            message = _outbox_message(
                ids=self.ids,
                fact=saved,
                event_type=FACT_UPDATED_EVENT,
                occurred_at=now,
            )
            await uow.outbox.enqueue(message)
            await uow.commit()

        return UpdateFactResult(
            fact=saved,
            outbox_message_ids=(message.message_id,),
        )


@dataclass(frozen=True, slots=True)
class ForgetFactHandler:
    """Tombstone one canonical fact through feature-owned ports."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: ForgetFactCommand) -> ForgetFactResult:
        async with self.uow_factory() as uow:
            current = await uow.facts.get_for_update(command.identity)
            if current is None:
                raise LookupError(f"Memory fact not found: {command.identity.fact_id}")
            if current.visibility.status == "deleted":
                raise ValueError(f"Memory fact is already deleted: {command.identity.fact_id}")
            if command.expected_version is not None:
                _require_expected_version(
                    current,
                    expected_version=command.expected_version,
                )

            now = self.clock.now()
            tombstone_id = self.ids.new_tombstone_id()
            forgotten = MemoryFactSnapshot(
                identity=current.identity,
                text=current.text,
                source_refs=current.source_refs,
                visibility=replace(
                    current.visibility,
                    status="deleted",
                    version=current.visibility.version + 1,
                ),
                kind=current.kind,
                evidence_refs=current.evidence_refs,
                category=current.category,
                tags=current.tags,
                created_at=current.created_at,
                updated_at=now,
            )

            saved = await uow.facts.save(forgotten)
            message = _outbox_message(
                ids=self.ids,
                fact=saved,
                event_type=FACT_DELETED_EVENT,
                occurred_at=now,
            )
            await uow.outbox.enqueue(message)
            await uow.commit()

        return ForgetFactResult(
            fact=saved,
            tombstone_id=tombstone_id,
            outbox_message_ids=(message.message_id,),
        )


def _require_active_fact_content(
    text: str,
    source_refs: tuple[MemoryFactSourceRef, ...],
) -> None:
    if not text.strip():
        raise ValueError("Memory fact text is required")
    if not source_refs:
        raise ValueError("Memory fact source_refs are required")


def _require_expected_version(
    fact: MemoryFactSnapshot,
    *,
    expected_version: int,
) -> None:
    actual_version = fact.visibility.version
    if actual_version != expected_version:
        raise ValueError(
            "Memory fact version conflict: "
            f"expected {expected_version}, actual {actual_version}"
        )


def _outbox_message(
    *,
    ids: MemoryFactIdPort,
    fact: MemoryFactSnapshot,
    event_type: str,
    occurred_at: datetime,
) -> MemoryFactOutboxMessage:
    return MemoryFactOutboxMessage(
        message_id=ids.new_outbox_message_id(),
        event_type=event_type,
        aggregate_id=fact.identity.fact_id,
        aggregate_version=fact.visibility.version,
        occurred_at=occurred_at,
    )


__all__ = (
    "FACT_CREATED_EVENT",
    "FACT_DELETED_EVENT",
    "FACT_UPDATED_EVENT",
    "ForgetFactHandler",
    "RememberFactHandler",
    "UpdateFactHandler",
)
