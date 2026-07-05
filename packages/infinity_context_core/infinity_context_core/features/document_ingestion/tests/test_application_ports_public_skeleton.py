"""Feature-local checks for document_ingestion application, ports and public API."""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path


APPLICATION_MODULE = "infinity_context_core.features.document_ingestion.application"
DOMAIN_MODULE = "infinity_context_core.features.document_ingestion.domain"
PORTS_MODULE = "infinity_context_core.features.document_ingestion.ports"
PUBLIC_MODULE = "infinity_context_core.features.document_ingestion.public"
FEATURE_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = FEATURE_ROOT.parents[3]
ALLOWED_CORE_PREFIXES = (
    "infinity_context_core.features.document_ingestion.application",
    "infinity_context_core.features.document_ingestion.domain",
    "infinity_context_core.features.document_ingestion.ports",
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


def test_ingestion_application_contracts_are_frozen_dataclasses() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")
    origin = domain.SourceDocumentOrigin(source_type="upload", source_external_id="doc.txt")
    command = application.IngestDocumentCommand(
        scope=scope,
        title="Document",
        origin=origin,
        text="Document text",
        idempotency_key="ingest-1",
    )
    draft = domain.SourceDocumentDraft.create(
        scope=scope,
        title="Document",
        origin=origin,
        text="Document text",
    )
    chunk_draft = domain.ChunkingPolicy().plan_chunks(draft.content.text)[0]
    prepared = application.PreparedDocumentIngestion(
        document=draft,
        chunks=(chunk_draft,),
        chunking_policy_version=domain.CHUNKING_POLICY_VERSION,
        idempotency_key="ingest-1",
    )
    document = domain.SourceDocument.from_draft(document_id="doc-1", draft=draft)
    chunk = domain.DocumentChunk.from_draft(
        chunk_id="chunk-1",
        document_id="doc-1",
        scope=scope,
        draft=chunk_draft,
    )
    result = application.IngestDocumentResult(document=document, chunks=(chunk,))

    shapes = (
        (
            application.IngestDocumentCommand,
            command,
            (
                "scope",
                "title",
                "origin",
                "text",
                "classification",
                "chunking_policy",
                "idempotency_key",
            ),
        ),
        (
            application.PreparedDocumentIngestion,
            prepared,
            (
                "document",
                "chunks",
                "chunking_policy_version",
                "idempotency_key",
                "warnings",
            ),
        ),
        (
            application.IngestDocumentResult,
            result,
            (
                "document",
                "chunks",
                "duplicate_chunk_count",
                "indexing_status",
                "warnings",
            ),
        ),
    )

    for shape, value, expected_fields in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        assert tuple(field.name for field in fields(shape)) == expected_fields
        _assert_frozen(value)


def test_prepare_document_ingestion_handler_builds_draft_and_chunks() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    handler = application.PrepareDocumentIngestionHandler(
        domain.ChunkingPolicy(target_chars=80, overlap_chars=10, min_chars=20)
    )
    command = application.IngestDocumentCommand(
        scope=domain.DocumentIngestionScope(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        title="Planning note",
        origin=domain.SourceDocumentOrigin(
            source_type="markdown",
            source_external_id="planning.md",
        ),
        text="Paragraph one has details.\n\nParagraph two has enough extra details.",
        idempotency_key="plan-1",
    )

    prepared = asyncio.run(handler.execute(command))

    assert prepared.document.title == "Planning note"
    assert prepared.document.content.content_hash == domain.content_hash_for_text(command.text)
    assert prepared.chunks
    assert prepared.chunking_policy_version == domain.CHUNKING_POLICY_VERSION
    assert prepared.idempotency_key == "plan-1"


def test_document_ingestion_ports_are_protocol_boundaries() -> None:
    ports = importlib.import_module(PORTS_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    protocol_names = (
        "SourceDocumentRepositoryPort",
        "DocumentChunkRepositoryPort",
        "DocumentChunkIndexPort",
    )
    for name in protocol_names:
        assert getattr(getattr(ports, name), "_is_protocol", False)

    for method_name in ("create", "get", "find_active_by_content_hash"):
        assert inspect.iscoroutinefunction(
            getattr(ports.SourceDocumentRepositoryPort, method_name)
        )
    for method_name in ("upsert", "list_for_document"):
        assert inspect.iscoroutinefunction(
            getattr(ports.DocumentChunkRepositoryPort, method_name)
        )
    for method_name in ("upsert_chunks", "delete_chunks"):
        assert inspect.iscoroutinefunction(getattr(ports.DocumentChunkIndexPort, method_name))

    scope = domain.DocumentIngestionScope(space_id="space-1", memory_scope_id="scope-1")
    origin = domain.SourceDocumentOrigin(source_type="upload", source_external_id="doc.txt")
    item = ports.DocumentChunkIndexItem(
        chunk_id="chunk-1",
        document_id="doc-1",
        scope=scope,
        origin=origin,
        text="Chunk text",
        content_hash=domain.content_hash_for_text("Chunk text"),
        sequence=0,
    )
    result = ports.DocumentIndexingResult(accepted_chunk_ids=("chunk-1",))

    assert is_dataclass(ports.DocumentChunkIndexItem)
    assert is_dataclass(ports.DocumentIndexingResult)
    assert not hasattr(item, "__dict__")
    assert not hasattr(result, "__dict__")
    _assert_frozen(item)
    _assert_frozen(result)


def test_document_ingestion_public_api_exports_application_domain_and_ports() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)
    ports = importlib.import_module(PORTS_MODULE)
    public = importlib.import_module(PUBLIC_MODULE)

    expected_exports = {
        "CHUNKING_POLICY_VERSION": domain,
        "ChunkingPolicy": domain,
        "DocumentChunk": domain,
        "DocumentChunkDraft": domain,
        "DocumentChunkIdentity": domain,
        "DocumentChunkIndexItem": ports,
        "DocumentChunkIndexPort": ports,
        "DocumentChunkKind": domain,
        "DocumentChunkRepositoryPort": ports,
        "DocumentChunkStatus": domain,
        "DocumentChunkUpsertResult": ports,
        "DocumentIndexingResult": ports,
        "DocumentIndexingStatus": application,
        "DocumentIngestionError": domain,
        "DocumentIngestionFeature": domain,
        "DocumentIngestionIdentityFactory": application,
        "DocumentIngestionInvariantError": domain,
        "DocumentIngestionScope": domain,
        "DocumentIngestionUseCases": application,
        "DocumentIngestionValidationError": domain,
        "DocumentTextRange": domain,
        "FEATURE_ID": domain,
        "IngestDocumentCommand": application,
        "IngestDocumentHandler": application,
        "IngestDocumentResult": application,
        "IngestDocumentUseCase": application,
        "PreparedDocumentIngestion": application,
        "PrepareDocumentIngestionHandler": application,
        "PrepareDocumentIngestionUseCase": application,
        "SourceDocument": domain,
        "SourceDocumentClassification": domain,
        "SourceDocumentContent": domain,
        "SourceDocumentDraft": domain,
        "SourceDocumentIdentity": domain,
        "SourceDocumentOrigin": domain,
        "SourceDocumentRepositoryPort": ports,
        "SourceDocumentStatus": domain,
        "StableDocumentIngestionIdentityFactory": application,
        "content_hash_for_text": domain,
        "estimate_token_count": domain,
        "normalize_document_text": domain,
    }

    assert public.__all__ == tuple(expected_exports)
    for name, module in expected_exports.items():
        assert getattr(public, name) is getattr(module, name)


def test_feature_capsule_imports_only_feature_owned_core() -> None:
    paths = [
        *sorted((FEATURE_ROOT / "application").rglob("*.py")),
        *sorted((FEATURE_ROOT / "domain").rglob("*.py")),
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
    else:  # pragma: no cover - clearer assertion failure only.
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
