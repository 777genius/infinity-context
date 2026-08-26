from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_FEATURE = (
    REPO_ROOT
    / "packages"
    / "infinity_context_core"
    / "infinity_context_core"
    / "features"
    / "context_building"
)
SERVER_PACKAGE = REPO_ROOT / "packages" / "infinity_context_server" / "infinity_context_server"
SERVER_CONTEXT_BUILDING = SERVER_PACKAGE / "features" / "context_building"
ADAPTERS_PACKAGE = (
    REPO_ROOT / "packages" / "infinity_context_adapters" / "infinity_context_adapters"
)
POSTGRES_ADAPTER = ADAPTERS_PACKAGE / "postgres"
QDRANT_ADAPTER = ADAPTERS_PACKAGE / "qdrant"
PRODUCTION_PACKAGE_ROOTS = tuple((REPO_ROOT / "packages").glob("*/"))
TYPESCRIPT_RETRIEVAL_ROOT = REPO_ROOT / "packages" / "infinity_context_ts_sdk" / "src"
VERSIONED_RETRIEVAL_PATH_ALLOWLIST = {
    REPO_ROOT
    / "packages"
    / "infinity_context_adapters"
    / "infinity_context_adapters"
    / "postgres"
    / "maintenance"
    / "locator_retrieval_v2_concurrent_indexes.sql",
}
OLD_RETRIEVAL_IDENTIFIER = re.compile(
    r"(?:RetrievalV2|RetrieveContextV2|ContextRetrieval\w*V2|"
    r"(?:Canonical|Postgres)?Locator\w*V2|retrieve_context_v2|"
    r"locator_retrieval_v2|retrieval_v2)"
)
OLD_SERVING_MODULE = "infinity_context_server.serving_identity"
NEW_SOURCE_CLASSIFICATION = {
    CORE_FEATURE / "domain" / "locator_retrieval.py": "domain",
    CORE_FEATURE / "domain" / "locator_retrieval_filters.py": "domain_filters",
    CORE_FEATURE / "ports" / "locator_retrieval.py": "ports",
    CORE_FEATURE / "application" / "locator_retrieval.py": "application",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval.py": "contract",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_validation.py": "contract",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_filters.py": "contract_filters",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_json.py": "contract_json",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_capability.py": "contract_capability",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_response.py": "contract_response",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_retrieval_errors.py": "contract_error",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_document_retrieval_projection_v1.py": "contract_projection",
    CORE_FEATURE / "domain" / "retrieval_capability.py": "domain_capability",
    CORE_FEATURE / "domain" / "retrieval_canonical.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_dataset.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_evaluation.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_evidence.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_qualification.py": "domain_eval",
    REPO_ROOT
    / "packages"
    / "infinity_context_core"
    / "infinity_context_core"
    / "features"
    / "document_ingestion"
    / "domain"
    / "retrieval_projection.py": "ingestion_domain",
    REPO_ROOT
    / "packages"
    / "infinity_context_core"
    / "infinity_context_core"
    / "features"
    / "document_ingestion"
    / "ports"
    / "projection_ownership.py": "ingestion_ports",
}
INTEGRATION_SOURCE_CLASSIFICATION = {
    SERVER_CONTEXT_BUILDING / "retrieval_service.py": "application_composition",
    SERVER_CONTEXT_BUILDING / "retrieval_mappers.py": "contract_mapping",
    SERVER_PACKAGE / "retrieval_composition.py": "provider_composition",
    SERVER_PACKAGE / "api" / "v1" / "context_retrieval.py": "http_adapter",
    POSTGRES_ADAPTER / "locator_retrieval.py": "canonical_read_adapter",
    POSTGRES_ADAPTER / "projected_document_ingestion.py": "canonical_write_adapter",
    POSTGRES_ADAPTER / "locator_models.py": "canonical_schema_adapter",
    POSTGRES_ADAPTER / "retrieval_projection_mapping.py": "projection_contract_mapping",
    POSTGRES_ADAPTER / "locator_projection_maintenance.py": "derived_repair_adapter",
    POSTGRES_ADAPTER
    / "migrations"
    / "0039_locator_retrieval_attributes.sql": "canonical_schema_migration",
    QDRANT_ADAPTER / "locator_profile.py": "derived_schema_adapter",
    QDRANT_ADAPTER / "locator_runtime.py": "derived_runtime_adapter",
}
STDLIB_ALLOWLIST = {
    "application": {"__future__", "asyncio", "dataclasses", "json", "math"},
    "contract": {
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "decimal",
        "math",
        "re",
    },
    "contract_capability": {"__future__", "collections", "dataclasses", "hashlib", "json"},
    "contract_filters": {"__future__", "collections", "dataclasses"},
    "contract_json": {"__future__", "collections", "json"},
    "contract_error": {"__future__", "collections", "dataclasses"},
    "contract_projection": {"__future__", "collections", "dataclasses", "datetime", "re"},
    "contract_response": {"__future__", "collections"},
    "domain_capability": {"__future__", "dataclasses", "math"},
    "domain_eval": {
        "__future__",
        "collections",
        "dataclasses",
        "fractions",
        "hashlib",
        "json",
        "pathlib",
        "types",
        "typing",
    },
    "domain_filters": {"__future__", "dataclasses", "datetime", "math"},
    "ingestion_domain": {"__future__", "dataclasses", "datetime"},
    "ingestion_ports": {"__future__", "dataclasses", "typing"},
    "domain": {"__future__", "dataclasses", "datetime", "decimal", "math"},
    "ports": {"__future__", "typing"},
}
OWN_FEATURE_ALLOWLIST = {
    "application": {
        "infinity_context_core.features.context_building.domain.locator_retrieval",
        "infinity_context_core.features.context_building.ports.locator_retrieval",
    },
    "contract": {
        ".._json",
        "._context_building_retrieval_filters",
        "._context_building_retrieval_response",
        "._context_building_retrieval_validation",
    },
    "contract_capability": {
        ".._json",
        "._context_building_retrieval_json",
        "._context_building_retrieval_validation",
    },
    "contract_filters": {
        ".._json",
        "._context_building_retrieval_validation",
    },
    "contract_json": {"._context_building_retrieval"},
    "contract_error": {".._json"},
    "contract_projection": {".._json", "._context_building_retrieval_json"},
    "contract_response": {"._context_building_retrieval"},
    "domain_capability": set(),
    "domain_eval": {
        "infinity_context_core.features.context_building.domain.locator_retrieval",
        "infinity_context_core.features.context_building.domain.retrieval_canonical",
        "infinity_context_core.features.context_building.domain.retrieval_dataset",
        "infinity_context_core.features.context_building.domain.retrieval_evaluation",
        "infinity_context_core.features.context_building.domain.retrieval_qualification",
    },
    "domain_filters": {
        "infinity_context_core.features.context_building.domain.retrieval_capability"
    },
    "ingestion_domain": {"infinity_context_core.features.document_ingestion.domain.errors"},
    "ingestion_ports": {
        "infinity_context_core.features.document_ingestion.domain",
        "infinity_context_core.features.document_ingestion.domain.retrieval_projection",
    },
    "domain": {
        "infinity_context_core.features.context_building.domain.locator_retrieval_filters",
        "infinity_context_core.features.context_building.domain.retrieval_capability",
    },
    "ports": {"infinity_context_core.features.context_building.domain.locator_retrieval"},
}


def test_every_locator_retrieval_source_has_fail_closed_dependency_classification() -> None:
    assert all(path.is_file() for path in NEW_SOURCE_CLASSIFICATION)
    assert set(NEW_SOURCE_CLASSIFICATION.values()) == set(STDLIB_ALLOWLIST)
    assert all(path.is_file() for path in INTEGRATION_SOURCE_CLASSIFICATION)
    assert len(set(INTEGRATION_SOURCE_CLASSIFICATION.values())) == len(
        INTEGRATION_SOURCE_CLASSIFICATION
    )


def test_locator_retrieval_imports_follow_explicit_layer_allowlists() -> None:
    violations: list[str] = []
    for path, classification in NEW_SOURCE_CLASSIFICATION.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imports(tree):
            root = name.lstrip(".").split(".", 1)[0]
            if (
                root not in STDLIB_ALLOWLIST[classification]
                and name not in OWN_FEATURE_ALLOWLIST[classification]
            ):
                violations.append(f"{classification}:{path.name}:{name}")
    assert violations == []


def test_locator_retrieval_layer_dependency_direction_is_inward_only() -> None:
    dependencies = {
        classification: {
            name
            for name in _imports(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            if name.startswith("infinity_context_core.features.context_building")
        }
        for path, classification in NEW_SOURCE_CLASSIFICATION.items()
        if classification in {"application", "contract", "domain", "ports"}
    }
    assert dependencies["domain"] == {
        "infinity_context_core.features.context_building.domain.locator_retrieval_filters",
        "infinity_context_core.features.context_building.domain.retrieval_capability",
    }
    assert dependencies["ports"] == {
        "infinity_context_core.features.context_building.domain.locator_retrieval"
    }
    assert dependencies["application"] == {
        "infinity_context_core.features.context_building.domain.locator_retrieval",
        "infinity_context_core.features.context_building.ports.locator_retrieval",
    }
    assert dependencies["contract"] == set()


def test_locator_retrieval_boundary_adr_is_accepted_and_locator_only() -> None:
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-0011-locator-retrieval-v2-boundary.md").read_text(
        encoding="utf-8"
    )
    assert "Status: accepted" in adr
    assert "locator-only" in adr
    assert "weighted_rrf_canonical_preferences.v1" in adr
    assert "document-retrieval-projection.v1" in adr
    assert "Meeting" not in adr
    assert "Discord" not in adr


def test_current_retrieval_has_no_v2_or_old_serving_identifiers() -> None:
    """Keep V2 at immutable wire/state/history boundaries, never in current code names."""

    violations: list[str] = []
    for package_root in PRODUCTION_PACKAGE_ROOTS:
        for path in package_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            violations.extend(
                f"{path.relative_to(REPO_ROOT)}:{name}"
                for name in _imports(tree)
                if name.lstrip(".") == OLD_SERVING_MODULE
                or name.lstrip(".").endswith(".serving_identity")
            )
            for node in ast.walk(tree):
                names = _defined_or_referenced_names(node)
                violations.extend(
                    f"{path.relative_to(REPO_ROOT)}:{name}"
                    for name in names
                    if OLD_RETRIEVAL_IDENTIFIER.search(name)
                )
    for path in TYPESCRIPT_RETRIEVAL_ROOT.rglob("*.ts"):
        identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", path.read_text(encoding="utf-8"))
        violations.extend(
            f"{path.relative_to(REPO_ROOT)}:{name}"
            for name in identifiers
            if OLD_RETRIEVAL_IDENTIFIER.search(name)
        )
    assert violations == []
    assert not (SERVER_PACKAGE / "serving_identity.py").exists()


def test_versioned_retrieval_filenames_are_explicit_immutable_boundaries() -> None:
    versioned_paths = {
        path
        for package_root in PRODUCTION_PACKAGE_ROOTS
        for path in package_root.rglob("*")
        if path.is_file()
        and ("retrieval_v2" in path.name or "retrieval-v2" in path.name)
        and "fixtures/context_retrieval_v2" not in path.as_posix()
        and "/migrations/" not in path.as_posix()
    }
    assert versioned_paths == VERSIONED_RETRIEVAL_PATH_ALLOWLIST


def _imports(tree: ast.AST) -> tuple[str, ...]:
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(f"{'.' * node.level}{node.module}")
    return tuple(imported)


def _defined_or_referenced_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return (node.name,)
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        return (node.attr,)
    if isinstance(node, ast.alias):
        return (node.name, node.asname or "")
    return ()
