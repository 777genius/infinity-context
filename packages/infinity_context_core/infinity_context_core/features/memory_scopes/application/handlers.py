"""Application handlers for feature-owned memory scope commands."""

from __future__ import annotations

from infinity_context_core.features.memory_scopes.application.commands import (
    CreateMemoryScopeCommand,
    CreateMemoryScopeResult,
    TransferMemoryScopeOwnershipCommand,
    TransferMemoryScopeOwnershipResult,
)
from infinity_context_core.features.memory_scopes.application.errors import (
    DuplicateMemoryScopeExternalRefError,
    MemoryScopeConflictError,
    MemoryScopeNotFoundError,
)
from infinity_context_core.features.memory_scopes.domain import (
    MemoryScopeIdentity,
    MemoryScopeOwnershipPolicy,
    MemoryScopeSnapshot,
)
from infinity_context_core.features.memory_scopes.ports import (
    MemoryScopeClockPort,
    MemoryScopeIdPort,
    MemoryScopeUnitOfWorkFactoryPort,
)


class CreateMemoryScopeHandler:
    """Create a canonical memory scope through feature-owned ports."""

    def __init__(
        self,
        *,
        uow_factory: MemoryScopeUnitOfWorkFactoryPort,
        ids: MemoryScopeIdPort,
        clock: MemoryScopeClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(
        self,
        command: CreateMemoryScopeCommand,
    ) -> CreateMemoryScopeResult:
        now = self._clock.now()
        scope = MemoryScopeSnapshot(
            identity=MemoryScopeIdentity(
                space_id=command.space_id,
                memory_scope_id=self._ids.new_memory_scope_id(),
            ),
            name=command.name,
            owner=command.owner,
            external_ref=command.external_ref,
            description=command.description,
            created_at=now,
            updated_at=now,
        )

        async with self._uow_factory() as uow:
            if command.external_ref is not None:
                existing = await uow.memory_scopes.get_by_external_ref(
                    command.space_id,
                    command.external_ref,
                )
                if existing is not None:
                    raise DuplicateMemoryScopeExternalRefError(
                        "memory_scope_external_ref_already_exists"
                    )
            created = await uow.memory_scopes.create(scope)
            await uow.commit()

        return CreateMemoryScopeResult(scope=created)


class TransferMemoryScopeOwnershipHandler:
    """Transfer memory scope ownership through feature-owned ports."""

    def __init__(
        self,
        *,
        uow_factory: MemoryScopeUnitOfWorkFactoryPort,
        clock: MemoryScopeClockPort,
        policy: MemoryScopeOwnershipPolicy | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._policy = policy or MemoryScopeOwnershipPolicy()

    async def execute(
        self,
        command: TransferMemoryScopeOwnershipCommand,
    ) -> TransferMemoryScopeOwnershipResult:
        async with self._uow_factory() as uow:
            current = await uow.memory_scopes.get_for_update(command.identity)
            if current is None:
                raise MemoryScopeNotFoundError("memory_scope_not_found")
            if (
                command.expected_current_owner is not None
                and current.owner != command.expected_current_owner
            ):
                raise MemoryScopeConflictError("memory_scope_owner_changed")

            self._policy.assert_can_transfer(
                current,
                initiated_by=command.initiated_by,
                new_owner=command.new_owner,
            )
            saved = await uow.memory_scopes.save(
                current.transfer_ownership(
                    command.new_owner,
                    transferred_at=self._clock.now(),
                )
            )
            await uow.commit()

        return TransferMemoryScopeOwnershipResult(
            scope=saved,
            previous_owner=current.owner,
        )


__all__ = ("CreateMemoryScopeHandler", "TransferMemoryScopeOwnershipHandler")
