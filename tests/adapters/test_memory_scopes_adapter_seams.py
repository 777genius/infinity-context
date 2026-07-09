"""Import, in-memory, and placeholder checks for memory_scopes adapter seams."""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_core.features.memory_scopes.public import (
    FEATURE_ID,
    MEMORY_SCOPE_STATUS_ACTIVE,
    MEMORY_SCOPE_STATUS_ARCHIVED,
    ArchiveMemoryScopeCommand,
    ArchiveMemoryScopeHandler,
    CreateMemoryScopeCommand,
    CreateMemoryScopeHandler,
    DuplicateMemoryScopeExternalRefError,
    MemoryScopeActor,
    MemoryScopeIdentity,
    MemoryScopeOwner,
    MemoryScopeSnapshot,
    RestoreMemoryScopeCommand,
    RestoreMemoryScopeHandler,
    TransferMemoryScopeOwnershipCommand,
    TransferMemoryScopeOwnershipHandler,
)
from sdk_module_isolation import provider_sdk_modules_unloaded

FEATURE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "infinity_context_adapters"
    / "infinity_context_adapters"
    / "features"
    / "memory_scopes"
)
ALLOWED_CORE_FEATURE_IMPORT = "infinity_context_core.features.memory_scopes.public"
FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "graphiti",
    "graphiti_core",
    "infinity_context_core.features.memory_scopes.application",
    "infinity_context_core.features.memory_scopes.domain",
    "infinity_context_core.features.memory_scopes.ports",
    "openai",
    "qdrant_client",
    "sqlalchemy",
)


def test_memory_scopes_adapter_package_mirrors_feature_id() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_scopes")
    features = importlib.import_module("infinity_context_adapters.features")

    assert "memory_scopes" in features.__all__
    assert module.FEATURE_ID == FEATURE_ID == "memory_scopes"
    assert module.InMemoryMemoryScopeRepository.feature_id == FEATURE_ID
    assert module.InMemoryMemoryScopeUnitOfWork.feature_id == FEATURE_ID
    assert module.InMemoryMemoryScopeUnitOfWorkFactory.feature_id == FEATURE_ID
    assert module.MemoryScopeRecord.feature_id == FEATURE_ID
    assert module.PostgresMemoryScopeStore.feature_id == FEATURE_ID
    assert module.PostgresMemoryScopeUnitOfWork.feature_id == FEATURE_ID
    assert module.PostgresMemoryScopeUnitOfWorkFactory.feature_id == FEATURE_ID


def test_memory_scopes_adapter_imports_do_not_load_provider_sdks() -> None:
    with provider_sdk_modules_unloaded(
        "sqlalchemy",
        "qdrant_client",
        "graphiti",
        "graphiti_core",
        "openai",
        "fastapi",
    ):
        importlib.import_module("infinity_context_adapters.features.memory_scopes")

        assert "sqlalchemy" not in sys.modules
        assert "qdrant_client" not in sys.modules
        assert "graphiti" not in sys.modules
        assert "graphiti_core" not in sys.modules
        assert "openai" not in sys.modules
        assert "fastapi" not in sys.modules


def test_memory_scopes_adapter_imports_only_public_core_feature_api() -> None:
    violations: list[str] = []

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            if imported == ALLOWED_CORE_FEATURE_IMPORT:
                continue
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


def test_in_memory_memory_scope_uow_drives_core_lifecycle_handlers() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_scopes")
    factory = module.create_in_memory_memory_scope_unit_of_work_factory()
    clock = _FixedClock(_time(1))
    owner_1 = MemoryScopeOwner(principal_id="owner-1")
    owner_2 = MemoryScopeOwner(principal_id="owner-2")

    create_result = asyncio.run(
        CreateMemoryScopeHandler(
            uow_factory=factory,
            ids=_FixedIds("scope-1"),
            clock=clock,
        ).execute(
            CreateMemoryScopeCommand(
                space_id="space-1",
                name="Default",
                owner=owner_1,
                external_ref="default",
                description="Primary memory scope",
            )
        )
    )

    assert create_result.scope.identity == MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    assert create_result.scope.created_at == _time(1)
    assert create_result.scope.updated_at == _time(1)

    clock.now_value = _time(2)
    transfer_result = asyncio.run(
        TransferMemoryScopeOwnershipHandler(
            uow_factory=factory,
            clock=clock,
        ).execute(
            TransferMemoryScopeOwnershipCommand(
                identity=create_result.scope.identity,
                new_owner=owner_2,
                initiated_by=MemoryScopeActor(principal_id="owner-1"),
                expected_current_owner=owner_1,
            )
        )
    )

    assert transfer_result.previous_owner == owner_1
    assert transfer_result.scope.owner == owner_2
    assert transfer_result.scope.updated_at == _time(2)

    clock.now_value = _time(3)
    archive_result = asyncio.run(
        ArchiveMemoryScopeHandler(
            uow_factory=factory,
            clock=clock,
        ).execute(
            ArchiveMemoryScopeCommand(
                identity=create_result.scope.identity,
                initiated_by=MemoryScopeActor(principal_id="owner-2"),
                expected_status=MEMORY_SCOPE_STATUS_ACTIVE,
            )
        )
    )

    assert archive_result.previous_status == MEMORY_SCOPE_STATUS_ACTIVE
    assert archive_result.scope.status == MEMORY_SCOPE_STATUS_ARCHIVED
    assert archive_result.scope.archived_at == _time(3)

    clock.now_value = _time(4)
    restore_result = asyncio.run(
        RestoreMemoryScopeHandler(
            uow_factory=factory,
            clock=clock,
        ).execute(
            RestoreMemoryScopeCommand(
                identity=create_result.scope.identity,
                initiated_by=MemoryScopeActor(principal_id="owner-2"),
                expected_status=MEMORY_SCOPE_STATUS_ARCHIVED,
            )
        )
    )

    assert restore_result.previous_status == MEMORY_SCOPE_STATUS_ARCHIVED
    assert restore_result.scope.status == MEMORY_SCOPE_STATUS_ACTIVE
    assert restore_result.scope.archived_at is None
    assert asyncio.run(_load_scope(factory, create_result.scope.identity)) == restore_result.scope


def test_in_memory_memory_scope_uow_rolls_back_uncommitted_changes() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_scopes")
    scope = _scope()
    factory = module.create_in_memory_memory_scope_unit_of_work_factory()

    asyncio.run(_create_without_commit(factory, scope))

    assert asyncio.run(_load_scope(factory, scope.identity)) is None

    asyncio.run(_create_with_commit(factory, scope))

    with pytest.raises(RuntimeError, match="force rollback"):
        asyncio.run(_transfer_then_fail(factory, scope))

    loaded = asyncio.run(_load_scope(factory, scope.identity))

    assert loaded is not None
    assert loaded.owner == scope.owner


def test_in_memory_memory_scope_uow_supports_external_ref_uniqueness_checks() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_scopes")
    factory = module.create_in_memory_memory_scope_unit_of_work_factory((_scope(),))

    with pytest.raises(
        DuplicateMemoryScopeExternalRefError,
        match="memory_scope_external_ref_already_exists",
    ):
        asyncio.run(
            CreateMemoryScopeHandler(
                uow_factory=factory,
                ids=_FixedIds("scope-2"),
                clock=_FixedClock(_time(1)),
            ).execute(
                CreateMemoryScopeCommand(
                    space_id="space-1",
                    name="Duplicate",
                    owner=MemoryScopeOwner(principal_id="owner-2"),
                    external_ref="default",
                )
            )
        )

    assert (
        asyncio.run(
            _load_scope(
                factory,
                MemoryScopeIdentity(space_id="space-1", memory_scope_id="scope-2"),
            )
        )
        is None
    )


def test_memory_scope_record_round_trips_public_snapshot() -> None:
    module = importlib.import_module("infinity_context_adapters.features.memory_scopes")
    scope = MemoryScopeSnapshot(
        identity=MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        name="Default",
        owner=MemoryScopeOwner(
            principal_id="owner-1",
            principal_kind="service",
        ),
        external_ref="default",
        description="Primary memory scope",
        created_at=_time(1),
        updated_at=_time(2),
    )

    record = module.MemoryScopeRecord.from_snapshot(scope)
    factory_record = module.memory_scope_record_from_snapshot(scope)

    assert record == factory_record
    assert record.feature_id == FEATURE_ID
    assert record.space_id == "space-1"
    assert record.memory_scope_id == "scope-1"
    assert record.owner_principal_id == "owner-1"
    assert record.owner_principal_kind == "service"
    assert record.to_snapshot() == scope


def test_postgres_memory_scope_store_is_explicit_placeholder() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_scopes.postgres_scope_store"
    )
    scope = _scope()

    with pytest.raises(
        NotImplementedError,
        match="canonical memory scope persistence wiring is deferred",
    ):
        asyncio.run(module.PostgresMemoryScopeStore().create(scope))

    with pytest.raises(
        NotImplementedError,
        match="canonical memory scope persistence wiring is deferred",
    ):
        asyncio.run(module.create_postgres_memory_scope_store().get(scope.identity))


def test_postgres_memory_scope_unit_of_work_exposes_transfer_support_seam() -> None:
    module = importlib.import_module(
        "infinity_context_adapters.features.memory_scopes.postgres_scope_store"
    )
    scope = _scope()
    transferred = scope.transfer_ownership(MemoryScopeOwner(principal_id="owner-2"))

    factory = module.create_postgres_memory_scope_unit_of_work_factory()
    uow = factory()

    assert factory.feature_id == FEATURE_ID
    assert uow.feature_id == FEATURE_ID
    assert uow.memory_scopes.feature_id == FEATURE_ID

    with pytest.raises(
        NotImplementedError,
        match="canonical memory scope persistence wiring is deferred",
    ):
        asyncio.run(uow.memory_scopes.get_for_update(scope.identity))

    with pytest.raises(
        NotImplementedError,
        match="canonical memory scope persistence wiring is deferred",
    ):
        asyncio.run(uow.memory_scopes.save(transferred))


def _scope() -> MemoryScopeSnapshot:
    return MemoryScopeSnapshot(
        identity=MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        name="Default",
        owner=MemoryScopeOwner(principal_id="owner-1"),
        external_ref="default",
    )


def _time(second: int) -> datetime:
    return datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC)


class _FixedClock:
    def __init__(self, now_value: datetime) -> None:
        self.now_value = now_value

    def now(self) -> datetime:
        return self.now_value


class _FixedIds:
    def __init__(self, *ids: str) -> None:
        self._ids = list(ids)

    def new_memory_scope_id(self) -> str:
        return self._ids.pop(0)


async def _load_scope(
    factory: object,
    identity: MemoryScopeIdentity,
) -> MemoryScopeSnapshot | None:
    async with factory() as uow:
        return await uow.memory_scopes.get(identity)


async def _create_without_commit(factory: object, scope: MemoryScopeSnapshot) -> None:
    async with factory() as uow:
        await uow.memory_scopes.create(scope)


async def _create_with_commit(factory: object, scope: MemoryScopeSnapshot) -> None:
    async with factory() as uow:
        await uow.memory_scopes.create(scope)
        await uow.commit()


async def _transfer_then_fail(factory: object, scope: MemoryScopeSnapshot) -> None:
    async with factory() as uow:
        current = await uow.memory_scopes.get_for_update(scope.identity)
        assert current is not None
        await uow.memory_scopes.save(
            current.transfer_ownership(MemoryScopeOwner(principal_id="owner-2"))
        )
        raise RuntimeError("force rollback")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def _matches_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)
