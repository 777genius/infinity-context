"""Architecture and documentation gates for the cognitive foundation."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_core"
    / "infinity_context_core"
    / "features"
    / "cognitive_memory"
)
ADR_PATH = REPO_ROOT / "docs" / "adr" / "ADR-0009-provider-neutral-cognitive-foundation.md"
OWN_FEATURE_PREFIX = "infinity_context_core.features.cognitive_memory"


def _absolute_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append(node.module)
    return tuple(imports)


def _disallowed_imports(imports: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        imported
        for imported in imports
        if imported.split(".", maxsplit=1)[0] not in sys.stdlib_module_names
        and imported != OWN_FEATURE_PREFIX
        and not imported.startswith(f"{OWN_FEATURE_PREFIX}.")
    )


def test_cognitive_memory_uses_feature_owned_clean_architecture_shape() -> None:
    assert (FEATURE_ROOT / "public.py").is_file()
    for layer in ("domain", "application", "ports", "tests"):
        assert (FEATURE_ROOT / layer / "__init__.py").is_file()


def test_cognitive_core_has_no_provider_framework_or_infrastructure_imports() -> None:
    violations: list[str] = []
    for path in FEATURE_ROOT.rglob("*.py"):
        if "tests" in path.relative_to(FEATURE_ROOT).parts:
            continue
        for imported in _disallowed_imports(_absolute_imports(path)):
            violations.append(f"{path.relative_to(REPO_ROOT)}: imports {imported}")

    assert violations == []


def test_cognitive_import_allowlist_rejects_arbitrary_third_party_packages(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.py"
    fixture.write_text(
        "import json\nimport httpx\nimport boto3\n"
        "from infinity_context_core.features.cognitive_memory.domain import CognitiveKind\n",
        encoding="utf-8",
    )

    assert _disallowed_imports(_absolute_imports(fixture)) == ("httpx", "boto3")


def test_cognitive_adr_locks_ownership_retrieval_and_hindsight_boundaries() -> None:
    adr = ADR_PATH.read_text(encoding="utf-8")

    for term in (
        "Postgres alone owns lifecycle",
        "confidence from 0 to 1 is not authority",
        "suggestion/fact lifecycle",
        "Qdrant dense plus sparse",
        "optional Graphiti",
        "context_building",
        "separate ADR",
    ):
        assert term in adr
    assert "new global layer directories" in adr
    assert "Hindsight adapter or dependency" in adr
