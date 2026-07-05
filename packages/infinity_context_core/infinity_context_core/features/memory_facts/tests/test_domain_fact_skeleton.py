"""Feature-local checks for the memory_facts domain skeleton."""

from __future__ import annotations

import ast
import importlib
from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path


DOMAIN_MODULE = "infinity_context_core.features.memory_facts.domain"
FACT_MODULE = f"{DOMAIN_MODULE}.fact"
FEATURE_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = FEATURE_ROOT.parents[3]
FORBIDDEN_IMPORT_PREFIXES = (
    "anthropic",
    "fast" + "api",
    "graph" + "iti",
    "graph" + "iti_core",
    "infinity_context_" + "adapters",
    "infinity_context_core." + "application",
    "infinity_context_core." + "domain",
    "infinity_context_core." + "ports",
    "infinity_context_" + "mcp",
    "infinity_context_" + "server",
    "open" + "ai",
    "qdrant" + "_client",
    "sql" + "alchemy",
)


def test_domain_fact_skeleton_is_imported_and_exported() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)
    fact = importlib.import_module(FACT_MODULE)

    expected_exports = {
        "MemoryFactClassification",
        "MemoryFactConfidence",
        "MemoryFactEvidenceRef",
        "MemoryFactIdentity",
        "MemoryFactKind",
        "MemoryFactScope",
        "MemoryFactSnapshot",
        "MemoryFactSourceRef",
        "MemoryFactStatus",
        "MemoryFactTrustLevel",
        "MemoryFactVisibility",
    }

    assert expected_exports <= set(domain.__all__)
    for export in expected_exports:
        assert getattr(domain, export) is getattr(fact, export)


def test_taxonomy_fields_are_flexible_strings_without_prescriptive_enums() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    assert domain.MemoryFactKind is str
    assert domain.MemoryFactStatus is str
    assert domain.MemoryFactConfidence is str
    assert domain.MemoryFactTrustLevel is str
    assert domain.MemoryFactClassification is str

    visibility = domain.MemoryFactVisibility(
        status="pending-review",
        version=0,
        confidence="extractor-score:0.73",
        trust_level="unverified-import",
        classification="tenant-private",
    )
    snapshot = domain.MemoryFactSnapshot(
        identity=domain.MemoryFactIdentity(
            fact_id="fact-1",
            scope=domain.MemoryFactScope(space_id="space-1", memory_scope_id="scope-1"),
        ),
        text="Fact text",
        source_refs=(),
        visibility=visibility,
        kind="project-specific-kind",
        category="",
        tags=("", "review"),
    )

    assert snapshot.visibility.status == "pending-review"
    assert snapshot.visibility.version == 0
    assert snapshot.kind == "project-specific-kind"
    assert snapshot.source_refs == ()
    assert snapshot.category == ""
    assert snapshot.tags == ("", "review")


def test_domain_shapes_are_frozen_slot_dataclasses() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.MemoryFactScope(space_id="space-1", memory_scope_id="scope-1")
    identity = domain.MemoryFactIdentity(fact_id="fact-1", scope=scope)
    source_ref = domain.MemoryFactSourceRef(
        source_type="document",
        source_id="doc-1",
        page_number=0,
        bbox=(10.0, 10.0, 5.0, 5.0),
    )
    evidence_ref = domain.MemoryFactEvidenceRef(source_ref=source_ref)
    visibility = domain.MemoryFactVisibility()
    shapes = (
        (domain.MemoryFactScope, scope, "space_id", "space-2"),
        (domain.MemoryFactIdentity, identity, "fact_id", "fact-2"),
        (domain.MemoryFactSourceRef, source_ref, "source_id", "doc-2"),
        (domain.MemoryFactEvidenceRef, evidence_ref, "evidence_id", "evidence-2"),
        (domain.MemoryFactVisibility, visibility, "status", "archived"),
        (
            domain.MemoryFactSnapshot,
            domain.MemoryFactSnapshot(
                identity=identity,
                text="Fact text",
                source_refs=(source_ref,),
                visibility=visibility,
                evidence_refs=(evidence_ref,),
            ),
            "text",
            "changed",
        ),
    )

    for shape, value, field_name, replacement in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        _assert_frozen(value, field_name, replacement)


def _assert_frozen(value: object, field_name: str, replacement: object) -> None:
    try:
        setattr(value, field_name, replacement)
    except FrozenInstanceError:
        pass
    else:  # pragma: no cover - this branch is only for a clearer assertion failure.
        raise AssertionError(f"{type(value).__name__} should be immutable")


def test_snapshot_keeps_source_and_evidence_refs() -> None:
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.MemoryFactScope(space_id="space-1", memory_scope_id="scope-1")
    source_ref = domain.MemoryFactSourceRef(source_type="document", source_id="doc-1")
    evidence_ref = domain.MemoryFactEvidenceRef(source_ref=source_ref)
    snapshot = domain.MemoryFactSnapshot(
        identity=domain.MemoryFactIdentity(fact_id="fact-1", scope=scope),
        text="Fact text",
        source_refs=(source_ref,),
        evidence_refs=(evidence_ref,),
    )

    assert snapshot.source_refs == (source_ref,)
    assert snapshot.evidence_refs == (evidence_ref,)


def test_memory_facts_feature_has_no_legacy_or_runtime_dependencies() -> None:
    violations: list[str] = []

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        if "tests" in path.relative_to(FEATURE_ROOT).parts:
            continue
        for imported in _imports(path):
            if _matches_forbidden_prefix(imported):
                violations.append(f"{path.relative_to(FEATURE_ROOT)}: imports {imported}")

    assert violations == []


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


def _matches_forbidden_prefix(imported: str) -> bool:
    return any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )
