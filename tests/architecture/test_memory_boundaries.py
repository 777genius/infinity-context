"""Static architecture checks for Infinity Context package boundaries."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PROVIDER_OR_INFRASTRUCTURE_IMPORT_PREFIXES = frozenset(
    {
        "anthropic",
        "asyncpg",
        "boto3",
        "botocore",
        "cognee",
        "fastapi",
        "graphiti",
        "graphiti_core",
        "httpx",
        "mcp",
        "neo4j",
        "openai",
        "pydantic_settings",
        "qdrant_client",
        "sqlalchemy",
        "uvicorn",
    }
)

CLIENT_APP_IMPORT_PREFIXES = frozenset(
    {
        "infinity_context_adapters",
        "infinity_context_cli",
        "infinity_context_mcp",
        "infinity_context_obsidian",
        "infinity_context_sdk",
        "infinity_context_server",
    }
)

CORE_FORBIDDEN_IMPORT_PREFIXES = (
    PROVIDER_OR_INFRASTRUCTURE_IMPORT_PREFIXES | CLIENT_APP_IMPORT_PREFIXES
)

CONTRACTS_FORBIDDEN_IMPORT_PREFIXES = (
    CORE_FORBIDDEN_IMPORT_PREFIXES
    | frozenset(
        {
            "alembic",
            "docling",
            "faster_whisper",
            "infinity_context_core",
            "infinity_context_obsidian_plugin",
        }
    )
)

ALLOWED_MCP_DYNAMIC_IMPORTS = frozenset(
    {
        (
            "packages/infinity_context_mcp/infinity_context_mcp/agent_behavior_bench.py",
            "openai",
        ),
    }
)


@dataclass(frozen=True)
class ImportReference:
    module: str
    line: int
    kind: str


def _python_files(package: str) -> list[Path]:
    return sorted((REPO_ROOT / package).rglob("*.py"))


def _imports(path: Path) -> list[ImportReference]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[ImportReference] = []
    importlib_aliases = {"importlib"}
    import_module_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(ImportReference(alias.name, node.lineno, "import"))
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            from_modules = _import_from_modules(path, node)
            for module in from_modules:
                imported.append(ImportReference(module, node.lineno, "from"))
            if from_modules and from_modules[0] == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Call):
            dynamic_module = _dynamic_import_module(
                node,
                importlib_aliases,
                import_module_aliases,
            )
            if dynamic_module is not None:
                imported.append(ImportReference(dynamic_module, node.lineno, "dynamic"))

    return imported


def _import_from_modules(path: Path, node: ast.ImportFrom) -> list[str]:
    base_module = _resolve_import_from_base(path, node)
    modules: list[str] = []
    if base_module:
        modules.append(base_module)

    for alias in node.names:
        if alias.name == "*":
            continue
        modules.append(f"{base_module}.{alias.name}" if base_module else alias.name)

    return list(dict.fromkeys(modules))


def _resolve_import_from_base(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    package = _package_context_for_path(path)
    if not package:
        return node.module or ""

    package_parts = package.split(".")
    parent_count = node.level - 1
    if parent_count > len(package_parts):
        return node.module or ""

    resolved_base = ".".join(package_parts[: len(package_parts) - parent_count])
    if node.module:
        return f"{resolved_base}.{node.module}" if resolved_base else node.module
    return resolved_base


def _package_context_for_path(path: Path) -> str:
    module = _module_name_for_path(path)
    if path.name == "__init__.py":
        return module
    return module.rsplit(".", 1)[0] if "." in module else ""


def _module_name_for_path(path: Path) -> str:
    parts = path.parts
    for index, part in enumerate(parts):
        if part == "packages" and index + 2 < len(parts):
            module_parts = list(parts[index + 2 :])
            break
    else:
        module_parts = [path.name]

    if module_parts[-1] == "__init__.py":
        module_parts = module_parts[:-1]
    else:
        module_parts[-1] = Path(module_parts[-1]).stem

    return ".".join(module_parts)


def _dynamic_import_module(
    node: ast.Call,
    importlib_aliases: set[str],
    import_module_aliases: set[str],
) -> str | None:
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    if not isinstance(node.args[0].value, str):
        return None

    func = node.func
    if isinstance(func, ast.Name) and func.id in ({"__import__"} | import_module_aliases):
        return node.args[0].value
    if (
        isinstance(func, ast.Attribute)
        and func.attr in {"find_spec", "import_module"}
        and isinstance(func.value, ast.Name)
        and func.value.id in importlib_aliases
    ):
        return node.args[0].value
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "find_spec"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "util"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id in importlib_aliases
    ):
        return node.args[0].value
    return None


def _assert_no_imports(
    package: str,
    forbidden_prefixes: frozenset[str],
    *,
    allowed_dynamic_imports: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    violations: list[str] = []
    for path in _python_files(package):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for imported in sorted(
            _imports(path),
            key=lambda item: (item.module, item.line, item.kind),
        ):
            if (
                imported.kind == "dynamic"
                and (rel, imported.module) in allowed_dynamic_imports
            ):
                continue
            if _matches_prefix(imported.module, forbidden_prefixes):
                violations.append(
                    f"{rel}:{imported.line}: {imported.kind} import references "
                    f"{imported.module}"
                )

    assert not violations, "Forbidden architecture imports:\n" + "\n".join(violations)


def _assert_file_no_imports(relative_path: str, forbidden_prefixes: frozenset[str]) -> None:
    path = REPO_ROOT / relative_path
    violations = []
    for imported in sorted(
        _imports(path),
        key=lambda item: (item.module, item.line, item.kind),
    ):
        if _matches_prefix(imported.module, forbidden_prefixes):
            violations.append(
                f"{path.relative_to(REPO_ROOT)}:{imported.line}: "
                f"{imported.kind} import references {imported.module}"
            )

    assert not violations, "Forbidden architecture imports:\n" + "\n".join(violations)


def _matches_prefix(module: str, forbidden_prefixes: frozenset[str]) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in forbidden_prefixes
    )


def test_import_scanner_resolves_relative_import_from_modules(tmp_path: Path) -> None:
    path = (
        tmp_path
        / "packages"
        / "infinity_context_core"
        / "infinity_context_core"
        / "domain"
        / "policy.py"
    )
    path.parent.mkdir(parents=True)
    path.write_text("from ..application import dto as app_dto\n", encoding="utf-8")

    imported_modules = {reference.module for reference in _imports(path)}

    assert "infinity_context_core.application" in imported_modules
    assert "infinity_context_core.application.dto" in imported_modules


def test_import_scanner_expands_imported_aliases_for_from_imports(tmp_path: Path) -> None:
    path = (
        tmp_path
        / "packages"
        / "infinity_context_server"
        / "infinity_context_server"
        / "top_evidence_policy.py"
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        "from infinity_context_server import eval as eval_module\n",
        encoding="utf-8",
    )

    imported_modules = {reference.module for reference in _imports(path)}

    assert "infinity_context_server.eval" in imported_modules


def test_memory_core_has_no_infrastructure_or_client_app_dependencies() -> None:
    _assert_no_imports(
        "packages/infinity_context_core/infinity_context_core",
        CORE_FORBIDDEN_IMPORT_PREFIXES,
    )


def test_contracts_package_has_no_infrastructure_or_client_app_dependencies() -> None:
    package = "packages/infinity_context_contracts/infinity_context_contracts"

    assert (REPO_ROOT / package).is_dir()
    _assert_no_imports(package, CONTRACTS_FORBIDDEN_IMPORT_PREFIXES)


def test_memory_adapters_do_not_depend_on_api_or_mcp_layers() -> None:
    _assert_no_imports(
        "packages/infinity_context_adapters/infinity_context_adapters",
        frozenset(
            {
                "fastapi",
                "infinity_context_mcp",
                "infinity_context_server",
                "mcp",
            }
        ),
    )


def test_core_application_does_not_reach_around_ports_to_adapters() -> None:
    _assert_no_imports(
        "packages/infinity_context_core/infinity_context_core/application",
        frozenset(
            {
                "infinity_context_adapters",
                "infinity_context_cli",
                "infinity_context_mcp",
                "infinity_context_obsidian",
                "infinity_context_sdk",
                "infinity_context_server",
            }
        ),
    )


def test_core_domain_does_not_import_application_layer() -> None:
    _assert_no_imports(
        "packages/infinity_context_core/infinity_context_core/domain",
        frozenset({"infinity_context_core.application"}),
    )


def test_core_ports_do_not_import_application_layer() -> None:
    _assert_no_imports(
        "packages/infinity_context_core/infinity_context_core/ports",
        frozenset({"infinity_context_core.application"}),
    )


def test_memory_mcp_does_not_depend_on_server_adapters_or_providers() -> None:
    _assert_no_imports(
        "packages/infinity_context_mcp/infinity_context_mcp",
        frozenset(
            {
                "anthropic",
                "fastapi",
                "graphiti",
                "graphiti_core",
                "infinity_context_adapters",
                "infinity_context_server",
                "openai",
                "qdrant_client",
                "sqlalchemy",
            }
        ),
        allowed_dynamic_imports=ALLOWED_MCP_DYNAMIC_IMPORTS,
    )


def test_memory_server_does_not_depend_on_mcp_adapter_layer() -> None:
    _assert_no_imports(
        "packages/infinity_context_server/infinity_context_server",
        frozenset(
            {
                "mcp",
                "infinity_context_mcp",
            }
        ),
    )


def test_top_evidence_policy_stays_lightweight() -> None:
    _assert_file_no_imports(
        "packages/infinity_context_server/infinity_context_server/top_evidence_policy.py",
        frozenset(
            {
                "anthropic",
                "fastapi",
                "graphiti",
                "graphiti_core",
                "httpx",
                "infinity_context_adapters",
                "infinity_context_mcp",
                "infinity_context_server.eval",
                "infinity_context_server.main",
                "mcp",
                "openai",
                "qdrant_client",
                "sqlalchemy",
            }
        ),
    )


def test_memory_sdk_stays_transport_client_only() -> None:
    _assert_no_imports(
        "packages/infinity_context_sdk/infinity_context_sdk",
        frozenset(
            {
                "anthropic",
                "fastapi",
                "graphiti",
                "graphiti_core",
                "infinity_context_adapters",
                "infinity_context_core",
                "infinity_context_mcp",
                "infinity_context_server",
                "mcp",
                "openai",
                "qdrant_client",
                "sqlalchemy",
            }
        ),
    )
