import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURE = ROOT / ("packages/infinity_context_core/infinity_context_core/features/context_building")
CORE_FILES = (
    FEATURE / "domain/retrieval_profile_lifecycle.py",
    FEATURE / "ports/retrieval_profile_lifecycle.py",
    FEATURE / "application/retrieval_profile_lifecycle.py",
)
FORBIDDEN_ROOTS = {
    "fastapi",
    "sqlalchemy",
    "qdrant_client",
    "infinity_context_adapters",
    "infinity_context_server",
}


def test_profile_lifecycle_core_has_no_framework_or_provider_dependencies() -> None:
    violations = []
    for path in CORE_FILES:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".", 1)[0] in FORBIDDEN_ROOTS:
                    violations.append(f"{path.name}:{name}")
    assert violations == []


def test_profile_lifecycle_provider_types_remain_in_adapters() -> None:
    combined = "\n".join(path.read_text() for path in CORE_FILES)
    assert "Qdrant" not in combined
    assert "AsyncSession" not in combined
    assert "FastAPI" not in combined
