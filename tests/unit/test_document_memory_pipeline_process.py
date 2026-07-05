"""Tests for the document memory pipeline process seam."""

from __future__ import annotations

import ast
import asyncio
import importlib
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

import infinity_context_core.features.context_building.public as context_building_public
import infinity_context_core.features.document_ingestion.public as document_ingestion_public
import infinity_context_core.features.memory_facts.public as memory_facts_public
import infinity_context_core.processes.document_memory_pipeline.public as pipeline_public


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESS_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_core"
    / "infinity_context_core"
    / "processes"
    / "document_memory_pipeline"
)
PACKAGES_ROOT = REPO_ROOT / "packages"

ALLOWED_FEATURE_PUBLIC_IMPORTS = (
    "infinity_context_core.features.context_building.public",
    "infinity_context_core.features.document_ingestion.public",
    "infinity_context_core.features.memory_facts.public",
)
ALLOWED_PROCESS_IMPORTS = (
    "infinity_context_core.processes.document_memory_pipeline",
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


def test_process_contracts_are_frozen_dataclasses_and_publicly_exported() -> None:
    contracts = importlib.import_module(
        "infinity_context_core.processes.document_memory_pipeline.contracts"
    )
    process = importlib.import_module(
        "infinity_context_core.processes.document_memory_pipeline.process"
    )

    ingest_command = _ingest_command()
    fact_command = _remember_fact_command("fact-command-1")
    build_context = _build_context_query()
    command = pipeline_public.DocumentMemoryPipelineCommand(
        ingest_document=ingest_command,
        remember_facts=(fact_command,),
        build_context=build_context,
        idempotency_key="pipeline-1",
    )
    result = pipeline_public.DocumentMemoryPipelineResult(
        document=_document_result(),
        remembered_facts=(_remember_fact_result("fact-1"),),
        context=_build_context_result(build_context),
    )
    use_cases = _pipeline_use_cases(document_result=result.document)

    shapes = (
        (
            pipeline_public.DocumentMemoryPipelineCommand,
            command,
            ("ingest_document", "remember_facts", "build_context", "idempotency_key"),
        ),
        (
            pipeline_public.DocumentMemoryPipelineResult,
            result,
            ("document", "remembered_facts", "context"),
        ),
        (
            pipeline_public.DocumentMemoryPipelineUseCases,
            use_cases,
            ("document_ingestion", "memory_facts", "context_building"),
        ),
    )

    for shape, value, expected_fields in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        assert tuple(field.name for field in fields(shape)) == expected_fields
        _assert_frozen(value)

    assert pipeline_public.DocumentMemoryPipelineCommand is contracts.DocumentMemoryPipelineCommand
    assert pipeline_public.DocumentMemoryPipelineResult is contracts.DocumentMemoryPipelineResult
    assert pipeline_public.DocumentMemoryPipelineUseCases is contracts.DocumentMemoryPipelineUseCases
    assert pipeline_public.DocumentMemoryPipelineProcess is process.DocumentMemoryPipelineProcess
    assert pipeline_public.__all__ == (
        "DocumentMemoryPipelineCommand",
        "DocumentMemoryPipelineProcess",
        "DocumentMemoryPipelineResult",
        "DocumentMemoryPipelineUseCase",
        "DocumentMemoryPipelineUseCases",
    )


def test_pipeline_process_orchestrates_feature_public_use_cases_in_order() -> None:
    document_result = _document_result()
    fact_result_1 = _remember_fact_result("fact-1")
    fact_result_2 = _remember_fact_result("fact-2")
    build_context = _build_context_query()
    context_result = _build_context_result(build_context)
    events: list[tuple[str, object]] = []

    process = pipeline_public.DocumentMemoryPipelineProcess(
        use_cases=_pipeline_use_cases(
            document_result=document_result,
            fact_results=(fact_result_1, fact_result_2),
            context_result=context_result,
            events=events,
        )
    )
    ingest_command = _ingest_command()
    fact_command_1 = _remember_fact_command("fact-command-1")
    fact_command_2 = _remember_fact_command("fact-command-2")
    command = pipeline_public.DocumentMemoryPipelineCommand(
        ingest_document=ingest_command,
        remember_facts=(fact_command_1, fact_command_2),
        build_context=build_context,
    )

    result = asyncio.run(process.execute(command))

    assert result == pipeline_public.DocumentMemoryPipelineResult(
        document=document_result,
        remembered_facts=(fact_result_1, fact_result_2),
        context=context_result,
    )
    assert events == [
        ("ingest_document", ingest_command),
        ("remember_fact", fact_command_1),
        ("remember_fact", fact_command_2),
        ("build_context", build_context),
    ]


def test_pipeline_can_run_ingestion_only_without_memory_or_context_apis() -> None:
    document_result = _document_result()
    events: list[tuple[str, object]] = []
    process = pipeline_public.DocumentMemoryPipelineProcess(
        use_cases=_pipeline_use_cases(document_result=document_result, events=events)
    )
    command = pipeline_public.DocumentMemoryPipelineCommand(
        ingest_document=_ingest_command(),
    )

    result = asyncio.run(process.execute(command))

    assert result.document == document_result
    assert result.remembered_facts == ()
    assert result.context is None
    assert [event[0] for event in events] == ["ingest_document"]


def test_pipeline_requires_optional_feature_apis_when_their_commands_are_present() -> None:
    events: list[tuple[str, object]] = []
    process = pipeline_public.DocumentMemoryPipelineProcess(
        use_cases=_pipeline_use_cases(document_result=_document_result(), events=events)
    )

    with _raises_value_error("memory_facts use cases are required"):
        asyncio.run(
            process.execute(
                pipeline_public.DocumentMemoryPipelineCommand(
                    ingest_document=_ingest_command(),
                    remember_facts=(_remember_fact_command("fact-command-1"),),
                )
            )
        )

    with _raises_value_error("context_building use cases are required"):
        asyncio.run(
            process.execute(
                pipeline_public.DocumentMemoryPipelineCommand(
                    ingest_document=_ingest_command(),
                    build_context=_build_context_query(),
                )
            )
        )

    assert events == []


def test_pipeline_process_imports_only_feature_public_apis() -> None:
    violations: list[str] = []

    for path in sorted(PROCESS_ROOT.rglob("*.py")):
        for imported in _imports(path):
            if _matches_prefix(imported, FORBIDDEN_IMPORT_PREFIXES):
                violations.append(f"{path.relative_to(REPO_ROOT)}: imports {imported}")
            if imported.startswith("infinity_context_core.features.") and not _matches_prefix(
                imported,
                ALLOWED_FEATURE_PUBLIC_IMPORTS,
            ):
                violations.append(f"{path.relative_to(REPO_ROOT)}: imports {imported}")
            if imported.startswith("infinity_context_core.") and not _matches_prefix(
                imported,
                (*ALLOWED_FEATURE_PUBLIC_IMPORTS, *ALLOWED_PROCESS_IMPORTS),
            ):
                violations.append(f"{path.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


class _SequenceUseCase:
    def __init__(
        self,
        *,
        name: str,
        results: tuple[object, ...],
        events: list[tuple[str, object]],
    ) -> None:
        self._name = name
        self._results = list(results)
        self._events = events

    async def execute(self, command: object) -> object:
        self._events.append((self._name, command))
        return self._results.pop(0)


def _raises_value_error(expected: str) -> _RaisesValueError:
    return _RaisesValueError(expected)


class _RaisesValueError:
    def __init__(self, expected: str) -> None:
        self._expected = expected

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: object,
    ) -> bool:
        if exc_type is None:
            raise AssertionError("ValueError was not raised")
        if exc_type is not ValueError:
            return False
        assert exc is not None
        assert self._expected in str(exc)
        return True


def _pipeline_use_cases(
    *,
    document_result: object,
    fact_results: tuple[object, ...] = (),
    context_result: object | None = None,
    events: list[tuple[str, object]] | None = None,
) -> pipeline_public.DocumentMemoryPipelineUseCases:
    events = events if events is not None else []
    document_use_cases = document_ingestion_public.DocumentIngestionUseCases(
        prepare_document_ingestion=_SequenceUseCase(
            name="prepare_document_ingestion",
            results=(),
            events=events,
        ),
        ingest_document=_SequenceUseCase(
            name="ingest_document",
            results=(document_result,),
            events=events,
        ),
    )
    memory_use_cases = None
    if fact_results:
        memory_use_cases = memory_facts_public.MemoryFactLifecycleUseCases(
            remember_fact=_SequenceUseCase(
                name="remember_fact",
                results=fact_results,
                events=events,
            ),
            update_fact=_SequenceUseCase(name="update_fact", results=(), events=events),
            forget_fact=_SequenceUseCase(name="forget_fact", results=(), events=events),
        )
    context_use_cases = None
    if context_result is not None:
        context_use_cases = context_building_public.ContextBuildingUseCases(
            build_context=_SequenceUseCase(
                name="build_context",
                results=(context_result,),
                events=events,
            )
        )
    return pipeline_public.DocumentMemoryPipelineUseCases(
        document_ingestion=document_use_cases,
        memory_facts=memory_use_cases,
        context_building=context_use_cases,
    )


def _ingest_command() -> document_ingestion_public.IngestDocumentCommand:
    return document_ingestion_public.IngestDocumentCommand(
        scope=_document_scope(),
        title="Planning note",
        origin=document_ingestion_public.SourceDocumentOrigin(
            source_type="markdown",
            source_external_id="planning.md",
        ),
        text="The deployment runbook requires a dry run before release.",
        idempotency_key="ingest-document-1",
    )


def _document_result() -> document_ingestion_public.IngestDocumentResult:
    command = _ingest_command()
    draft = document_ingestion_public.SourceDocumentDraft.create(
        scope=command.scope,
        title=command.title,
        origin=command.origin,
        text=command.text,
    )
    document = document_ingestion_public.SourceDocument.from_draft(
        document_id="doc-1",
        draft=draft,
    )
    chunk_draft = document_ingestion_public.ChunkingPolicy().plan_chunks(draft.content.text)[0]
    chunk = document_ingestion_public.DocumentChunk.from_draft(
        chunk_id="chunk-1",
        document_id=document.identity.document_id,
        scope=command.scope,
        draft=chunk_draft,
    )
    return document_ingestion_public.IngestDocumentResult(
        document=document,
        chunks=(chunk,),
        indexing_status="indexed",
    )


def _document_scope() -> document_ingestion_public.DocumentIngestionScope:
    return document_ingestion_public.DocumentIngestionScope(
        space_id="space-1",
        memory_scope_id="scope-1",
        thread_id="thread-1",
    )


def _memory_scope() -> memory_facts_public.MemoryFactScope:
    return memory_facts_public.MemoryFactScope(
        space_id="space-1",
        memory_scope_id="scope-1",
        thread_id="thread-1",
    )


def _source_ref() -> memory_facts_public.MemoryFactSourceRef:
    return memory_facts_public.MemoryFactSourceRef(
        source_type="document",
        source_id="doc-1",
        chunk_id="chunk-1",
        quote_preview="requires a dry run",
    )


def _remember_fact_command(fact_id: str) -> memory_facts_public.RememberFactCommand:
    return memory_facts_public.RememberFactCommand(
        scope=_memory_scope(),
        text=f"{fact_id} remembers the dry-run requirement.",
        source_refs=(_source_ref(),),
        kind="requirement",
        idempotency_key=fact_id,
    )


def _remember_fact_result(fact_id: str) -> memory_facts_public.RememberFactResult:
    snapshot = memory_facts_public.MemoryFactSnapshot(
        identity=memory_facts_public.MemoryFactIdentity(
            fact_id=fact_id,
            scope=_memory_scope(),
        ),
        text=f"{fact_id} remembers the dry-run requirement.",
        source_refs=(_source_ref(),),
        kind="requirement",
    )
    return memory_facts_public.RememberFactResult(fact=snapshot)


def _build_context_query() -> context_building_public.BuildContextQuery:
    return context_building_public.BuildContextQuery(
        query=context_building_public.ContextQuery(
            scope=context_building_public.ContextScope(
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id="thread-1",
            ),
            text="What does the runbook require?",
        ),
        budget=context_building_public.ContextBudget(
            max_prompt_tokens=128,
            reserved_response_tokens=32,
        ),
        candidate_limit=5,
        idempotency_key="context-1",
    )


def _build_context_result(
    query: context_building_public.BuildContextQuery,
) -> context_building_public.BuildContextResult:
    return context_building_public.BuildContextResult(
        bundle=context_building_public.ContextBundle(
            query=query.query,
            items=(),
            rendered_evidence="",
            max_prompt_tokens=query.budget.max_prompt_tokens,
        )
    )


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
    return any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes)
