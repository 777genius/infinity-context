"""Static checks for feature-owned vertical slice boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

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


def _feature_dirs(root: str) -> list[Path]:
    path = REPO_ROOT / root
    if not path.exists():
        return []
    return sorted(child for child in path.iterdir() if child.is_dir() and not child.name.startswith("_"))


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


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


def test_core_feature_capsules_expose_public_api_when_created() -> None:
    missing_public_api: list[str] = []
    for path in _feature_dirs("packages/infinity_context_core/infinity_context_core/features"):
        if not (path / "public.py").exists():
            missing_public_api.append(str(path.relative_to(REPO_ROOT)))

    assert missing_public_api == []


def test_core_features_do_not_import_other_feature_internals() -> None:
    feature_root = REPO_ROOT / "packages" / "infinity_context_core" / "infinity_context_core" / "features"
    if not feature_root.exists():
        return

    violations: list[str] = []
    for feature_dir in _feature_dirs(str(feature_root.relative_to(REPO_ROOT))):
        current_feature = feature_dir.name
        for path in feature_dir.rglob("*.py"):
            for imported in _imports(path):
                prefix = "infinity_context_core.features."
                if not imported.startswith(prefix):
                    continue

                imported_parts = imported.removeprefix(prefix).split(".")
                if not imported_parts:
                    continue

                imported_feature = imported_parts[0]
                imports_internal = len(imported_parts) > 1 and imported_parts[1] != "public"
                if imported_feature != current_feature and imports_internal:
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}: imports {imported}")

    assert violations == []
