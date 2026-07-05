"""Import and placeholder checks for memory_scopes adapter seams."""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
from pathlib import Path

import pytest

from infinity_context_core.features.memory_scopes.public import (
    FEATURE_ID,
    MemoryScopeIdentity,
    MemoryScopeOwner,
    MemoryScopeSnapshot,
)


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
    assert module.PostgresMemoryScopeStore.feature_id == FEATURE_ID
    assert module.PostgresMemoryScopeUnitOfWork.feature_id == FEATURE_ID
    assert module.PostgresMemoryScopeUnitOfWorkFactory.feature_id == FEATURE_ID


def test_memory_scopes_adapter_imports_do_not_load_provider_sdks() -> None:
    for module_name in (
        "sqlalchemy",
        "qdrant_client",
        "graphiti",
        "graphiti_core",
        "openai",
        "fastapi",
    ):
        sys.modules.pop(module_name, None)

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
    return any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for prefix in prefixes
    )
