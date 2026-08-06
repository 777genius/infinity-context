"""Feature-local checks for memory_facts application, ports and public API."""

from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass
from pathlib import Path

APPLICATION_MODULE = "infinity_context_core.features.memory_facts.application"
DOMAIN_MODULE = "infinity_context_core.features.memory_facts.domain"
PORTS_MODULE = "infinity_context_core.features.memory_facts.ports"
PUBLIC_MODULE = "infinity_context_core.features.memory_facts.public"
FEATURE_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = FEATURE_ROOT.parents[3]
ALLOWED_CORE_PREFIXES = (
    "infinity_context_core.features.memory_facts.application",
    "infinity_context_core.features.memory_facts.domain",
    "infinity_context_core.features.memory_facts.ports",
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


def test_fact_lifecycle_commands_and_results_are_frozen_dataclasses() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    scope = domain.MemoryFactScope(space_id="space-1", memory_scope_id="scope-1")
    identity = domain.MemoryFactIdentity(fact_id="fact-1", scope=scope)
    source_ref = domain.MemoryFactSourceRef(source_type="document", source_id="doc-1")
    snapshot = domain.MemoryFactSnapshot(
        identity=identity,
        text="Fact text",
        source_refs=(source_ref,),
    )

    shapes = (
        (
            application.RememberFactCommand,
            application.RememberFactCommand(
                scope=scope,
                text="Fact text",
                source_refs=(source_ref,),
                idempotency_key="remember-1",
            ),
            (
                "scope",
                "text",
                "source_refs",
                "kind",
                "evidence_refs",
                "category",
                "tags",
                "quality",
                "temporal_extent",
                "freshness",
                "retention",
                "epistemic_context",
                "code_scope",
                "idempotency_key",
            ),
        ),
        (
            application.RememberFactResult,
            application.RememberFactResult(
                fact=snapshot,
                outbox_message_ids=("outbox-1",),
            ),
            ("fact", "outbox_message_ids", "replayed"),
        ),
        (
            application.UpdateFactCommand,
            application.UpdateFactCommand(
                identity=identity,
                expected_version=1,
                text="Updated fact text",
                source_refs=(source_ref,),
                reason="correction",
            ),
            (
                "identity",
                "expected_version",
                "text",
                "source_refs",
                "kind",
                "evidence_refs",
                "category",
                "tags",
                "retention",
                "reason",
                "idempotency_key",
                "authorized_code_scope",
            ),
        ),
        (
            application.UpdateFactResult,
            application.UpdateFactResult(fact=snapshot),
            ("fact", "outbox_message_ids", "replayed"),
        ),
        (
            application.ForgetFactCommand,
            application.ForgetFactCommand(
                identity=identity,
                expected_version=1,
                reason="obsolete",
            ),
            (
                "identity",
                "expected_version",
                "reason",
                "idempotency_key",
                "authorized_code_scope",
            ),
        ),
        (
            application.ForgetFactResult,
            application.ForgetFactResult(fact=snapshot, tombstone_id="tombstone-1"),
            ("fact", "tombstone_id", "outbox_message_ids", "replayed", "already_deleted"),
        ),
    )

    for shape, value, expected_fields in shapes:
        assert is_dataclass(shape)
        assert not hasattr(value, "__dict__")
        assert tuple(field.name for field in fields(shape)) == expected_fields
        _assert_frozen(value)


def test_fact_lifecycle_ports_are_protocol_boundaries() -> None:
    ports = importlib.import_module(PORTS_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)

    protocol_names = (
        "FactSupersessionRepositoryPort",
        "FactTemporalDecisionRepositoryPort",
        "MemoryFactClockPort",
        "MemoryFactIdPort",
        "MemoryFactOutboxPort",
        "MemoryFactRepositoryPort",
        "MemoryFactSelectionPort",
        "MemoryFactTransactionPort",
        "MemoryFactUnitOfWorkFactoryPort",
        "MemoryFactUnitOfWorkPort",
    )
    for name in protocol_names:
        assert getattr(getattr(ports, name), "_is_protocol", False)

    assert inspect.iscoroutinefunction(ports.MemoryFactOutboxPort.enqueue)
    for method_name in (
        "create",
        "get",
        "get_for_update",
        "get_many_for_update",
        "list_versions",
        "save",
    ):
        assert inspect.iscoroutinefunction(getattr(ports.MemoryFactRepositoryPort, method_name))
    assert inspect.iscoroutinefunction(ports.MemoryFactSelectionPort.find_eligible)
    for method_name in ("create", "find_active_successor", "list_active"):
        assert inspect.iscoroutinefunction(
            getattr(ports.FactSupersessionRepositoryPort, method_name)
        )
    for method_name in (
        "create",
        "find_compensation",
        "get",
        "get_by_idempotency_key",
    ):
        assert inspect.iscoroutinefunction(
            getattr(ports.FactTemporalDecisionRepositoryPort, method_name)
        )
    for method_name in ("__aenter__", "__aexit__", "commit", "rollback", "lock_scope"):
        assert inspect.iscoroutinefunction(getattr(ports.MemoryFactUnitOfWorkPort, method_name))
    assert not inspect.iscoroutinefunction(ports.MemoryFactUnitOfWorkFactoryPort.__call__)

    message = ports.MemoryFactOutboxMessage(
        message_id="outbox-1",
        event_type="fact.remembered",
        aggregate_id="fact-1",
        aggregate_version=1,
        scope=domain.MemoryFactScope("space-1", "scope-1"),
    )
    assert is_dataclass(ports.MemoryFactOutboxMessage)
    assert not hasattr(message, "__dict__")
    _assert_frozen(message)

    annotations = ports.MemoryFactTransactionPort.__annotations__
    assert annotations["facts"] == "MemoryFactRepositoryPort"
    assert annotations["supersessions"] == "FactSupersessionRepositoryPort"
    assert annotations["temporal_decisions"] == "FactTemporalDecisionRepositoryPort"
    assert annotations["operation_receipts"] == "MemoryFactOperationReceiptPort"
    assert annotations["outbox"] == "MemoryFactOutboxPort"
    assert domain.MemoryFactSnapshot.__name__ == "MemoryFactSnapshot"


def test_memory_facts_public_api_exports_exact_feature_boundary() -> None:
    application = importlib.import_module(APPLICATION_MODULE)
    domain = importlib.import_module(DOMAIN_MODULE)
    ports = importlib.import_module(PORTS_MODULE)
    public = importlib.import_module(PUBLIC_MODULE)

    expected_exports = {
        "FEATURE_ID": domain,
        "FACT_TEMPORAL_MUTATION_POLICY_VERSION": application,
        "SUPERSESSION_POLICY_VERSION": application,
        "DisputeFactsCommand": application,
        "DisputeFactsHandler": application,
        "DisputeFactsResult": application,
        "ConfirmFactCommand": application,
        "ConfirmFactHandler": application,
        "ConfirmFactResult": application,
        "EndFactValidityCommand": application,
        "EndFactValidityHandler": application,
        "EndFactValidityResult": application,
        "FactCurrentness": domain,
        "FactCurrentnessAssessment": domain,
        "FactCurrentnessPolicy": domain,
        "FactCodeScopeReference": domain,
        "FactEligibilityAssessment": domain,
        "FactEligibilityPolicy": domain,
        "FactEpistemicContext": domain,
        "FactEpistemicMode": domain,
        "FactFreshness": domain,
        "FactLifecycle": domain,
        "FactLifecycleStatus": domain,
        "FactQuality": domain,
        "FactRetention": domain,
        "FactRevision": domain,
        "FactTemporalAssurance": domain,
        "FactSupersessionPolicy": domain,
        "FactSupersessionRelation": domain,
        "FactTemporalDecision": domain,
        "FactTemporalDecisionRepositoryPort": ports,
        "FactTemporalDecisionType": domain,
        "FactSupersessionRepositoryPort": ports,
        "FactTemporalExtent": domain,
        "FactTemporalKind": domain,
        "FactTemporalQueryMode": domain,
        "ForgetFactCommand": application,
        "ForgetFactHandler": application,
        "ForgetFactResult": application,
        "ForgetFactUseCase": application,
        "MemoryFactClassification": domain,
        "MemoryFactClockPort": ports,
        "MemoryFactConfidence": domain,
        "MemoryFact": domain,
        "MemoryFactEvidenceRef": domain,
        "MemoryFactIdPort": ports,
        "MemoryFactIdentity": domain,
        "MemoryFactKind": domain,
        "MemoryFactLifecycleUseCases": application,
        "MemoryFactReadUseCases": application,
        "MemoryFactListSpec": ports,
        "MemoryFactReadModelPort": ports,
        "MemoryFactTemporalUseCases": application,
        "MemoryFactTransactionPort": ports,
        "MemoryFactOutboxMessage": ports,
        "MemoryFactOutboxPort": ports,
        "MemoryFactOperationReceipt": ports,
        "MemoryFactIdempotencyConflict": ports,
        "MemoryFactOperationReceiptPort": ports,
        "MemoryFactRepositoryPort": ports,
        "MemoryFactScope": domain,
        "MemoryFactSelectionPort": ports,
        "MemoryFactSelectionQuery": domain,
        "MemoryFactSnapshot": domain,
        "MemoryFactSourceRef": domain,
        "MemoryFactStatus": domain,
        "MemoryFactTrustLevel": domain,
        "MemoryFactUnitOfWorkFactoryPort": ports,
        "MemoryFactUnitOfWorkPort": ports,
        "MemoryFactVisibility": domain,
        "MemoryFactsFeature": domain,
        "RememberFactCommand": application,
        "RememberFactHandler": application,
        "RememberFactResult": application,
        "RememberFactUseCase": application,
        "ReinstateSupersededFactCommand": application,
        "ReinstateSupersededFactHandler": application,
        "ReinstateSupersededFactResult": application,
        "ReviewedFactCandidate": application,
        "ReviewedFactDecision": application,
        "ReviewedFactMutationExecutor": application,
        "ReviewedFactMutationPort": application,
        "ReviewedFactMutationResult": application,
        "ReviewedFactTarget": application,
        "SelectMemoryFactsHandler": application,
        "GetMemoryFactHandler": application,
        "ListMemoryFactVersionsHandler": application,
        "ListMemoryFactsHandler": application,
        "SupersedeFactCommand": application,
        "SupersedeFactHandler": application,
        "SupersedeFactResult": application,
        "UpdateFactCommand": application,
        "UpdateFactHandler": application,
        "UpdateFactResult": application,
        "UpdateFactUseCase": application,
    }

    assert public.__all__ == tuple(expected_exports)
    for name, module in expected_exports.items():
        assert getattr(public, name) is getattr(module, name)


def test_memory_facts_public_api_imports_only_feature_layer_boundaries() -> None:
    public_path = FEATURE_ROOT / "public.py"
    feature_imports = tuple(
        imported
        for imported in _imports(public_path)
        if imported.startswith("infinity_context_core.features.memory_facts")
    )

    assert feature_imports == (
        APPLICATION_MODULE,
        DOMAIN_MODULE,
        PORTS_MODULE,
    )


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
