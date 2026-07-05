"""Feature-local checks for memory_scopes application, ports and public API."""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path


APPLICATION_MODULE = "infinity_context_core.features.memory_scopes.application"
DOMAIN_MODULE = "infinity_context_core.features.memory_scopes.domain"
PORTS_MODULE = "infinity_context_core.features.memory_scopes.ports"
PUBLIC_MODULE = "infinity_context_core.features.memory_scopes.public"
FEATURE_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = FEATURE_ROOT.parents[3]
ALLOWED_CORE_PREFIXES = (
    "infinity_context_core.features.memory_scopes.application",
    "infinity_context_core.features.memory_scopes.domain",
    "infinity_context_core.features.memory_scopes.ports",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "anthropic",
    "fastapi",
    "graphiti",
    "graphiti_core",
    "infinity_context_adapters",
    "infinity_context_core.application",
    "infinity_context_core.domain",
    "infinity_context_core.ports",
    "infinity_context_mcp",
    "infinity_context_server",
    "openai",
    "qdrant_client",
    "sqlalchemy",
)


def test_create_and_transfer_commands_are_frozen_dataclasses() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    new_owner = domain.MemoryScopeOwner(principal_id="owner-2")
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    actor = domain.MemoryScopeActor(principal_id="owner-1")
    snapshot = domain.MemoryScopeSnapshot(
        identity=identity,
        name="Default",
        owner=owner,
    )

    shapes = (
        (
            application.CreateMemoryScopeCommand,
            application.CreateMemoryScopeCommand(
                space_id="space-1",
                name="Default",
                owner=owner,
                external_ref="default",
                idempotency_key="create-1",
            ),
            (
                "space_id",
                "name",
                "owner",
                "external_ref",
                "description",
                "idempotency_key",
            ),
        ),
        (
            application.CreateMemoryScopeResult,
            application.CreateMemoryScopeResult(scope=snapshot),
            ("scope",),
        ),
        (
            application.TransferMemoryScopeOwnershipCommand,
            application.TransferMemoryScopeOwnershipCommand(
                identity=identity,
                new_owner=new_owner,
                initiated_by=actor,
                expected_current_owner=owner,
                reason="owner rotation",
            ),
            (
                "identity",
                "new_owner",
                "initiated_by",
                "expected_current_owner",
                "reason",
                "idempotency_key",
            ),
        ),
        (
            application.TransferMemoryScopeOwnershipResult,
            application.TransferMemoryScopeOwnershipResult(
                scope=snapshot,
                previous_owner=owner,
            ),
            ("scope", "previous_owner"),
        ),
    )

    for shape, value, expected_fields in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        assert tuple(field.name for field in fields(shape)) == expected_fields
        _assert_frozen(value)


def test_memory_scope_ports_are_protocol_boundaries() -> None:
    ports = importlib.import_module(PORTS_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    protocol_names = (
        "MemoryScopeClockPort",
        "MemoryScopeIdPort",
        "MemoryScopeRepositoryPort",
        "MemoryScopeUnitOfWorkFactoryPort",
        "MemoryScopeUnitOfWorkPort",
    )
    for name in protocol_names:
        assert getattr(getattr(ports, name), "_is_protocol", False)

    for method_name in ("create", "get", "get_for_update", "get_by_external_ref", "save"):
        assert inspect.iscoroutinefunction(
            getattr(ports.MemoryScopeRepositoryPort, method_name)
        )
    for method_name in ("__aenter__", "__aexit__", "commit", "rollback"):
        assert inspect.iscoroutinefunction(
            getattr(ports.MemoryScopeUnitOfWorkPort, method_name)
        )
    assert not inspect.iscoroutinefunction(ports.MemoryScopeIdPort.new_memory_scope_id)
    assert not inspect.iscoroutinefunction(ports.MemoryScopeClockPort.now)
    assert not inspect.iscoroutinefunction(ports.MemoryScopeUnitOfWorkFactoryPort.__call__)

    annotations = ports.MemoryScopeUnitOfWorkPort.__annotations__
    assert annotations["memory_scopes"] == "MemoryScopeRepositoryPort"
    assert domain.MemoryScopeSnapshot.__name__ == "MemoryScopeSnapshot"


def test_memory_scopes_public_api_exports_domain_application_and_ports() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)
    ports = importlib.import_module(PORTS_MODULE)
    public = importlib.import_module(PUBLIC_MODULE)

    expected_exports = {
        "CreateMemoryScopeCommand": application,
        "CreateMemoryScopeHandler": application,
        "CreateMemoryScopeResult": application,
        "CreateMemoryScopeUseCase": application,
        "DuplicateMemoryScopeExternalRefError": application,
        "MemoryScopeActor": domain,
        "MemoryScopeClockPort": ports,
        "MemoryScopeConflictError": application,
        "MemoryScopeIdPort": ports,
        "MemoryScopeIdentity": domain,
        "MemoryScopeOwner": domain,
        "MemoryScopeOwnershipPolicy": domain,
        "MemoryScopeRepositoryPort": ports,
        "MemoryScopeSnapshot": domain,
        "MemoryScopeUnitOfWorkFactoryPort": ports,
        "MemoryScopeUnitOfWorkPort": ports,
        "MemoryScopeUseCases": application,
        "TransferMemoryScopeOwnershipCommand": application,
        "TransferMemoryScopeOwnershipHandler": application,
        "TransferMemoryScopeOwnershipResult": application,
        "TransferMemoryScopeOwnershipUseCase": application,
    }

    assert expected_exports.keys() <= set(public.__all__)
    for name, module in expected_exports.items():
        assert getattr(public, name) is getattr(module, name)


def test_create_handler_allocates_canonical_identity_and_checks_external_ref() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repo = _MemoryScopeRepository()
    uow = _MemoryScopeUnitOfWork(repo)
    handler = application.CreateMemoryScopeHandler(
        uow_factory=_UnitOfWorkFactory(uow),
        ids=_MemoryScopeIds("scope-1"),
        clock=_MemoryScopeClock(now),
    )

    result = asyncio.run(
        handler.execute(
            application.CreateMemoryScopeCommand(
                space_id="space-1",
                name="Default",
                owner=domain.MemoryScopeOwner(principal_id="owner-1"),
                external_ref="default",
            )
        )
    )

    assert result.scope.identity == domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    assert result.scope.owner == domain.MemoryScopeOwner(principal_id="owner-1")
    assert result.scope.created_at == now
    assert result.scope.updated_at == now
    assert repo.get_stored(result.scope.identity) == result.scope
    assert uow.committed
    assert not uow.rolled_back


def test_create_handler_rejects_duplicate_space_external_ref() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    existing = domain.MemoryScopeSnapshot(
        identity=domain.MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-existing",
        ),
        name="Existing",
        owner=domain.MemoryScopeOwner(principal_id="owner-1"),
        external_ref="default",
    )
    repo = _MemoryScopeRepository(existing)
    uow = _MemoryScopeUnitOfWork(repo)
    handler = application.CreateMemoryScopeHandler(
        uow_factory=_UnitOfWorkFactory(uow),
        ids=_MemoryScopeIds("scope-new"),
        clock=_MemoryScopeClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )

    try:
        asyncio.run(
            handler.execute(
                application.CreateMemoryScopeCommand(
                    space_id="space-1",
                    name="Duplicate",
                    owner=domain.MemoryScopeOwner(principal_id="owner-1"),
                    external_ref="default",
                )
            )
        )
    except application.DuplicateMemoryScopeExternalRefError:
        pass
    else:  # pragma: no cover - clearer assertion failure branch.
        raise AssertionError("duplicate memory scope external ref should fail")

    assert repo.get_stored(existing.identity) == existing
    assert not uow.committed
    assert uow.rolled_back


def test_transfer_handler_uses_policy_and_preserves_scope_identity() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    current = domain.MemoryScopeSnapshot(
        identity=identity,
        name="Default",
        owner=owner,
        external_ref="default",
    )
    repo = _MemoryScopeRepository(current)
    uow = _MemoryScopeUnitOfWork(repo)
    handler = application.TransferMemoryScopeOwnershipHandler(
        uow_factory=_UnitOfWorkFactory(uow),
        clock=_MemoryScopeClock(now),
    )
    new_owner = domain.MemoryScopeOwner(principal_id="owner-2")

    result = asyncio.run(
        handler.execute(
            application.TransferMemoryScopeOwnershipCommand(
                identity=identity,
                new_owner=new_owner,
                initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
                expected_current_owner=owner,
            )
        )
    )

    assert result.previous_owner == owner
    assert result.scope.identity == identity
    assert result.scope.owner == new_owner
    assert result.scope.updated_at == now
    assert repo.get_stored(identity) == result.scope
    assert uow.committed
    assert not uow.rolled_back


def test_transfer_handler_rejects_missing_scope_without_commit() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-missing",
    )
    repo = _MemoryScopeRepository()
    uow = _MemoryScopeUnitOfWork(repo)
    handler = application.TransferMemoryScopeOwnershipHandler(
        uow_factory=_UnitOfWorkFactory(uow),
        clock=_MemoryScopeClock(now),
    )

    try:
        asyncio.run(
            handler.execute(
                application.TransferMemoryScopeOwnershipCommand(
                    identity=identity,
                    new_owner=domain.MemoryScopeOwner(principal_id="owner-2"),
                    initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
                )
            )
        )
    except application.MemoryScopeNotFoundError:
        pass
    else:  # pragma: no cover - clearer assertion failure branch.
        raise AssertionError("missing memory scope transfer should fail")

    assert not uow.committed
    assert uow.rolled_back


def test_transfer_handler_rejects_expected_owner_conflict_without_save() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    current = domain.MemoryScopeSnapshot(
        identity=identity,
        name="Default",
        owner=owner,
    )
    repo = _MemoryScopeRepository(current)
    uow = _MemoryScopeUnitOfWork(repo)
    handler = application.TransferMemoryScopeOwnershipHandler(
        uow_factory=_UnitOfWorkFactory(uow),
        clock=_MemoryScopeClock(now),
    )

    try:
        asyncio.run(
            handler.execute(
                application.TransferMemoryScopeOwnershipCommand(
                    identity=identity,
                    new_owner=domain.MemoryScopeOwner(principal_id="owner-2"),
                    initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
                    expected_current_owner=domain.MemoryScopeOwner(
                        principal_id="owner-stale"
                    ),
                )
            )
        )
    except application.MemoryScopeConflictError:
        pass
    else:  # pragma: no cover - clearer assertion failure branch.
        raise AssertionError("stale memory scope owner expectation should fail")

    assert repo.get_stored(identity) == current
    assert not uow.committed
    assert uow.rolled_back


def test_transfer_handler_rolls_back_policy_denial_without_save() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    current = domain.MemoryScopeSnapshot(
        identity=identity,
        name="Default",
        owner=owner,
    )
    repo = _MemoryScopeRepository(current)
    uow = _MemoryScopeUnitOfWork(repo)
    handler = application.TransferMemoryScopeOwnershipHandler(
        uow_factory=_UnitOfWorkFactory(uow),
        clock=_MemoryScopeClock(now),
    )

    try:
        asyncio.run(
            handler.execute(
                application.TransferMemoryScopeOwnershipCommand(
                    identity=identity,
                    new_owner=domain.MemoryScopeOwner(principal_id="owner-2"),
                    initiated_by=domain.MemoryScopeActor(principal_id="outsider-1"),
                )
            )
        )
    except domain.MemoryScopeOwnershipError:
        pass
    else:  # pragma: no cover - clearer assertion failure branch.
        raise AssertionError("unauthorized memory scope transfer should fail")

    assert repo.get_stored(identity) == current
    assert not uow.committed
    assert uow.rolled_back


def test_application_ports_and_public_import_only_feature_owned_core() -> None:
    paths = [
        *sorted((FEATURE_ROOT / "application").rglob("*.py")),
        *sorted((FEATURE_ROOT / "ports").rglob("*.py")),
        FEATURE_ROOT / "public.py",
    ]
    violations: list[str] = []

    for path in paths:
        for imported in _imports(path):
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")
            if imported.startswith("infinity_context_core.") and not _matches_prefix(
                imported,
                ALLOWED_CORE_PREFIXES,
            ):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


def _assert_frozen(value: object) -> None:
    field_name = fields(value)[0].name
    try:
        setattr(value, field_name, None)
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - this branch is only for a clearer assertion failure.
        raise AssertionError(f"{type(value).__name__} should be immutable")


class _MemoryScopeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _MemoryScopeIds:
    def __init__(self, *scope_ids: str) -> None:
        self._scope_ids = list(scope_ids)

    def new_memory_scope_id(self) -> str:
        return self._scope_ids.pop(0)


class _MemoryScopeRepository:
    def __init__(self, *scopes: object) -> None:
        self._scopes = {scope.identity: scope for scope in scopes}

    async def create(self, scope: object) -> object:
        self._scopes[scope.identity] = scope
        return scope

    async def get(self, identity: object) -> object | None:
        return self._scopes.get(identity)

    async def get_for_update(self, identity: object) -> object | None:
        return self._scopes.get(identity)

    async def get_by_external_ref(
        self,
        space_id: str,
        external_ref: str,
    ) -> object | None:
        for scope in self._scopes.values():
            if scope.identity.space_id == space_id and scope.external_ref == external_ref:
                return scope
        return None

    async def save(self, scope: object) -> object:
        self._scopes[scope.identity] = scope
        return scope

    def get_stored(self, identity: object) -> object | None:
        return self._scopes.get(identity)


class _MemoryScopeUnitOfWork:
    def __init__(self, repo: _MemoryScopeRepository) -> None:
        self.memory_scopes = repo
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _MemoryScopeUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _UnitOfWorkFactory:
    def __init__(self, uow: _MemoryScopeUnitOfWork) -> None:
        self._uow = uow

    def __call__(self) -> _MemoryScopeUnitOfWork:
        return self._uow


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported = _resolve_import_from(path, node)
            if imported is not None:
                imports.append(imported)
    return imports


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    module = node.module or ""
    if node.level == 0:
        return module or None

    package = _package_context(path)
    if package is None:
        return module or None

    package_parts = package.split(".")
    if node.level > len(package_parts):
        return module or None

    resolved_parts = package_parts[: len(package_parts) - node.level + 1]
    if module:
        resolved_parts.extend(module.split("."))
    return ".".join(resolved_parts)


def _package_context(path: Path) -> str | None:
    relative = path.relative_to(PACKAGES_ROOT)
    parts = relative.with_suffix("").parts
    if len(parts) < 2:
        return None

    module_parts = list(parts[1:])
    if module_parts[-1] == "__init__":
        module_parts.pop()
    else:
        module_parts.pop()

    if not module_parts:
        return None
    return ".".join(module_parts)


def _matches_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for prefix in prefixes
    )
