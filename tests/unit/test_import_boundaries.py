import ast
import importlib
import importlib.abc
import pkgutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_ROOT = (
    PROJECT_ROOT / "packages" / "infinity_context_contracts" / "infinity_context_contracts"
)
CORE_ROOT = PROJECT_ROOT / "packages" / "infinity_context_core" / "infinity_context_core"

PROVIDER_OR_INFRASTRUCTURE_IMPORTS = frozenset(
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

CLIENT_APP_IMPORTS = frozenset(
    {
        "infinity_context_adapters",
        "infinity_context_cli",
        "infinity_context_mcp",
        "infinity_context_obsidian",
        "infinity_context_sdk",
        "infinity_context_server",
    }
)

FORBIDDEN_IN_CORE = PROVIDER_OR_INFRASTRUCTURE_IMPORTS | CLIENT_APP_IMPORTS
FORBIDDEN_IN_CONTRACTS = FORBIDDEN_IN_CORE | frozenset(
    {
        "alembic",
        "docling",
        "faster_whisper",
        "infinity_context_core",
        "infinity_context_obsidian_plugin",
    }
)


def imports_for_file(path: Path) -> list[tuple[str, int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int, str]] = []
    importlib_aliases = {"importlib"}
    import_module_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno, "import"))
                if alias.name == "importlib":
                    importlib_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            from_modules = _import_from_modules(path, node)
            for module in from_modules:
                imports.append((module, node.lineno, "from"))
            if from_modules and from_modules[0] == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Call):
            dynamic_module = _dynamic_import_module(node, importlib_aliases, import_module_aliases)
            if dynamic_module is not None:
                imports.append((dynamic_module, node.lineno, "dynamic"))

    return imports


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


def _matches_prefix(module: str, prefixes: frozenset[str]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


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

    imported_modules = {module for module, _, _ in imports_for_file(path)}

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

    imported_modules = {module for module, _, _ in imports_for_file(path)}

    assert "infinity_context_server.eval" in imported_modules


def test_memory_core_has_no_infrastructure_or_client_app_imports() -> None:
    violations: list[str] = []
    for path in sorted(CORE_ROOT.rglob("*.py")):
        for module, line, kind in imports_for_file(path):
            if _matches_prefix(module, FORBIDDEN_IN_CORE):
                violations.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line}: {kind} import references {module}"
                )

    assert violations == []


def test_core_modules_import_with_forbidden_runtime_packages_blocked() -> None:
    saved_core_modules = _remove_loaded_modules("infinity_context_core")
    blocker = _ForbiddenImportBlocker(FORBIDDEN_IN_CORE)
    sys.meta_path.insert(0, blocker)
    try:
        core_package = importlib.import_module("infinity_context_core")
        for module_info in pkgutil.walk_packages(
            core_package.__path__,
            core_package.__name__ + ".",
        ):
            importlib.import_module(module_info.name)
    finally:
        sys.meta_path.remove(blocker)
        _remove_loaded_modules("infinity_context_core")
        sys.modules.update(saved_core_modules)


class _ForbiddenImportBlocker(importlib.abc.MetaPathFinder):
    def __init__(self, forbidden_prefixes: frozenset[str]) -> None:
        self._forbidden_prefixes = forbidden_prefixes

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        if _matches_prefix(fullname, self._forbidden_prefixes):
            raise AssertionError(f"blocked forbidden runtime import from core: {fullname}")
        return None


def _remove_loaded_modules(package_name: str) -> dict[str, object]:
    removed = {
        name: module
        for name, module in sys.modules.items()
        if name == package_name or name.startswith(f"{package_name}.")
    }
    for name in removed:
        sys.modules.pop(name, None)
    return removed


def test_capability_contracts_are_importable_without_provider_adapters() -> None:
    import infinity_context_core.ports.capabilities as capabilities  # noqa: PLC0415

    assert capabilities.MemoryCapability.TEMPORAL_FACT_GRAPH == "temporal_fact_graph"
    assert capabilities.ConsistencyMode.REQUIRE_FRESH_PROJECTION == "require_fresh_projection"


def test_contracts_package_is_importable_without_runtime_layers() -> None:
    import infinity_context_contracts as contracts  # noqa: PLC0415

    assert CONTRACTS_ROOT.is_dir()
    assert contracts.__version__ == "0.1.0"
    assert contracts.HealthResponseDto(status="ok", service="test", deploy_profile="test")


def test_contracts_modules_import_with_forbidden_runtime_packages_blocked() -> None:
    saved_contract_modules = _remove_loaded_modules("infinity_context_contracts")
    blocker = _ForbiddenImportBlocker(FORBIDDEN_IN_CONTRACTS)
    sys.meta_path.insert(0, blocker)
    try:
        contracts_package = importlib.import_module("infinity_context_contracts")
        for module_info in pkgutil.walk_packages(
            contracts_package.__path__,
            contracts_package.__name__ + ".",
        ):
            importlib.import_module(module_info.name)
    finally:
        sys.meta_path.remove(blocker)
        _remove_loaded_modules("infinity_context_contracts")
        sys.modules.update(saved_contract_modules)


def test_routes_do_not_import_provider_adapter_packages() -> None:
    api_root = (
        PROJECT_ROOT / "packages" / "infinity_context_server" / "infinity_context_server" / "api"
    )
    forbidden_prefixes = frozenset({"infinity_context_adapters", "sqlalchemy"})
    forbidden_calls = {"AsyncSession", "create_engine", "create_async_engine"}

    imported_modules: set[str] = set()
    direct_db_calls: set[str] = set()
    for path in api_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.update(_import_from_modules(path, node))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in forbidden_calls
            ):
                direct_db_calls.add(node.func.id)

    forbidden_imports = {
        module for module in imported_modules if _matches_prefix(module, forbidden_prefixes)
    }

    assert forbidden_imports == set()
    assert direct_db_calls == set()


def test_routes_do_not_use_unit_of_work_directly() -> None:
    api_root = (
        PROJECT_ROOT / "packages" / "infinity_context_server" / "infinity_context_server" / "api"
    )
    offenders = []
    for path in api_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "uow_factory":
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
                break
            if isinstance(node, ast.Attribute) and node.attr == "uow_factory":
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
                break

    assert offenders == []


def test_sdk_imports_without_provider_adapters() -> None:
    from infinity_context_sdk import InfinityContextClient  # noqa: PLC0415

    assert InfinityContextClient().base_url == "http://127.0.0.1:7788"
