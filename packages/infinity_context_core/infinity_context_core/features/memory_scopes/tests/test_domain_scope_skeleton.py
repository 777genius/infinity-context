"""Feature-local checks for the memory_scopes domain skeleton."""

from __future__ import annotations

import ast
import importlib
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import UTC, datetime
from pathlib import Path

DOMAIN_MODULE = "infinity_context_core.features.memory_scopes.domain"
SCOPE_MODULE = f"{DOMAIN_MODULE}.scope"
POLICIES_MODULE = f"{DOMAIN_MODULE}.policies"
FEATURE_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = FEATURE_ROOT.parents[3]
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


def test_domain_scope_skeleton_is_imported_and_exported() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)
    scope = importlib.import_module(SCOPE_MODULE)
    policies = importlib.import_module(POLICIES_MODULE)

    expected_scope_exports = {
        "MEMORY_SCOPE_STATUS_ACTIVE",
        "MEMORY_SCOPE_STATUS_ARCHIVED",
        "MEMORY_SCOPE_STATUS_DELETED",
        "MemoryScopeActor",
        "MemoryScopeIdentity",
        "MemoryScopeOwner",
        "MemoryScopeSnapshot",
        "MemoryScopeStatus",
        "VALID_MEMORY_SCOPE_STATUSES",
    }
    expected_policy_exports = {
        "MEMORY_SCOPE_ADMIN_CAPABILITY",
        "MEMORY_SCOPE_LIFECYCLE_CAPABILITY",
        "MEMORY_SCOPE_TRANSFER_CAPABILITY",
        "MemoryScopeLifecycleDecision",
        "MemoryScopeLifecyclePolicy",
        "MemoryScopeOwnershipDecision",
        "MemoryScopeOwnershipPolicy",
    }

    assert expected_scope_exports | expected_policy_exports <= set(domain.__all__)
    for export in expected_scope_exports:
        assert getattr(domain, export) is getattr(scope, export)
    for export in expected_policy_exports:
        assert getattr(domain, export) is getattr(policies, export)


def test_scope_domain_shapes_are_frozen_slot_dataclasses() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    actor = domain.MemoryScopeActor(
        principal_id="owner-1",
        capabilities=(domain.MEMORY_SCOPE_TRANSFER_CAPABILITY,),
    )
    snapshot = domain.MemoryScopeSnapshot(
        identity=identity,
        name="Default",
        owner=owner,
        external_ref="default",
        description="Client App default memory scope",
    )
    decision = domain.MemoryScopeOwnershipDecision.allow()
    lifecycle_decision = domain.MemoryScopeLifecycleDecision.allow()

    shapes = (
        (domain.MemoryScopeIdentity, identity, "space_id", "space-2"),
        (domain.MemoryScopeOwner, owner, "principal_id", "owner-2"),
        (domain.MemoryScopeActor, actor, "principal_id", "actor-2"),
        (domain.MemoryScopeSnapshot, snapshot, "name", "Renamed"),
        (domain.MemoryScopeOwnershipDecision, decision, "allowed", False),
        (domain.MemoryScopeLifecycleDecision, lifecycle_decision, "allowed", False),
        (domain.MemoryScopeOwnershipPolicy, domain.MemoryScopeOwnershipPolicy(), None, None),
        (domain.MemoryScopeLifecyclePolicy, domain.MemoryScopeLifecyclePolicy(), None, None),
    )

    for shape, value, field_name, replacement in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        if field_name is not None:
            _assert_frozen(value, field_name, replacement)


def test_scope_identity_and_owner_reject_blank_values() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    factories = (
        lambda: domain.MemoryScopeIdentity(space_id="", memory_scope_id="scope-1"),
        lambda: domain.MemoryScopeIdentity(space_id="space-1", memory_scope_id=" "),
        lambda: domain.MemoryScopeOwner(principal_id=""),
        lambda: domain.MemoryScopeActor(principal_id="actor-1", capabilities=("",)),
        lambda: domain.MemoryScopeSnapshot(
            identity=domain.MemoryScopeIdentity(
                space_id="space-1",
                memory_scope_id="scope-1",
            ),
            name=" ",
            owner=domain.MemoryScopeOwner(principal_id="owner-1"),
        ),
        lambda: domain.MemoryScopeSnapshot(
            identity=domain.MemoryScopeIdentity(
                space_id="space-1",
                memory_scope_id="scope-1",
            ),
            name="Default",
            owner=domain.MemoryScopeOwner(principal_id="owner-1"),
            external_ref=" ",
        ),
        lambda: domain.MemoryScopeSnapshot(
            identity=domain.MemoryScopeIdentity(
                space_id="space-1",
                memory_scope_id="scope-1",
            ),
            name="Default",
            owner=domain.MemoryScopeOwner(principal_id="owner-1"),
            status="suspended",
        ),
    )

    for factory in factories:
        try:
            factory()
        except domain.MemoryScopeDomainError:
            pass
        else:  # pragma: no cover - clearer assertion failure branch.
            raise AssertionError("blank or invalid scope value should fail")


def test_ownership_policy_allows_owner_or_admin_transfer_only_for_active_scope() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    new_owner = domain.MemoryScopeOwner(principal_id="owner-2")
    scope = domain.MemoryScopeSnapshot(
        identity=domain.MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        name="Default",
        owner=owner,
    )
    policy = domain.MemoryScopeOwnershipPolicy()

    owner_decision = policy.decide_transfer(
        scope,
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
        new_owner=new_owner,
    )
    admin_decision = policy.decide_transfer(
        scope,
        initiated_by=domain.MemoryScopeActor(
            principal_id="admin-1",
            capabilities=(domain.MEMORY_SCOPE_ADMIN_CAPABILITY,),
        ),
        new_owner=new_owner,
    )
    outsider_decision = policy.decide_transfer(
        scope,
        initiated_by=domain.MemoryScopeActor(principal_id="outsider-1"),
        new_owner=new_owner,
    )
    archived_decision = policy.decide_transfer(
        scope.archive(),
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
        new_owner=new_owner,
    )
    unchanged_decision = policy.decide_transfer(
        scope,
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
        new_owner=owner,
    )

    assert owner_decision.allowed
    assert admin_decision.allowed
    assert not outsider_decision.allowed
    assert outsider_decision.reason == "actor_cannot_transfer_memory_scope"
    assert not archived_decision.allowed
    assert archived_decision.reason == "memory_scope_not_active"
    assert not unchanged_decision.allowed
    assert unchanged_decision.reason == "owner_unchanged"


def test_lifecycle_policy_allows_owner_admin_or_lifecycle_actor() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    owner = domain.MemoryScopeOwner(principal_id="owner-1")
    scope = domain.MemoryScopeSnapshot(
        identity=domain.MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        name="Default",
        owner=owner,
    )
    archived = scope.archive()
    deleted = domain.MemoryScopeSnapshot(
        identity=scope.identity,
        name=scope.name,
        owner=owner,
        status=domain.MEMORY_SCOPE_STATUS_DELETED,
    )
    policy = domain.MemoryScopeLifecyclePolicy()

    owner_archive = policy.decide_archive(
        scope,
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
    )
    lifecycle_archive = policy.decide_archive(
        scope,
        initiated_by=domain.MemoryScopeActor(
            principal_id="manager-1",
            capabilities=(domain.MEMORY_SCOPE_LIFECYCLE_CAPABILITY,),
        ),
    )
    admin_restore = policy.decide_restore(
        archived,
        initiated_by=domain.MemoryScopeActor(
            principal_id="admin-1",
            capabilities=(domain.MEMORY_SCOPE_ADMIN_CAPABILITY,),
        ),
    )
    outsider_archive = policy.decide_archive(
        scope,
        initiated_by=domain.MemoryScopeActor(principal_id="outsider-1"),
    )
    active_restore = policy.decide_restore(
        scope,
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
    )
    archived_archive = policy.decide_archive(
        archived,
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
    )
    deleted_restore = policy.decide_restore(
        deleted,
        initiated_by=domain.MemoryScopeActor(principal_id="owner-1"),
    )

    assert owner_archive.allowed
    assert lifecycle_archive.allowed
    assert admin_restore.allowed
    assert not outsider_archive.allowed
    assert outsider_archive.reason == "actor_cannot_manage_memory_scope_lifecycle"
    assert not active_restore.allowed
    assert active_restore.reason == "memory_scope_already_active"
    assert not archived_archive.allowed
    assert archived_archive.reason == "memory_scope_already_archived"
    assert not deleted_restore.allowed
    assert deleted_restore.reason == "memory_scope_deleted"


def test_scope_snapshot_transfer_archive_and_restore_preserve_identity() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    archived_at = datetime(2026, 1, 2, tzinfo=UTC)
    restored_at = datetime(2026, 1, 3, tzinfo=UTC)
    identity = domain.MemoryScopeIdentity(
        space_id="space-1",
        memory_scope_id="scope-1",
    )
    original = domain.MemoryScopeSnapshot(
        identity=identity,
        name="Default",
        owner=domain.MemoryScopeOwner(principal_id="owner-1"),
        external_ref="default",
    )
    transferred = original.transfer_ownership(
        domain.MemoryScopeOwner(principal_id="owner-2"),
        transferred_at=updated_at,
    )
    archived = transferred.archive(archived_at=archived_at)
    restored = archived.restore(restored_at=restored_at)

    assert (
        original.identity
        == transferred.identity
        == archived.identity
        == restored.identity
    )
    assert original.owner.principal_id == "owner-1"
    assert transferred.owner.principal_id == "owner-2"
    assert transferred.updated_at == updated_at
    assert transferred.is_active()
    assert archived.status == domain.MEMORY_SCOPE_STATUS_ARCHIVED
    assert archived.archived_at == archived_at
    assert not archived.is_active()
    assert archived.is_archived()
    assert restored.status == domain.MEMORY_SCOPE_STATUS_ACTIVE
    assert restored.archived_at is None
    assert restored.updated_at == restored_at
    assert restored.is_active()


def test_invalid_scope_lifecycle_transitions_fail_directly() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    active = domain.MemoryScopeSnapshot(
        identity=domain.MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        name="Default",
        owner=domain.MemoryScopeOwner(principal_id="owner-1"),
    )
    archived = active.archive()
    deleted = domain.MemoryScopeSnapshot(
        identity=domain.MemoryScopeIdentity(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        name="Default",
        owner=domain.MemoryScopeOwner(principal_id="owner-1"),
        status=domain.MEMORY_SCOPE_STATUS_DELETED,
    )

    for transition in (
        archived.archive,
        active.restore,
        deleted.archive,
        deleted.restore,
    ):
        try:
            transition()
        except domain.MemoryScopeLifecycleError:
            pass
        else:  # pragma: no cover - clearer assertion failure branch.
            raise AssertionError("invalid memory scope lifecycle transition should fail")


def test_memory_scopes_feature_has_no_legacy_or_runtime_dependencies() -> None:
    violations: list[str] = []

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        if "tests" in path.relative_to(FEATURE_ROOT).parts:
            continue
        for imported in _imports(path):
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


def _assert_frozen(value: object, field_name: str, replacement: object) -> None:
    try:
        setattr(value, field_name, replacement)
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - this branch is only for a clearer assertion failure.
        raise AssertionError(f"{type(value).__name__} should be immutable")


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
