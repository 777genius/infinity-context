"""Static checks for feature-owned vertical slice boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_FEATURE_ROOT = (
    REPO_ROOT / "packages" / "infinity_context_core" / "infinity_context_core" / "features"
)
CONTRACT_FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
)
CORE_FEATURE_LAYERS = ("domain", "application", "ports")

FEATURE_IDS = frozenset(
    {
        "memory_facts",
        "context_building",
        "document_ingestion",
        "memory_scopes",
    }
)

FEATURE_ROOTS = (
    "packages/infinity_context_core/infinity_context_core/features",
    "packages/infinity_context_contracts/infinity_context_contracts/features",
    "packages/infinity_context_adapters/infinity_context_adapters/features",
    "packages/infinity_context_server/infinity_context_server/features",
)

ADR_PATH = REPO_ROOT / "docs" / "adr" / "ADR-0007-feature-owned-vertical-slices.md"

CONTRACT_FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "graphiti",
    "infinity_context_adapters",
    "infinity_context_core",
    "infinity_context_server",
    "openai",
    "pydantic",
    "qdrant_client",
    "sqlalchemy",
)


def _feature_dirs(root: str) -> list[Path]:
    path = REPO_ROOT / root
    if not path.exists():
        return []
    return sorted(child for child in path.iterdir() if child.is_dir() and not child.name.startswith("_"))


def _feature_modules(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        child
        for child in root.glob("*.py")
        if child.stem != "__init__" and not child.name.startswith("_")
    )


def _python_modules(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def _package_context(path: Path) -> str | None:
    try:
        relative = path.relative_to(REPO_ROOT / "packages")
    except ValueError:
        return None

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


def _imports_from_tree(path: Path, tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported = _resolve_import_from(path, node)
            if imported is not None:
                imports.append(imported)
    return imports


def _imports_from_source(path: Path, source: str) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    return _imports_from_tree(path, tree)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _imports_from_tree(path, tree)


def _matches_module_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)


def _is_cross_feature_internal_import(current_feature: str, imported: str) -> bool:
    prefix = "infinity_context_core.features."
    if not imported.startswith(prefix):
        return False

    imported_parts = imported.removeprefix(prefix).split(".")
    if not imported_parts:
        return False

    imported_feature = imported_parts[0]
    imports_internal = len(imported_parts) > 1 and imported_parts[1] != "public"
    return imported_feature != current_feature and imports_internal


def _is_allowed_core_feature_import(feature_id: str, path: Path, imported: str) -> bool:
    if not imported.startswith("infinity_context_core."):
        return True

    relative_parts = path.relative_to(CORE_FEATURE_ROOT / feature_id).parts
    own_feature = f"infinity_context_core.features.{feature_id}"
    shared_kernel = "infinity_context_core.shared_kernel"

    if _matches_module_prefix(imported, (shared_kernel,)):
        return True

    if relative_parts[0] == "public.py":
        return imported in {
            f"{own_feature}.application",
            f"{own_feature}.domain",
            f"{own_feature}.ports",
        }

    layer = relative_parts[0]
    if layer == "domain":
        return _matches_module_prefix(imported, (f"{own_feature}.domain",))
    if layer == "application":
        return _matches_module_prefix(
            imported,
            (
                f"{own_feature}.application",
                f"{own_feature}.domain",
                f"{own_feature}.ports",
            ),
        )
    if layer == "ports":
        return _matches_module_prefix(
            imported,
            (
                f"{own_feature}.domain",
                f"{own_feature}.ports",
            ),
        )
    if layer == "tests":
        return _matches_module_prefix(imported, (own_feature,))

    return False


def test_feature_owned_architecture_decision_is_documented() -> None:
    adr = ADR_PATH.read_text(encoding="utf-8")

    for feature_id in FEATURE_IDS:
        assert feature_id in adr
    assert "domain/application/ports" in adr
    assert "not Feature-Sliced Design" in adr


def test_feature_directories_use_known_feature_ids() -> None:
    unexpected: list[str] = []
    for root in FEATURE_ROOTS:
        for path in _feature_dirs(root):
            if path.name not in FEATURE_IDS:
                unexpected.append(str(path.relative_to(REPO_ROOT)))

    assert unexpected == []


def test_contract_feature_modules_use_known_feature_ids() -> None:
    unexpected: list[str] = []
    for path in _feature_modules(CONTRACT_FEATURE_ROOT):
        if path.stem not in FEATURE_IDS:
            unexpected.append(str(path.relative_to(REPO_ROOT)))

    assert unexpected == []


def test_contract_feature_modules_stay_at_boundary() -> None:
    path = CONTRACT_FEATURE_ROOT / "memory_facts.py"

    assert path.is_file()

    violations: list[str] = []
    for module_path in _python_modules(CONTRACT_FEATURE_ROOT):
        for imported in _imports(module_path):
            if _matches_module_prefix(imported, CONTRACT_FORBIDDEN_IMPORT_PREFIXES):
                rel = module_path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_core_feature_capsules_expose_public_api_when_created() -> None:
    missing_public_api: list[str] = []
    for path in _feature_dirs("packages/infinity_context_core/infinity_context_core/features"):
        if not (path / "public.py").exists():
            missing_public_api.append(str(path.relative_to(REPO_ROOT)))

    assert missing_public_api == []


def test_memory_facts_core_capsule_has_clean_architecture_shape() -> None:
    feature_dir = CORE_FEATURE_ROOT / "memory_facts"

    assert (feature_dir / "public.py").is_file()
    for layer in CORE_FEATURE_LAYERS:
        assert (feature_dir / layer / "__init__.py").is_file()


def test_memory_facts_public_api_is_importable_and_narrow() -> None:
    from infinity_context_core.features.memory_facts import public  # noqa: PLC0415

    assert public.FEATURE_ID == "memory_facts"
    assert public.MemoryFactsFeature().feature_id == "memory_facts"
    assert public.__all__ == (
        "FEATURE_ID",
        "ForgetFactCommand",
        "ForgetFactHandler",
        "ForgetFactResult",
        "ForgetFactUseCase",
        "MemoryFactClassification",
        "MemoryFactClockPort",
        "MemoryFactConfidence",
        "MemoryFactEvidenceRef",
        "MemoryFactIdPort",
        "MemoryFactIdentity",
        "MemoryFactKind",
        "MemoryFactLifecycleUseCases",
        "MemoryFactOutboxMessage",
        "MemoryFactOutboxPort",
        "MemoryFactRepositoryPort",
        "MemoryFactScope",
        "MemoryFactSnapshot",
        "MemoryFactSourceRef",
        "MemoryFactStatus",
        "MemoryFactTrustLevel",
        "MemoryFactUnitOfWorkFactoryPort",
        "MemoryFactUnitOfWorkPort",
        "MemoryFactVisibility",
        "MemoryFactsFeature",
        "RememberFactCommand",
        "RememberFactHandler",
        "RememberFactResult",
        "RememberFactUseCase",
        "UpdateFactCommand",
        "UpdateFactHandler",
        "UpdateFactResult",
        "UpdateFactUseCase",
    )


def test_document_ingestion_public_api_is_importable_and_narrow() -> None:
    from infinity_context_core.features.document_ingestion import public  # noqa: PLC0415

    assert public.FEATURE_ID == "document_ingestion"
    assert public.DocumentIngestionFeature().feature_id == "document_ingestion"
    assert public.__all__ == (
        "CHUNKING_POLICY_VERSION",
        "ChunkingPolicy",
        "DocumentChunk",
        "DocumentChunkDraft",
        "DocumentChunkIdentity",
        "DocumentChunkIndexItem",
        "DocumentChunkIndexPort",
        "DocumentChunkKind",
        "DocumentChunkRepositoryPort",
        "DocumentChunkStatus",
        "DocumentChunkUpsertResult",
        "DocumentIndexingResult",
        "DocumentIndexingStatus",
        "DocumentIngestionError",
        "DocumentIngestionFeature",
        "DocumentIngestionIdentityFactory",
        "DocumentIngestionInvariantError",
        "DocumentIngestionScope",
        "DocumentIngestionUseCases",
        "DocumentIngestionValidationError",
        "DocumentTextRange",
        "FEATURE_ID",
        "IngestDocumentCommand",
        "IngestDocumentHandler",
        "IngestDocumentResult",
        "IngestDocumentUseCase",
        "PreparedDocumentIngestion",
        "PrepareDocumentIngestionHandler",
        "PrepareDocumentIngestionUseCase",
        "SourceDocument",
        "SourceDocumentClassification",
        "SourceDocumentContent",
        "SourceDocumentDraft",
        "SourceDocumentIdentity",
        "SourceDocumentOrigin",
        "SourceDocumentRepositoryPort",
        "SourceDocumentStatus",
        "StableDocumentIngestionIdentityFactory",
        "content_hash_for_text",
        "estimate_token_count",
        "normalize_document_text",
    )


def test_core_feature_public_api_imports_feature_layer_boundaries_only() -> None:
    path = CORE_FEATURE_ROOT / "document_ingestion" / "public.py"
    layer_imports = _imports_from_source(
        path,
        "from .application import IngestDocumentHandler\n"
        "from .domain import SourceDocument\n"
        "from .ports import SourceDocumentRepositoryPort\n",
    )
    internal_imports = _imports_from_source(
        path,
        "from .application.use_cases import IngestDocumentHandler\n"
        "from .domain.source_document import SourceDocument\n"
        "from .ports.repositories import SourceDocumentRepositoryPort\n",
    )
    legacy_imports = _imports_from_source(
        path,
        "from ...application.use_cases import IngestDocumentHandler\n",
    )

    assert all(
        _is_allowed_core_feature_import("document_ingestion", path, imported)
        for imported in layer_imports
    )
    assert not any(
        _is_allowed_core_feature_import("document_ingestion", path, imported)
        for imported in internal_imports + legacy_imports
    )


def test_relative_core_feature_import_resolves_to_legacy_layer_first_core() -> None:
    path = CORE_FEATURE_ROOT / "memory_facts" / "application" / "use_case.py"
    imports = _imports_from_source(path, "from ....domain.entities import MemoryFact\n")

    assert "infinity_context_core.domain.entities" in imports
    assert not _is_allowed_core_feature_import("memory_facts", path, imports[0])


def test_relative_core_feature_import_resolves_to_cross_feature_internal() -> None:
    path = CORE_FEATURE_ROOT / "memory_facts" / "application" / "use_case.py"
    imports = _imports_from_source(path, "from ...context_building.domain import Context\n")

    assert "infinity_context_core.features.context_building.domain" in imports
    assert _is_cross_feature_internal_import("memory_facts", imports[0])


def test_core_features_do_not_import_other_feature_internals() -> None:
    feature_root = CORE_FEATURE_ROOT
    if not feature_root.exists():
        return

    violations: list[str] = []
    for feature_dir in _feature_dirs(str(feature_root.relative_to(REPO_ROOT))):
        current_feature = feature_dir.name
        for path in feature_dir.rglob("*.py"):
            for imported in _imports(path):
                if _is_cross_feature_internal_import(current_feature, imported):
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_core_feature_capsule_layers_do_not_import_legacy_layer_first_core() -> None:
    if not CORE_FEATURE_ROOT.exists():
        return

    violations: list[str] = []
    for feature_dir in _feature_dirs(str(CORE_FEATURE_ROOT.relative_to(REPO_ROOT))):
        for path in feature_dir.rglob("*.py"):
            for imported in _imports(path):
                if _is_allowed_core_feature_import(feature_dir.name, path, imported):
                    continue
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported}")

    assert violations == []
