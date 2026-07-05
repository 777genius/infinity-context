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
SERVER_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
)
SERVER_API_ROOT = SERVER_ROOT / "api"
SERVER_FEATURE_ROOT = SERVER_ROOT / "features"
SERVER_OUTBOX_WORKER_PATH = SERVER_ROOT / "worker.py"
SERVER_PROCESS_ROOT = SERVER_ROOT / "processes"

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

OUTBOX_WORKFLOW_DEFINITION_NAMES = frozenset(
    {
        "ExtractionOutboxProcess",
        "OutboxEventDispatcher",
        "OutboxEventHandler",
        "OutboxHandlerRegistry",
        "ProjectionOutboxProcess",
        "build_outbox_event_dispatcher",
        "merge_outbox_handlers",
    }
)
OUTBOX_WORKFLOW_HANDLER_NAMES = frozenset(
    {
        "handle_asset_extract",
        "handle_capture_consolidate",
        "handle_cognee_document_forget",
        "handle_cognee_document_ingest",
        "handle_graph_delete",
        "handle_graph_upsert",
        "handle_vector_delete_chunks",
        "handle_vector_upsert",
    }
)


def _feature_dirs(root: str) -> list[Path]:
    path = REPO_ROOT / root
    if not path.exists():
        return []
    return sorted(
        child
        for child in path.iterdir()
        if child.is_dir() and not child.name.startswith("_")
    )


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


def _server_route_modules() -> list[Path]:
    paths = [
        *list((SERVER_API_ROOT / "v1").glob("*.py")),
        *list(SERVER_FEATURE_ROOT.glob("*/routes.py")),
    ]
    legacy_client = SERVER_API_ROOT / "legacy_client.py"
    if legacy_client.exists():
        paths.append(legacy_client)
    return sorted(path for path in paths if path.is_file())


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


def _is_core_feature_package_root(imported: str) -> bool:
    prefix = "infinity_context_core.features."
    if not imported.startswith(prefix):
        return False

    imported_parts = imported.removeprefix(prefix).split(".")
    return len(imported_parts) == 1 and imported_parts[0] in FEATURE_IDS


def _import_targets_from_tree(path: Path, tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported = _resolve_import_from(path, node)
            if imported is None:
                continue
            if _is_core_feature_package_root(imported):
                imports.extend(f"{imported}.{alias.name}" for alias in node.names)
            else:
                imports.append(imported)
    return imports


def _import_targets_from_source(path: Path, source: str) -> list[str]:
    tree = ast.parse(source, filename=str(path))
    return _import_targets_from_tree(path, tree)


def _import_targets(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _import_targets_from_tree(path, tree)


def _matches_module_prefix(imported: str, prefixes: tuple[str, ...]) -> bool:
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)


def _is_server_route_import(imported: str) -> bool:
    if _matches_module_prefix(imported, ("infinity_context_server.api",)):
        return True

    feature_route_prefix = "infinity_context_server.features."
    if not imported.startswith(feature_route_prefix):
        return False

    imported_parts = imported.removeprefix(feature_route_prefix).split(".")
    return len(imported_parts) >= 2 and imported_parts[1] == "routes"


def _outbox_workflow_definition_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if (
            node.name in OUTBOX_WORKFLOW_DEFINITION_NAMES
            or node.name in OUTBOX_WORKFLOW_HANDLER_NAMES
        ):
            names.append(node.name)
    return names


def _is_cross_feature_internal_import(current_feature: str, imported: str) -> bool:
    prefix = "infinity_context_core.features."
    if not imported.startswith(prefix):
        return False

    imported_parts = imported.removeprefix(prefix).split(".")
    if not imported_parts:
        return False

    imported_feature = imported_parts[0]
    imports_public_api = len(imported_parts) > 1 and imported_parts[1] == "public"
    return imported_feature != current_feature and not imports_public_api


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


def test_memory_scope_lifecycle_contracts_use_feature_identity_fields() -> None:
    from dataclasses import fields  # noqa: PLC0415

    from infinity_context_contracts.features.memory_scopes import (  # noqa: PLC0415
        ArchiveMemoryScopeRequestDto,
        RestoreMemoryScopeRequestDto,
    )

    for dto_type in (ArchiveMemoryScopeRequestDto, RestoreMemoryScopeRequestDto):
        field_names = {field.name for field in fields(dto_type)}

        assert {"space_id", "memory_scope_id"} <= field_names
        assert "scope_id" not in field_names


def test_memory_scope_contracts_do_not_import_core_lifecycle_internals() -> None:
    path = CONTRACT_FEATURE_ROOT / "memory_scopes.py"

    assert path.is_file()
    assert not any(
        _matches_module_prefix(imported, ("infinity_context_core",))
        for imported in _imports(path)
    )


def test_sdk_and_mcp_contract_payload_boundaries_do_not_import_core() -> None:
    checked_paths = (
        REPO_ROOT / "packages/infinity_context_sdk/infinity_context_sdk/__init__.py",
        REPO_ROOT / "packages/infinity_context_sdk/infinity_context_sdk/_payloads.py",
        REPO_ROOT / "packages/infinity_context_sdk/infinity_context_sdk/context.py",
        REPO_ROOT / "packages/infinity_context_sdk/infinity_context_sdk/scopes.py",
        REPO_ROOT
        / "packages/infinity_context_mcp/infinity_context_mcp/adapters/http_gateway.py",
        REPO_ROOT / "packages/infinity_context_mcp/infinity_context_mcp/domain/models.py",
    )

    violations: list[str] = []
    for path in checked_paths:
        for imported in _imports(path):
            if _matches_module_prefix(imported, ("infinity_context_core",)):
                violations.append(f"{path.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


def test_sdk_and_mcp_payload_helpers_depend_on_feature_public_contracts() -> None:
    sdk_imports = set(
        _imports(REPO_ROOT / "packages/infinity_context_sdk/infinity_context_sdk/_payloads.py")
    )
    mcp_imports = set(
        _imports(
            REPO_ROOT
            / "packages/infinity_context_mcp/infinity_context_mcp/adapters/http_gateway.py"
        )
    )

    expected = {
        "infinity_context_contracts.features.document_ingestion",
        "infinity_context_contracts.features.memory_facts",
    }
    assert expected <= sdk_imports
    assert expected <= mcp_imports
    assert "infinity_context_contracts.features.memory_scopes" in sdk_imports


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


def test_legacy_core_surfaces_expose_feature_public_api_namespaces() -> None:
    import infinity_context_core as core  # noqa: PLC0415
    import infinity_context_core.application as application  # noqa: PLC0415
    import infinity_context_core.features.context_building.public as context_building_public  # noqa: PLC0415,E501
    import infinity_context_core.features.document_ingestion.public as document_ingestion_public  # noqa: PLC0415,E501
    import infinity_context_core.features.memory_facts.public as memory_facts_public  # noqa: PLC0415,E501
    import infinity_context_core.features.memory_scopes.public as memory_scopes_public  # noqa: PLC0415,E501

    shim_cases = (
        (
            "context_building_public",
            context_building_public,
            "ContextBuildingUseCases",
            ("BuildContextQuery", "BuildContextUseCase"),
        ),
        (
            "document_ingestion_public",
            document_ingestion_public,
            "DocumentIngestionUseCases",
            ("IngestDocumentCommand", "IngestDocumentUseCase"),
        ),
        (
            "memory_facts_public",
            memory_facts_public,
            "MemoryFactLifecycleUseCases",
            ("RememberFactCommand", "RememberFactUseCase"),
        ),
        (
            "memory_scopes_public",
            memory_scopes_public,
            "MemoryScopeUseCases",
            ("CreateMemoryScopeCommand", "CreateMemoryScopeUseCase"),
        ),
    )

    for surface in (core, application):
        exported = set(surface.__all__)
        for namespace_name, public_module, use_case_bundle_name, public_names in shim_cases:
            namespace = getattr(surface, namespace_name)

            assert namespace is public_module
            assert namespace_name in exported
            assert getattr(surface, use_case_bundle_name) is getattr(
                public_module,
                use_case_bundle_name,
            )
            assert use_case_bundle_name in exported
            for public_name in public_names:
                assert getattr(namespace, public_name) is getattr(public_module, public_name)


def test_legacy_core_feature_public_shims_do_not_import_feature_internals() -> None:
    shim_surfaces = (
        REPO_ROOT / "packages/infinity_context_core/infinity_context_core/__init__.py",
        REPO_ROOT / "packages/infinity_context_core/infinity_context_core/application/__init__.py",
    )

    violations: list[str] = []
    for path in shim_surfaces:
        for imported in _imports(path):
            prefix = "infinity_context_core.features."
            if not imported.startswith(prefix):
                continue
            feature_parts = imported.removeprefix(prefix).split(".")
            if len(feature_parts) != 2 or feature_parts[1] != "public":
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_outbox_worker_event_dispatch_is_owned_by_server_process_boundary() -> None:
    worker_source = SERVER_OUTBOX_WORKER_PATH.read_text(encoding="utf-8")
    process_paths = sorted(SERVER_PROCESS_ROOT.glob("*.py"))
    process_sources = {
        path.name: path.read_text(encoding="utf-8") for path in process_paths
    }
    process_imports = {
        imported
        for path in process_paths
        for imported in _imports(path)
    }

    assert "build_outbox_event_dispatcher" in worker_source
    assert "document_chunk_retrieval_text" not in worker_source
    assert "ConsolidateCaptureCommand" not in worker_source
    assert "RunAssetExtractionCommand" not in worker_source

    for event_type in (
        "vector.upsert_chunk",
        "vector.upsert_chunks",
        "vector.delete_chunks",
        "graph.upsert_fact",
        "graph.delete_fact",
        "cognee.ingest_document",
        "cognee.forget_document",
        "capture.consolidate",
        "asset.extract",
    ):
        assert event_type not in worker_source
        assert event_type in "".join(process_sources.values())

    assert not any(
        _matches_module_prefix(imported, ("fastapi", "infinity_context_server.api"))
        for imported in process_imports
    )


def test_outbox_workflow_code_stays_under_server_processes() -> None:
    violations: list[str] = []
    for path in _python_modules(SERVER_ROOT):
        if path.is_relative_to(SERVER_PROCESS_ROOT):
            continue
        for name in _outbox_workflow_definition_names(path):
            rel = path.relative_to(REPO_ROOT)
            violations.append(f"{rel}: defines {name}")

    assert violations == []


def test_server_processes_do_not_import_fastapi_or_routes() -> None:
    violations: list[str] = []
    for path in _python_modules(SERVER_PROCESS_ROOT):
        for imported in _imports(path):
            if not (
                _matches_module_prefix(imported, ("fastapi",))
                or _is_server_route_import(imported)
            ):
                continue
            rel = path.relative_to(REPO_ROOT)
            violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_route_modules_do_not_dispatch_outbox_event_workflows_directly() -> None:
    route_outbox_dispatch_imports = (
        "infinity_context_server.processes",
        "infinity_context_server.worker",
    )

    violations: list[str] = []
    for path in _server_route_modules():
        for imported in _imports(path):
            if _matches_module_prefix(imported, route_outbox_dispatch_imports):
                rel = path.relative_to(REPO_ROOT)
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


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


def test_relative_core_feature_public_import_resolves_to_public_module() -> None:
    path = CORE_FEATURE_ROOT / "memory_facts" / "application" / "use_case.py"
    imports = _import_targets_from_source(path, "from ...context_building import public\n")

    assert "infinity_context_core.features.context_building.public" in imports
    assert not _is_cross_feature_internal_import("memory_facts", imports[0])


def test_core_features_do_not_import_other_feature_internals() -> None:
    feature_root = CORE_FEATURE_ROOT
    if not feature_root.exists():
        return

    violations: list[str] = []
    for feature_dir in _feature_dirs(str(feature_root.relative_to(REPO_ROOT))):
        current_feature = feature_dir.name
        for path in feature_dir.rglob("*.py"):
            for imported in _import_targets(path):
                if _is_cross_feature_internal_import(current_feature, imported):
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}: imports {imported}")

    assert violations == []


def test_memory_facts_external_core_imports_use_public_api() -> None:
    memory_facts_feature_dir = CORE_FEATURE_ROOT / "memory_facts"
    memory_facts_prefix = "infinity_context_core.features.memory_facts"
    memory_facts_public = f"{memory_facts_prefix}.public"
    scan_roots = (
        REPO_ROOT / "packages",
        REPO_ROOT / "tests",
    )

    violations: list[str] = []
    for scan_root in scan_roots:
        for path in _python_modules(scan_root):
            if path.is_relative_to(memory_facts_feature_dir):
                continue
            for imported in _import_targets(path):
                if not _matches_module_prefix(imported, (memory_facts_prefix,)):
                    continue
                if _matches_module_prefix(imported, (memory_facts_public,)):
                    continue
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
