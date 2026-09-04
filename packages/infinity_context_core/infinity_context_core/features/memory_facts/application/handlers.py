"""Concrete application handlers for the memory_facts lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.application.authorization import (
    require_authorized_code_scope,
)
from infinity_context_core.features.memory_facts.application.commands import (
    ForgetFactCommand,
    ForgetFactResult,
    RememberFactCommand,
    RememberFactResult,
    UpdateFactCommand,
    UpdateFactResult,
)
from infinity_context_core.features.memory_facts.application.events import (
    FACT_CREATED_EVENT,
    FACT_DELETED_EVENT,
    FACT_UPDATED_EVENT,
    new_fact_outbox_message,
)
from infinity_context_core.features.memory_facts.application.idempotency import (
    lifecycle_command_fingerprint,
    normalize_memory_fact_idempotency_key,
    validate_lifecycle_replay,
)
from infinity_context_core.features.memory_facts.domain import (
    MemoryFact,
    MemoryFactIdentity,
)
from infinity_context_core.features.memory_facts.domain.taxonomy import (
    materialize_fact_retention_expiry,
)
from infinity_context_core.features.memory_facts.ports import (
    MemoryFactClockPort,
    MemoryFactIdempotencyConflict,
    MemoryFactIdPort,
    MemoryFactOperationReceipt,
    MemoryFactUnitOfWorkFactoryPort,
)


@dataclass(frozen=True, slots=True)
class RememberFactHandler:
    """Create one canonical fact through feature-owned ports."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: RememberFactCommand) -> RememberFactResult:
        key = _idempotency_key(command.idempotency_key)
        fingerprint = lifecycle_command_fingerprint(command)
        try:
            async with self.uow_factory() as uow:
                if key is not None:
                    receipt = await uow.operation_receipts.get(
                        space_id=command.scope.space_id,
                        memory_scope_id=command.scope.memory_scope_id,
                        thread_id=command.scope.thread_id,
                        operation="remember",
                        idempotency_key=key,
                    )
                    if receipt is not None:
                        return _remember_replay(receipt, fingerprint)
                await uow.coordinate_source_refs(
                    scope=command.scope,
                    source_refs=command.source_refs,
                )
                now = self.clock.now()
                aggregate = MemoryFact.remember(
                    identity=MemoryFactIdentity(
                        fact_id=self.ids.new_fact_id(),
                        scope=command.scope,
                    ),
                    text=command.text,
                    source_refs=command.source_refs,
                    now=now,
                    kind=command.kind,
                    evidence_refs=command.evidence_refs,
                    category=command.category,
                    tags=command.tags,
                    quality=command.quality,
                    temporal_extent=command.temporal_extent,
                    freshness=command.freshness,
                    retention=materialize_fact_retention_expiry(
                        command.retention,
                        now=now,
                    ),
                    epistemic_context=command.epistemic_context,
                    code_scope=command.code_scope,
                )
                saved = await uow.facts.create(aggregate.to_snapshot())
                message = new_fact_outbox_message(
                    ids=self.ids,
                    fact=saved,
                    event_type=FACT_CREATED_EVENT,
                    occurred_at=now,
                )
                await uow.outbox.enqueue(message)
                if key is not None:
                    await uow.operation_receipts.create(
                        MemoryFactOperationReceipt(
                            space_id=command.scope.space_id,
                            memory_scope_id=command.scope.memory_scope_id,
                            thread_id=command.scope.thread_id,
                            idempotency_key=key,
                            operation="remember",
                            request_fingerprint=fingerprint,
                            result_fact=saved,
                            outbox_message_ids=(message.message_id,),
                            created_at=now,
                        )
                    )
                await uow.commit()
        except MemoryFactIdempotencyConflict:
            replay = await _load_replay(
                self.uow_factory,
                space_id=command.scope.space_id,
                memory_scope_id=command.scope.memory_scope_id,
                thread_id=command.scope.thread_id,
                operation="remember",
                idempotency_key=key,
            )
            if replay is not None:
                return _remember_replay(replay, fingerprint)
            raise

        return RememberFactResult(fact=saved, outbox_message_ids=(message.message_id,))


@dataclass(frozen=True, slots=True)
class UpdateFactHandler:
    """Replace one canonical fact version through feature-owned ports."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: UpdateFactCommand) -> UpdateFactResult:
        key = _idempotency_key(command.idempotency_key)
        fingerprint = lifecycle_command_fingerprint(command)
        space_id = command.identity.scope.space_id
        try:
            async with self.uow_factory() as uow:
                if key is not None:
                    receipt = await uow.operation_receipts.get(
                        space_id=space_id,
                        memory_scope_id=command.identity.scope.memory_scope_id,
                        thread_id=command.identity.scope.thread_id,
                        operation="update",
                        idempotency_key=key,
                    )
                    if receipt is not None:
                        result = _update_replay(receipt, fingerprint)
                        require_authorized_code_scope(
                            result.fact,
                            command.authorized_code_scope,
                        )
                        return result
                await uow.coordinate_source_refs(
                    scope=command.identity.scope,
                    source_refs=command.source_refs,
                )
                current = await uow.facts.get_for_update(command.identity)
                if key is not None:
                    receipt = await uow.operation_receipts.get(
                        space_id=space_id,
                        memory_scope_id=command.identity.scope.memory_scope_id,
                        thread_id=command.identity.scope.thread_id,
                        operation="update",
                        idempotency_key=key,
                    )
                    if receipt is not None:
                        result = _update_replay(receipt, fingerprint)
                        require_authorized_code_scope(
                            result.fact,
                            command.authorized_code_scope,
                        )
                        return result
                if current is None:
                    raise LookupError(f"Memory fact not found: {command.identity.fact_id}")
                require_authorized_code_scope(current, command.authorized_code_scope)
                aggregate = MemoryFact.restore(current)
                now = self.clock.now()
                updated = aggregate.update(
                    expected_version=command.expected_version,
                    text=command.text,
                    source_refs=command.source_refs,
                    now=now,
                    kind=command.kind or aggregate.kind,
                    evidence_refs=(
                        command.evidence_refs
                        if command.evidence_refs is not None
                        else aggregate.evidence_refs
                    ),
                    category=(
                        command.category if command.category is not None else aggregate.category
                    ),
                    tags=command.tags if command.tags is not None else aggregate.tags,
                    retention=materialize_fact_retention_expiry(
                        command.retention,
                        now=now,
                    ),
                )
                saved = await uow.facts.save(updated.to_snapshot())
                now = saved.updated_at
                if now is None:  # pragma: no cover - aggregate supplies transaction time.
                    raise RuntimeError("Updated memory fact has no transaction time")
                message = new_fact_outbox_message(
                    ids=self.ids,
                    fact=saved,
                    event_type=FACT_UPDATED_EVENT,
                    occurred_at=now,
                )
                await uow.outbox.enqueue(message)
                if key is not None:
                    await uow.operation_receipts.create(
                        MemoryFactOperationReceipt(
                            space_id=space_id,
                            memory_scope_id=command.identity.scope.memory_scope_id,
                            thread_id=command.identity.scope.thread_id,
                            idempotency_key=key,
                            operation="update",
                            request_fingerprint=fingerprint,
                            result_fact=saved,
                            outbox_message_ids=(message.message_id,),
                            created_at=now,
                        )
                    )
                await uow.commit()
        except MemoryFactIdempotencyConflict:
            replay = await _load_replay(
                self.uow_factory,
                space_id=space_id,
                memory_scope_id=command.identity.scope.memory_scope_id,
                thread_id=command.identity.scope.thread_id,
                operation="update",
                idempotency_key=key,
            )
            if replay is not None:
                result = _update_replay(replay, fingerprint)
                require_authorized_code_scope(result.fact, command.authorized_code_scope)
                return result
            raise

        return UpdateFactResult(fact=saved, outbox_message_ids=(message.message_id,))


@dataclass(frozen=True, slots=True)
class ForgetFactHandler:
    """Tombstone one canonical fact through feature-owned ports."""

    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: ForgetFactCommand) -> ForgetFactResult:
        key = _idempotency_key(command.idempotency_key)
        fingerprint = lifecycle_command_fingerprint(command)
        space_id = command.identity.scope.space_id
        try:
            async with self.uow_factory() as uow:
                if key is not None:
                    receipt = await uow.operation_receipts.get(
                        space_id=space_id,
                        memory_scope_id=command.identity.scope.memory_scope_id,
                        thread_id=command.identity.scope.thread_id,
                        operation="forget",
                        idempotency_key=key,
                    )
                    if receipt is not None:
                        result = _forget_replay(receipt, fingerprint)
                        require_authorized_code_scope(
                            result.fact,
                            command.authorized_code_scope,
                        )
                        return result
                current = await uow.facts.get_for_update(command.identity)
                if key is not None:
                    receipt = await uow.operation_receipts.get(
                        space_id=space_id,
                        memory_scope_id=command.identity.scope.memory_scope_id,
                        thread_id=command.identity.scope.thread_id,
                        operation="forget",
                        idempotency_key=key,
                    )
                    if receipt is not None:
                        result = _forget_replay(receipt, fingerprint)
                        require_authorized_code_scope(
                            result.fact,
                            command.authorized_code_scope,
                        )
                        return result
                if current is None:
                    raise LookupError(f"Memory fact not found: {command.identity.fact_id}")
                require_authorized_code_scope(current, command.authorized_code_scope)
                if current.visibility.status == "deleted" and command.expected_version is None:
                    return ForgetFactResult(fact=current, already_deleted=True)
                now = self.clock.now()
                tombstone_id = self.ids.new_tombstone_id()
                forgotten = MemoryFact.restore(current).forget(
                    expected_version=command.expected_version,
                    now=now,
                )
                saved = await uow.facts.save(forgotten.to_snapshot())
                message = new_fact_outbox_message(
                    ids=self.ids,
                    fact=saved,
                    event_type=FACT_DELETED_EVENT,
                    occurred_at=now,
                )
                await uow.outbox.enqueue(message)
                if key is not None:
                    await uow.operation_receipts.create(
                        MemoryFactOperationReceipt(
                            space_id=space_id,
                            memory_scope_id=command.identity.scope.memory_scope_id,
                            thread_id=command.identity.scope.thread_id,
                            idempotency_key=key,
                            operation="forget",
                            request_fingerprint=fingerprint,
                            result_fact=saved,
                            outbox_message_ids=(message.message_id,),
                            tombstone_id=tombstone_id,
                            created_at=now,
                        )
                    )
                await uow.commit()
        except MemoryFactIdempotencyConflict:
            replay = await _load_replay(
                self.uow_factory,
                space_id=space_id,
                memory_scope_id=command.identity.scope.memory_scope_id,
                thread_id=command.identity.scope.thread_id,
                operation="forget",
                idempotency_key=key,
            )
            if replay is not None:
                result = _forget_replay(replay, fingerprint)
                require_authorized_code_scope(result.fact, command.authorized_code_scope)
                return result
            raise

        return ForgetFactResult(
            fact=saved,
            tombstone_id=tombstone_id,
            outbox_message_ids=(message.message_id,),
        )


def _idempotency_key(value: str | None) -> str | None:
    return normalize_memory_fact_idempotency_key(value)


async def _load_replay(
    uow_factory: MemoryFactUnitOfWorkFactoryPort,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    operation: str,
    idempotency_key: str | None,
) -> MemoryFactOperationReceipt | None:
    if idempotency_key is None:
        return None
    async with uow_factory() as uow:
        return await uow.operation_receipts.get(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )


def _remember_replay(
    receipt: MemoryFactOperationReceipt,
    fingerprint: str,
) -> RememberFactResult:
    validate_lifecycle_replay(
        receipt,
        operation="remember",
        request_fingerprint=fingerprint,
    )
    return RememberFactResult(receipt.result_fact, receipt.outbox_message_ids, replayed=True)


def _update_replay(
    receipt: MemoryFactOperationReceipt,
    fingerprint: str,
) -> UpdateFactResult:
    validate_lifecycle_replay(
        receipt,
        operation="update",
        request_fingerprint=fingerprint,
    )
    return UpdateFactResult(receipt.result_fact, receipt.outbox_message_ids, replayed=True)


def _forget_replay(
    receipt: MemoryFactOperationReceipt,
    fingerprint: str,
) -> ForgetFactResult:
    validate_lifecycle_replay(
        receipt,
        operation="forget",
        request_fingerprint=fingerprint,
    )
    return ForgetFactResult(
        receipt.result_fact,
        receipt.tombstone_id,
        receipt.outbox_message_ids,
        replayed=True,
    )


__all__ = (
    "FACT_CREATED_EVENT",
    "FACT_DELETED_EVENT",
    "FACT_UPDATED_EVENT",
    "ForgetFactHandler",
    "RememberFactHandler",
    "UpdateFactHandler",
)
