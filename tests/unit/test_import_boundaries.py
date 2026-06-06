import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = PROJECT_ROOT / "packages" / "memo_stack_core" / "memo_stack_core"

FORBIDDEN_IN_CORE = {
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
    "asyncpg",
    "uvicorn",
    "memo_stack_adapters",
    "memo_stack_server",
}


def imports_for_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", maxsplit=1)[0])
    return imports


def test_memory_core_has_no_infrastructure_imports() -> None:
    found: set[str] = set()
    for path in CORE_ROOT.rglob("*.py"):
        found.update(imports_for_file(path) & FORBIDDEN_IN_CORE)

    assert found == set()


def test_capability_contracts_are_importable_without_provider_adapters() -> None:
    import memo_stack_core.ports.capabilities as capabilities  # noqa: PLC0415

    assert capabilities.MemoryCapability.TEMPORAL_FACT_GRAPH == "temporal_fact_graph"
    assert capabilities.ConsistencyMode.REQUIRE_FRESH_PROJECTION == "require_fresh_projection"


def test_routes_do_not_import_provider_adapter_packages() -> None:
    api_root = PROJECT_ROOT / "packages" / "memo_stack_server" / "memo_stack_server" / "api"
    forbidden_prefixes = ("memo_stack_adapters", "sqlalchemy")
    forbidden_calls = {"AsyncSession", "create_engine", "create_async_engine"}

    imported_modules: set[str] = set()
    direct_db_calls: set[str] = set()
    for path in api_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in forbidden_calls
            ):
                direct_db_calls.add(node.func.id)

    forbidden_imports = {
        module
        for module in imported_modules
        if module.startswith(forbidden_prefixes)
    }

    assert forbidden_imports == set()
    assert direct_db_calls == set()


def test_routes_do_not_use_unit_of_work_directly() -> None:
    api_root = PROJECT_ROOT / "packages" / "memo_stack_server" / "memo_stack_server" / "api"
    offenders = []
    for path in api_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "uow_factory" in source:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == []


def test_sdk_imports_without_provider_adapters() -> None:
    from memo_stack_sdk import MemoStackClient  # noqa: PLC0415

    assert MemoStackClient().base_url == "http://127.0.0.1:7788"
