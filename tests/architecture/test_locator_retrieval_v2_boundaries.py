from __future__ import annotations

import ast
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
NEW_SOURCE_CLASSIFICATION = {
    CORE_FEATURE / "domain" / "locator_retrieval_v2.py": "domain",
    CORE_FEATURE / "domain" / "locator_retrieval_v2_filters.py": "domain_filters",
    CORE_FEATURE / "ports" / "locator_retrieval_v2.py": "ports",
    CORE_FEATURE / "application" / "locator_retrieval_v2.py": "application",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_v2.py": "contract",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_v2_validation.py": "contract",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_v2_filters.py": "contract_filters",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_v2_json.py": "contract_json",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_v2_capability.py": "contract_capability",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_building_retrieval_v2_response.py": "contract_response",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_context_retrieval_v2_errors.py": "contract_error",
    REPO_ROOT
    / "packages"
    / "infinity_context_contracts"
    / "infinity_context_contracts"
    / "features"
    / "_document_retrieval_projection_v1.py": "contract_projection",
    CORE_FEATURE / "domain" / "retrieval_v2_capability.py": "domain_capability",
    CORE_FEATURE / "domain" / "retrieval_v2_canonical.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_v2_dataset.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_v2_evaluation.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_v2_evidence.py": "domain_eval",
    CORE_FEATURE / "domain" / "retrieval_v2_qualification.py": "domain_eval",
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
        "infinity_context_core.features.context_building.domain.locator_retrieval_v2",
        "infinity_context_core.features.context_building.ports.locator_retrieval_v2",
    },
    "contract": {
        ".._json",
        "._context_building_retrieval_v2_filters",
        "._context_building_retrieval_v2_response",
        "._context_building_retrieval_v2_validation",
    },
    "contract_capability": {
        ".._json",
        "._context_building_retrieval_v2_json",
        "._context_building_retrieval_v2_validation",
    },
    "contract_filters": {
        ".._json",
        "._context_building_retrieval_v2_validation",
    },
    "contract_json": {"._context_building_retrieval_v2"},
    "contract_error": {".._json"},
    "contract_projection": {".._json", "._context_building_retrieval_v2_json"},
    "contract_response": {"._context_building_retrieval_v2"},
    "domain_capability": set(),
    "domain_eval": {
        "infinity_context_core.features.context_building.domain.locator_retrieval_v2",
        "infinity_context_core.features.context_building.domain.retrieval_v2_canonical",
        "infinity_context_core.features.context_building.domain.retrieval_v2_dataset",
        "infinity_context_core.features.context_building.domain.retrieval_v2_evaluation",
        "infinity_context_core.features.context_building.domain.retrieval_v2_qualification",
    },
    "domain_filters": {
        "infinity_context_core.features.context_building.domain.retrieval_v2_capability"
    },
    "ingestion_domain": {"infinity_context_core.features.document_ingestion.domain.errors"},
    "ingestion_ports": {
        "infinity_context_core.features.document_ingestion.domain",
        "infinity_context_core.features.document_ingestion.domain.retrieval_projection",
    },
    "domain": {
        "infinity_context_core.features.context_building.domain.locator_retrieval_v2_filters",
        "infinity_context_core.features.context_building.domain.retrieval_v2_capability",
    },
    "ports": {"infinity_context_core.features.context_building.domain.locator_retrieval_v2"},
}


def test_every_locator_retrieval_v2_source_has_fail_closed_dependency_classification() -> None:
    assert all(path.is_file() for path in NEW_SOURCE_CLASSIFICATION)
    assert set(NEW_SOURCE_CLASSIFICATION.values()) == set(STDLIB_ALLOWLIST)
    assert all(path.is_file() for path in INTEGRATION_SOURCE_CLASSIFICATION)
    assert len(set(INTEGRATION_SOURCE_CLASSIFICATION.values())) == len(
        INTEGRATION_SOURCE_CLASSIFICATION
    )


def test_locator_retrieval_v2_imports_follow_explicit_layer_allowlists() -> None:
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


def test_locator_retrieval_v2_layer_dependency_direction_is_inward_only() -> None:
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
        "infinity_context_core.features.context_building.domain.locator_retrieval_v2_filters",
        "infinity_context_core.features.context_building.domain.retrieval_v2_capability",
    }
    assert dependencies["ports"] == {
        "infinity_context_core.features.context_building.domain.locator_retrieval_v2"
    }
    assert dependencies["application"] == {
        "infinity_context_core.features.context_building.domain.locator_retrieval_v2",
        "infinity_context_core.features.context_building.ports.locator_retrieval_v2",
    }
    assert dependencies["contract"] == set()


def test_locator_retrieval_v2_boundary_adr_is_accepted_and_locator_only() -> None:
    adr = (REPO_ROOT / "docs" / "adr" / "ADR-0011-locator-retrieval-v2-boundary.md").read_text(
        encoding="utf-8"
    )
    assert "Status: accepted" in adr
    assert "locator-only" in adr
    assert "weighted_rrf_canonical_preferences.v1" in adr
    assert "document-retrieval-projection.v1" in adr
    assert "Meeting" not in adr
    assert "Discord" not in adr


def _imports(tree: ast.AST) -> tuple[str, ...]:
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(f"{'.' * node.level}{node.module}")
    return tuple(imported)
