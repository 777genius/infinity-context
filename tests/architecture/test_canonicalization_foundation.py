"""Foundation guards: exact execution debt, never a count of hybrid imports.

The inventory is deliberately reviewable and must shrink explicitly as owners
migrate. Existing isolation/public seam/size tests remain the authoritative gates
for their respective policies; this module only fills the ownership gaps.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from canonicalization_ast import (
    SERVER,
    canonicalization_routes,
    compatibility_imports,
    container_overlaps,
    dormant_edges,
    index_repository,
    legacy_execution_edges,
    load_trees,
    require_inventory,
    route_edges,
)
from canonicalization_inventory import CONTAINER_OVERLAPS, ROUTE_OWNER_TYPES, ROUTE_OWNERS


@pytest.fixture(scope="module")
def ownership_index():
    return index_repository()


def test_route_executing_owners_require_explicit_inventory_removal(ownership_index) -> None:
    index = ownership_index
    paths = canonicalization_routes()
    composition = index.paths[f"{SERVER}.composition"]
    load_trees(index, [*paths, composition])
    fields = index.fields(composition, "Container")
    actual = {
        (caller.removeprefix(f"{SERVER}."), owner)
        for caller, owner in route_edges(index, paths, fields)
    }
    require_inventory(actual, ROUTE_OWNERS)
    used_fields = {owner.split(".")[0] for _, owner in actual}
    require_inventory({(name, fields[name]) for name in used_fields}, ROUTE_OWNER_TYPES)
    # No direct legacy class invocation in routes; Container owns construction.
    require_inventory(legacy_execution_edges(index, paths), set())


def test_exact_eight_container_overlaps(ownership_index) -> None:
    index = ownership_index
    composition = index.paths[f"{SERVER}.composition"]
    load_trees(index, [composition])
    require_inventory(
        container_overlaps(index.fields(composition, "Container")), CONTAINER_OVERLAPS
    )


def test_no_production_placeholder_construction_or_injection(ownership_index) -> None:
    index = ownership_index
    violations = set()
    # Streaming keeps memory bounded and covers production outside the API too.
    for path in index.paths.values():
        load_trees(index, [path])
        violations.update(dormant_edges(index, [path]))
    assert not violations, sorted(violations)


def test_locator_compatibility_imports_are_not_duplicate_owners(ownership_index) -> None:
    index = ownership_index
    path = index.paths[f"{SERVER}.api.v1.context_retrieval"]
    load_trees(index, [path])
    assert compatibility_imports(index, path)
    assert not legacy_execution_edges(index, [path])
    assert (
        "api.v1.context_retrieval.retrieve_context",
        "locator_retrieval.execute",
    ) in ROUTE_OWNERS


def test_existing_exception_inventory_cannot_expand() -> None:
    from canonicalization_inventory import FROZEN_INTERNAL_IMPORTS  # noqa: PLC0415
    from feature_owned_vertical_slice_config import (  # noqa: PLC0415
        NON_VERTICAL_SLICE_SUPPORT_COMPONENTS_BY_ROOT,
        TRANSITIONAL_CORE_FEATURE_INTERNAL_IMPORTS,
    )

    require_inventory(set(TRANSITIONAL_CORE_FEATURE_INTERNAL_IMPORTS), FROZEN_INTERNAL_IMPORTS)
    assert {
        "packages/infinity_context_core/infinity_context_core/features": frozenset(
            {"projection_receipts"}
        ),
    } == NON_VERTICAL_SLICE_SUPPORT_COMPONENTS_BY_ROOT


def test_foundation_files_are_strictly_below_1000_lines() -> None:
    for path in Path(__file__).parent.glob("*canonicalization*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) < 1000, path
        ast.parse(path.read_text(encoding="utf-8"))


def test_scope_transfer_process_owners_remain_explicit(ownership_index) -> None:
    index = ownership_index
    path = index.paths[f"{SERVER}.api.v1.export"]
    load_trees(index, [path])
    actual = {
        (caller.rsplit(".", 1)[-1], target.rsplit(".", 1)[-1])
        for caller, target, _ in index.calls(path)
        if target.startswith(f"{SERVER}.memory_scope_transfer.")
    }
    require_inventory(
        actual,
        {
            ("export_memory_scope_snapshot", "export_memory_scope_payload"),
            ("import_memory_scope_snapshot", "import_memory_scope_payload"),
            ("preview_memory_scope_snapshot_import", "import_memory_scope_payload"),
        },
    )


def test_digest_indirect_legacy_context_owner_is_explicit(ownership_index) -> None:
    index = ownership_index
    composition = index.paths[f"{SERVER}.composition"]
    digest = index.paths["infinity_context_core.application.use_cases.build_memory_digest"]
    load_trees(index, [composition, digest])
    dependencies = {
        (target.rsplit(".", 1)[-1], arg.rsplit(".", 1)[-1])
        for _, target, args in index.calls(composition)
        if target.endswith(".BuildMemoryDigestUseCase")
        for arg in args
        if arg.endswith("UseCase")
    }
    require_inventory(dependencies, {("BuildMemoryDigestUseCase", "BuildContextUseCase")})
    assert any(target == "self._context_builder.execute" for _, target, _ in index.calls(digest)), (
        "Remove migrated digest inventory explicitly"
    )
