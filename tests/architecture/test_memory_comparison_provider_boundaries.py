"""Keep official benchmark policy independent from the OpenAI HTTP adapter."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "packages/infinity_context_server/infinity_context_server"
PROVIDER_NEUTRAL_FILES = (
    "memory_comparison_provider_provenance.py",
    "memory_comparison_mem0_official_prompt_renderer.py",
    "memory_comparison_mem0_locomo_prompts.py",
    "memory_comparison_mem0_longmemeval_prompts.py",
)


def test_provider_neutral_official_contract_has_no_transport_dependency() -> None:
    forbidden = {"httpx", "openai", "requests", "fastapi"}
    violations: list[str] = []
    for filename in PROVIDER_NEUTRAL_FILES:
        path = SERVER / filename
        for imported in _imports(path):
            if imported.split(".", 1)[0] in forbidden:
                violations.append(f"{filename}: imports {imported}")
    assert not violations, "Provider boundary violations:\n" + "\n".join(violations)


def test_generic_provenance_has_no_openai_route_policy_details() -> None:
    path = SERVER / "memory_comparison_provider_provenance.py"
    source = path.read_text(encoding="utf-8").casefold()

    assert "openai" not in source
    assert "api.openai.com" not in source
    assert "chatcmpl-" not in source
    assert "fp_" not in source
    assert "urllib.parse" not in _imports(path)


def test_only_openai_http_adapter_owns_httpx_in_official_slice() -> None:
    chat_imports = _imports(SERVER / "memory_comparison_mem0_official_chat.py")
    transport_imports = _imports(
        SERVER / "memory_comparison_openai_official_transport.py"
    )

    assert "httpx" not in chat_imports
    assert "httpx" in transport_imports
    assert "openai" not in {item.split(".", 1)[0] for item in transport_imports}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported
