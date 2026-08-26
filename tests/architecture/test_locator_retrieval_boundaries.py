from __future__ import annotations

import ast
import asyncio
import importlib.util
import os
import re
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

from infinity_context_core.ports.adapters import VectorWriteResult
from infinity_context_server.composition import Container
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.processes.projections import ProjectionOutboxProcess

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
CURRENT_SOURCE_ROOTS = tuple(
    path
    for path in (
        REPO_ROOT / "packages",
        REPO_ROOT / "docs",
        REPO_ROOT / "examples",
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
        REPO_ROOT / "plugins",
        REPO_ROOT / ".github",
    )
    if path.exists()
)
VERSIONED_RETRIEVAL_PATH_ALLOWLIST: set[Path] = set()
OLD_RETRIEVAL_IDENTIFIER = re.compile(
    r"(?:RetrievalV2|RetrieveContextV2|ContextRetrieval\w*V2|"
    r"(?:Canonical|Postgres)?Locator\w*V2|retrieve_context_v2|"
    r"locator_retrieval_v2|retrieval_v2)"
)
OLD_SERVING_MODULE = "infinity_context_server.serving_identity"
REMOVED_RETRIEVAL_MODULE = "infinity_context_server.retrieval_composition"
REMOVED_PROJECTION_MODULE = "infinity_context_adapters.postgres.locator_projection_maintenance"
REMOVED_PROJECTION_NAMES = {
    "locator_projection_maintenance",
    "locator_vector_index",
}
CURRENT_V2_NAME = re.compile(
    r"\bRetrieval[ _-]?V2\b|\bretrieval[_-]v2\b|\blocator[ _-]?V2\b",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {
    ".cjs",
    ".cts",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".mts",
    ".py",
    ".pyi",
    ".rst",
    ".toml",
    ".ts",
    ".tsx",
    ".sh",
    ".yaml",
    ".yml",
}
IMMUTABLE_V2_PATHS = {
    Path("docs/adr/ADR-0011-locator-retrieval-v2-boundary.md"),
    *(
        Path("packages/infinity_context_adapters/infinity_context_adapters/postgres/migrations")
        / name
        for name in (
            "0039_locator_retrieval_attributes.sql",
            "0040_locator_profile_lifecycle.sql",
            "0041_locator_profile_attestation_fence.sql",
            "0042_locator_profile_retirement.sql",
            "0043_locator_profile_transition_audit.sql",
            "0044_locator_profile_operator_receipts.sql",
            "0046_locator_profile_linearizable_fences.sql",
        )
    ),
}
IMMUTABLE_WIRE_PATH_PREFIXES = (
    Path(
        "packages/infinity_context_contracts/infinity_context_contracts/fixtures/context_retrieval_v2"
    ),
    Path("packages/infinity_context_ts_sdk/fixtures/context_retrieval_v2"),
)
IMMUTABLE_V2_LINE_MARKERS = {
    "ADR-0011-locator-retrieval-v2-boundary.md",
    "context-retrieval.v2",
    "context-retrieval-v2-cases.v1",
    "context-retrieval-v2-errors.v1",
    "context_retrieval_v2",
    "generic-retrieval-v2-dataset.v1",
    "locator-v2-{self.profile_kind}-{self.index_profile_digest}",
    "locator-v2-pairs-relative-22222222",
    "locator-v2-reproject:",
    "locator-v2-tombstone:",
    "pre-0046 Retrieval V2 writers",
}
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
    SERVER_PACKAGE / "retrieval_profile_composition.py": "provider_composition",
    SERVER_PACKAGE / "api" / "v1" / "context_retrieval.py": "http_adapter",
    POSTGRES_ADAPTER / "locator_retrieval.py": "canonical_read_adapter",
    POSTGRES_ADAPTER / "projected_document_ingestion.py": "canonical_write_adapter",
    POSTGRES_ADAPTER / "locator_models.py": "canonical_schema_adapter",
    POSTGRES_ADAPTER / "retrieval_projection_mapping.py": "projection_contract_mapping",
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
    """Keep V2 at explicit immutable boundaries, never in current names or strings."""

    violations: list[str] = []
    for path in _current_text_files():
        relative = path.relative_to(REPO_ROOT)
        text = path.read_text(encoding="utf-8")
        violations.extend(_source_boundary_violations(relative, text))
    assert violations == []
    assert not (SERVER_PACKAGE / "serving_identity.py").exists()
    assert not (SERVER_PACKAGE / "retrieval_composition.py").exists()
    assert not (POSTGRES_ADAPTER / "locator_projection_maintenance.py").exists()


def test_retrieval_boundary_guard_catches_python_and_typescript_mutations() -> None:
    mutations = {
        Path("packages/example/mutant.py"): (
            "import importlib\n"
            "old = importlib.import_module('infinity_context_adapters.postgres.' + "
            "'locator_' + 'projection_maintenance')\n"
            "legacy = getattr(object(), 'locator_' + 'vector_index')\n"
            "label = 'locator-' + 'v2'\n"
        ),
        Path("packages/example/mutant.ts"): (
            "const old = container['locator_' + 'vector_index'];\n"
            "const module = import('infinity_context_server.' + 'retrieval_composition');\n"
            "const label = 'locator-' + 'v2';\n"
        ),
    }
    for relative, text in mutations.items():
        assert _source_boundary_violations(relative, text), relative


def test_retrieval_boundary_guard_allows_exact_frozen_fixture_identifier() -> None:
    samples = {
        Path(
            "packages/infinity_context_contracts/infinity_context_contracts/fixtures/"
            "context_retrieval_v2/frozen.py"
        ): ("context_retrieval_v2 = 'fixtures/context_retrieval_v2/request.json'\n"),
        Path("packages/infinity_context_ts_sdk/fixtures/context_retrieval_v2/frozen.ts"): (
            "const context_retrieval_v2 = 'fixtures/context_retrieval_v2/request.json';\n"
        ),
    }
    for relative, text in samples.items():
        assert _source_boundary_violations(relative, text) == [], relative


def test_drained_projection_lane_cannot_be_dynamically_injected() -> None:
    class Vector:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, ...]] = []

        async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> VectorWriteResult:
            self.deleted.append(chunk_ids)
            return VectorWriteResult.ok(len(chunk_ids))

    class Poison:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"drained projection lane accessed: {name}")

    vector = Vector()
    container = SimpleNamespace(vector_index=vector)
    for name in REMOVED_PROJECTION_NAMES:
        setattr(container, name, Poison())
    process = ProjectionOutboxProcess(container)
    job = ClaimedOutboxJob(
        id=1,
        event_type="vector.delete_chunks",
        aggregate_id="chunk-a",
        aggregate_version=7,
        attempt_count=0,
        workload_class="projection",
        fairness_key="chunk:chunk-a",
        payload_json={"chunk_ids": ["chunk-a"]},
        aggregate_type="locator_chunk",
    )

    asyncio.run(process.handle_vector_delete_chunks(job))
    asyncio.run(
        process.handle_vector_upsert(
            ClaimedOutboxJob(
                id=2,
                event_type="vector.upsert_chunk",
                aggregate_id="chunk-a",
                aggregate_version=8,
                attempt_count=0,
                workload_class="projection",
                fairness_key="chunk:chunk-a",
                payload_json={"chunk_id": "chunk-a"},
                aggregate_type="locator_chunk",
            )
        )
    )

    assert vector.deleted == []
    assert REMOVED_PROJECTION_NAMES.isdisjoint(Container.__annotations__)


def test_drained_retrieval_runtime_has_no_dynamic_or_packaged_consumer() -> None:
    profile_source = (SERVER_PACKAGE / "retrieval_profile_composition.py").read_text(
        encoding="utf-8"
    )
    composition_source = (SERVER_PACKAGE / "composition.py").read_text(encoding="utf-8")
    assert "fallback" not in profile_source
    assert "build_locator_retrieval_service" not in composition_source
    assert importlib.util.find_spec(OLD_SERVING_MODULE) is None
    assert importlib.util.find_spec(REMOVED_RETRIEVAL_MODULE) is None
    assert importlib.util.find_spec(REMOVED_PROJECTION_MODULE) is None

    removed_members = {
        "infinity_context_server/serving_identity.py",
        "infinity_context_server/retrieval_composition.py",
        "infinity_context_adapters/postgres/locator_projection_maintenance.py",
    }
    violations: list[str] = []
    for path in _current_text_files():
        text = path.read_text(encoding="utf-8")
        if not _immutable_v2_path(path.relative_to(REPO_ROOT)) and any(
            module in text
            for module in (
                OLD_SERVING_MODULE,
                REMOVED_RETRIEVAL_MODULE,
                REMOVED_PROJECTION_MODULE,
            )
        ):
            violations.append(f"{path.relative_to(REPO_ROOT)}:removed module consumer")
    archive_roots = (
        REPO_ROOT,
        REPO_ROOT / "dist",
        REPO_ROOT / "packages" / "infinity_context_ts_sdk",
    )
    archive_paths = {
        path
        for root in archive_roots
        if root.exists()
        for pattern in ("*.tar", "*.tar.gz", "*.tgz", "*.whl", "*.zip")
        for path in root.glob(pattern)
    }
    for path in sorted(archive_paths):
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    violations.extend(
                        f"{path.relative_to(REPO_ROOT)}:{name}"
                        for name in archive.namelist()
                        if any(name.endswith(member) for member in removed_members)
                    )
                    for name in archive.namelist():
                        if name.endswith("retrieval_profile_composition.py"):
                            source = archive.read(name).decode("utf-8")
                            if "fallback" in source:
                                violations.append(
                                    f"{path.relative_to(REPO_ROOT)}:{name}:drained fallback"
                                )
            elif path.name.endswith((".tar", ".tar.gz", ".tgz")) and tarfile.is_tarfile(path):
                with tarfile.open(path) as archive:
                    violations.extend(
                        f"{path.relative_to(REPO_ROOT)}:{member.name}"
                        for member in archive.getmembers()
                        if any(member.name.endswith(name) for name in removed_members)
                    )
                    for member in archive.getmembers():
                        if member.name.endswith("retrieval_profile_composition.py"):
                            extracted = archive.extractfile(member)
                            if extracted is not None and b"fallback" in extracted.read():
                                violations.append(
                                    f"{path.relative_to(REPO_ROOT)}:{member.name}:drained fallback"
                                )
        except OSError:
            continue
    assert violations == []


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


def _source_boundary_violations(relative: Path, text: str) -> list[str]:
    violations: list[str] = []
    lines = text.splitlines()
    removed_modules = {
        OLD_SERVING_MODULE,
        REMOVED_RETRIEVAL_MODULE,
        REMOVED_PROJECTION_MODULE,
    }
    if "serving_identity" in relative.name:
        violations.append(f"{relative}:old serving filename")
    if (
        "retrieval_v2" in relative.name or "retrieval-v2" in relative.name
    ) and not _immutable_v2_path(relative):
        violations.append(f"{relative}:current V2 filename")
    for line_number, line in enumerate(lines, 1):
        if "serving_identity" in line:
            violations.append(f"{relative}:{line_number}:old serving name")
        if any(name in line for name in REMOVED_PROJECTION_NAMES) and not _immutable_v2_path(
            relative
        ):
            violations.append(f"{relative}:{line_number}:removed projection name")
        if CURRENT_V2_NAME.search(line) and not _immutable_v2_line(relative, line):
            violations.append(f"{relative}:{line_number}:current V2 name")
    if relative.suffix in {".py", ".pyi"}:
        tree = ast.parse(text, filename=str(relative))
        violations.extend(
            f"{relative}:{name}"
            for name in _imports(tree)
            if name.lstrip(".") in removed_modules
            or name.lstrip(".").endswith(
                (
                    ".serving_identity",
                    ".retrieval_composition",
                    ".locator_projection_maintenance",
                )
            )
        )
        for node in ast.walk(tree):
            for name in _defined_or_referenced_names(node):
                if OLD_RETRIEVAL_IDENTIFIER.search(name) and not _immutable_v2_path(relative):
                    violations.append(f"{relative}:{name}")
            value = _static_python_string(node)
            if value is not None:
                source_line = lines[getattr(node, "lineno", 1) - 1]
                if any(module in value for module in removed_modules) and not _immutable_v2_path(
                    relative
                ):
                    violations.append(f"{relative}:dynamic old module string")
                if any(name in value for name in REMOVED_PROJECTION_NAMES) and not (
                    _immutable_v2_path(relative)
                ):
                    violations.append(f"{relative}:dynamic removed projection name")
                if CURRENT_V2_NAME.search(value) and not _immutable_v2_line(relative, source_line):
                    violations.append(f"{relative}:dynamic current V2 name")
    elif relative.suffix in {".cts", ".mts", ".ts", ".tsx"} or relative.name.endswith(
        (".d.cts", ".d.ts")
    ):
        for line_number, line in enumerate(lines, 1):
            violations.extend(
                f"{relative}:{name}"
                for name in re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", line)
                if OLD_RETRIEVAL_IDENTIFIER.search(name)
                and not _immutable_v2_path(relative)
                and not _immutable_v2_line(relative, line)
            )
            for value in _typescript_static_strings(line):
                if any(module in value for module in removed_modules) and not _immutable_v2_path(
                    relative
                ):
                    violations.append(f"{relative}:{line_number}:dynamic old module string")
                if any(name in value for name in REMOVED_PROJECTION_NAMES) and not (
                    _immutable_v2_path(relative)
                ):
                    violations.append(f"{relative}:{line_number}:dynamic removed projection name")
                if CURRENT_V2_NAME.search(value) and not _immutable_v2_line(relative, line):
                    violations.append(f"{relative}:{line_number}:dynamic current V2 name")
    return violations


def _static_python_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_python_string(node.left)
        right = _static_python_string(node.right)
        return None if left is None or right is None else left + right
    return None


def _typescript_static_strings(line: str) -> tuple[str, ...]:
    values: list[str] = []
    quoted = r"(?:'[^'\\]*(?:\\.[^'\\]*)*'|\"[^\"\\]*(?:\\.[^\"\\]*)*\")"
    pattern = re.compile(quoted + r"(?:\s*\+\s*" + quoted + r")+")
    literal = re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*)'|\"([^\"\\]*(?:\\.[^\"\\]*)*)\"")
    for match in pattern.finditer(line):
        values.append(
            "".join(
                next(value for value in item.groups() if value is not None)
                for item in literal.finditer(match.group(0))
            )
        )
    return tuple(values)


def _current_text_files() -> tuple[Path, ...]:
    guard = Path(__file__).resolve()
    excluded = {
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "node_modules",
        "__pycache__",
    }
    paths: set[Path] = set()
    for root in CURRENT_SOURCE_ROOTS:
        for directory, names, filenames in os.walk(root):
            names[:] = [name for name in names if name not in excluded]
            for filename in filenames:
                path = Path(directory) / filename
                if path != guard and (
                    path.suffix in TEXT_SUFFIXES or path.name.endswith((".d.cts", ".d.ts"))
                ):
                    paths.add(path)
    paths.update(
        path for path in (REPO_ROOT / "README.md", REPO_ROOT / "pyproject.toml") if path.exists()
    )
    return tuple(sorted(paths))


def _immutable_v2_path(relative: Path) -> bool:
    return relative in IMMUTABLE_V2_PATHS or any(
        relative == prefix or prefix in relative.parents for prefix in IMMUTABLE_WIRE_PATH_PREFIXES
    )


def _immutable_v2_line(relative: Path, line: str) -> bool:
    if _immutable_v2_path(relative):
        return True
    if (
        "ADR-0011-locator-retrieval-v2-boundary.md" in line
        or "pre-0046 Retrieval V2 writers" in line
    ):
        return True
    sanitized = line
    for marker in IMMUTABLE_V2_LINE_MARKERS:
        sanitized = sanitized.replace(marker, "")
    return not CURRENT_V2_NAME.search(sanitized)
