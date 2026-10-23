"""Capture/check the approved canonical persistence relocation, without database I/O."""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import builtins
import dis
import hashlib
import importlib
import inspect
import json
import pickle
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for package in sorted((ROOT / "packages").iterdir()):
    if package.is_dir():
        sys.path.insert(0, str(package))

PREFIX = "infinity_context_adapters.postgres."
ORIGINAL = PREFIX + "unit_of_work"
BASE = "b0b87bd774f93c2bca9bec14c0efc072a2ba2de8"
COMPATIBILITY = (
    "_ADDITIVE_SCHEMA_COLUMNS",
    "_LEGACY_PROFILE_ID_TABLES",
    "_column_names",
    "_ensure_legacy_profile_schema",
    "_copy_legacy_profiles_to_memory_scopes",
    "_repoint_legacy_profile_references",
    "_repoint_scalar_scope_column",
    "_repoint_token_scope_json",
    "_decode_json_string_list",
    "_rename_or_backfill_legacy_column",
    "_ensure_additive_schema_columns",
    "_ensure_document_thread_unique_indexes",
    "_rebuild_sqlite_memory_documents_without_legacy_unique",
    "_sqlite_memory_documents_table_sql_has_legacy_unique",
)
RUNTIME = (
    "create_schema",
    "_ensure_runtime_schema",
    "_backfill_memory_fact_temporal_columns",
    "_ensure_memory_fact_temporal_indexes",
    "_ensure_memory_fact_supersession_indexes",
    "_ensure_memory_fact_code_scope_indexes",
    "_ensure_managed_benchmark_writer_fence",
    "_ensure_outbox_lifecycle_indexes",
    "_ensure_capture_indexes",
    "_ensure_suggestion_metadata_indexes",
    "_expire_duplicate_pending_suggestions_before_unique_indexes",
)
UNCHANGED = (
    "_BENCHMARK_WRITER_FENCE_MESSAGE",
    "_is_benchmark_writer_fence_error",
    "build_async_engine",
    "build_session_factory",
    "PostgresUnitOfWork",
    "PostgresUnitOfWorkFactory",
)
OWNERS = {name: PREFIX + "schema_compatibility" for name in COMPATIBILITY}
OWNERS.update({name: PREFIX + "schema_runtime" for name in RUNTIME})
OWNERS.update({name: ORIGINAL for name in UNCHANGED})
SLICE = "l1"
REPOSITORY_OWNERS = {
    "_keyword_search_statement": PREFIX + "document_repositories",
    "PostgresDocumentRepository": PREFIX + "document_repositories",
    "PostgresChunkRepository": PREFIX + "document_repositories",
    "PostgresAnchorRepository": PREFIX + "anchor_repositories",
    "PostgresEpisodeRepository": PREFIX + "episode_repositories",
    "PostgresCaptureRepository": PREFIX + "capture_repositories",
    "PostgresSuggestionRepository": PREFIX + "suggestion_repositories",
}
TRACE = (
    "_ensure_legacy_profile_schema",
    "metadata.create_all",
    "seed_retrieval_schema_singletons",
    "ensure_benchmark_projection_manifest_schema",
    "_ensure_additive_schema_columns",
    "_backfill_memory_fact_temporal_columns",
    "_ensure_memory_fact_temporal_indexes",
    "_ensure_memory_fact_code_scope_indexes",
    "_ensure_memory_fact_supersession_indexes",
    "_ensure_document_thread_unique_indexes",
    "_ensure_outbox_lifecycle_indexes",
    "_ensure_capture_indexes",
    "_ensure_suggestion_metadata_indexes",
    "ensure_canonical_keyword_trigram_access_path",
    "_ensure_managed_benchmark_writer_fence",
)


def reference(value: object) -> str:
    module = value.__module__
    name = value.__qualname__
    # L2 deliberately changes these existing UoW dependencies' canonical modules.
    if SLICE == "l1" and REPOSITORY_OWNERS.get(name.split(".")[0]) == module:
        module = PREFIX + "repositories"
    if module == ORIGINAL and name.split(".")[0] in OWNERS:
        module = OWNERS[name.split(".")[0]]
    return f"{module}.{name}"


def describe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): describe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [describe(item) for item in value]
    if isinstance(value, types.ModuleType):
        return {"module": value.__name__}
    if inspect.isclass(value) or inspect.isfunction(value):
        return {"reference": reference(value)}
    return {"repr": repr(value)}


def global_names(code: types.CodeType) -> set[str]:
    names = {op.argval for op in dis.get_instructions(code) if op.opname == "LOAD_GLOBAL"}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names.update(global_names(value))
    return names


def functions(value: object) -> dict[str, object]:
    if inspect.isfunction(value):
        return {"": value}
    if inspect.isclass(value):
        return {name: item for name, item in vars(value).items() if inspect.isfunction(item)}
    return {}


def contract(value: object) -> dict[str, object]:
    entries = {}
    for name, function in functions(value).items():
        bindings = {}
        for global_name in sorted(global_names(function.__code__)):
            binding = function.__globals__.get(global_name, getattr(builtins, global_name, None))
            assert global_name in function.__globals__ or hasattr(builtins, global_name), (
                global_name
            )
            bindings[global_name] = describe(binding)
        entries[name] = {
            "signature": str(inspect.signature(function)),
            "annotations": {key: describe(item) for key, item in get_type_hints(function).items()},
            "doc": function.__doc__,
            "globals": bindings,
        }
    if entries:
        return {"name": value.__name__, "qualname": value.__qualname__, "methods": entries}
    return {"value": describe(value)}


def source_nodes(module_name: str) -> dict[str, ast.AST]:
    module = importlib.import_module(module_name)
    nodes = {}
    for node in ast.parse(Path(module.__file__).read_text()).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes[node.name] = node
        elif isinstance(node, ast.Assign) and not isinstance(node.value, ast.Name):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    nodes[target.id] = node
    return nodes


def fingerprint(node: ast.AST) -> str:
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def operation_trace(callback) -> list[str]:
    trace = []

    def recorder(name):
        return lambda _connection: trace.append(name)

    replacements = {name: recorder(name) for name in TRACE if name != "metadata.create_all"}
    replacements["load_schema_metadata"] = lambda: types.SimpleNamespace(
        create_all=recorder("metadata.create_all")
    )
    with patch.dict(callback.__globals__, replacements):
        callback(object())
    return trace


async def session_contract(module) -> None:
    class Session:
        async def rollback(self):
            pass

        async def close(self):
            pass

    class Clock:
        calls = 0

        def now(self):
            self.calls += 1
            return datetime(2026, 10, 23, tzinfo=UTC)

    session, clock = Session(), Clock()
    async with module.PostgresUnitOfWork(session_factory=lambda: session, clock=clock) as uow:
        repositories = (
            "benchmark_runs",
            "scope",
            "users",
            "facts",
            "fact_relations",
            "assets",
            "asset_extractions",
            "context_links",
            "context_link_suggestions",
            "anchors",
            "episodes",
            "documents",
            "chunks",
            "captures",
            "suggestions",
            "suggestion_resolution_receipts",
            "usage",
            "idempotency",
            "outbox",
        )
        assert all(getattr(uow, name)._session is session for name in repositories)
        assert clock.calls == 1
        assert uow.facts._now is uow.idempotency._now is uow.outbox._now


def capture(path: Path) -> None:
    module = importlib.import_module(ORIGINAL)
    relative = Path(module.__file__).relative_to(ROOT)
    pinned = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=ROOT)
    assert pinned == Path(module.__file__).read_bytes(), "Production source changed before capture"
    nodes = source_nodes(ORIGINAL)
    expected = set(OWNERS) - {"PostgresIdempotencyRepository", "PostgresOutbox"}
    assert set(nodes) == expected, "Every original definition must have one reviewed owner"
    definitions = {}
    for name in OWNERS:
        value = getattr(module, name)
        source_module = value.__module__ if functions(value) else ORIGINAL
        definitions[name] = fingerprint(source_nodes(source_module)[name])
    payload = {
        "base": BASE,
        "checkout_base": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "original": ORIGINAL,
        "owners": OWNERS,
        "source_sha256": hashlib.sha256(pinned).hexdigest(),
        "definitions": definitions,
        "contracts": {name: contract(getattr(module, name)) for name in OWNERS},
        "operation_trace": operation_trace(module._ensure_runtime_schema) if SLICE == "l1" else [],
        "legacy_pickles": {
            name: base64.b64encode(pickle.dumps(getattr(module, name))).decode()
            for name in OWNERS
            if functions(getattr(module, name))
        },
    }
    assert payload["operation_trace"] == (list(TRACE) if SLICE == "l1" else [])
    assert not path.exists(), "Never replace the unchanged-source evidence"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    asyncio.run(session_contract(importlib.import_module(PREFIX + "unit_of_work")))
    print(f"captured {len(OWNERS)} definitions; slice {SLICE} contracts and session lifetime")


def check(path: Path) -> None:
    payload = json.loads(path.read_text())
    assert payload["base"] == BASE and payload["owners"] == OWNERS
    original = importlib.import_module(ORIGINAL)
    modules = {owner: importlib.import_module(owner) for owner in set(OWNERS.values())}
    nodes = {name: source_nodes(name) for name in modules}
    for name, owner in OWNERS.items():
        value = getattr(modules[owner], name)
        assert getattr(original, name) is value, f"legacy alias: {name}"
        assert fingerprint(nodes[owner][name]) == payload["definitions"][name], f"body: {name}"
        assert contract(value) == payload["contracts"][name], f"binding/contract: {name}"
        assert sum(name in definitions for definitions in nodes.values()) == 1, name
        if inspect.isfunction(value) or inspect.isclass(value):
            assert value.__module__ == owner, f"canonical owner: {name}"
        for function in functions(value).values():
            for global_name in global_names(function.__code__):
                bound = function.__globals__.get(global_name, getattr(builtins, global_name, None))
                if global_name in OWNERS:
                    expected = getattr(modules[OWNERS[global_name]], global_name)
                    assert bound is expected, f"relocated dependency: {name}.{global_name}"
                elif inspect.isclass(bound) or inspect.isfunction(bound):
                    canonical = importlib.import_module(bound.__module__)
                    if "." not in bound.__qualname__:
                        assert getattr(canonical, bound.__qualname__) is bound, global_name
    for name, encoded in payload["legacy_pickles"].items():
        assert pickle.loads(base64.b64decode(encoded)) is getattr(original, name)
    if SLICE == "l1":
        callback = original.create_schema.__globals__["_ensure_runtime_schema"]
        assert callback is original._ensure_runtime_schema
        assert operation_trace(callback) == payload["operation_trace"] == list(TRACE)
    for owner in modules.keys() - {ORIGINAL}:
        tree = ast.parse(Path(modules[owner].__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in {ORIGINAL, PREFIX + "repositories"}, owner
            elif isinstance(node, ast.Import):
                assert all(
                    item.name not in {ORIGINAL, PREFIX + "repositories"} for item in node.names
                )
    asyncio.run(session_contract(importlib.import_module(PREFIX + "unit_of_work")))
    for order in ((ORIGINAL, *modules), (*reversed(modules), ORIGINAL)):
        paths = [str(package) for package in sorted((ROOT / "packages").iterdir())]
        code = f"import importlib, sys; sys.path[:0] = {paths!r};"
        code += ";".join(
            f"assert importlib.import_module({name!r}).__file__.startswith({str(ROOT)!r})"
            for name in order
        )
        subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT)
    print(
        f"verified {len(OWNERS)} bodies/bindings/aliases/hints; schema trace and session lifetime"
    )


def main() -> None:
    global ORIGINAL, OWNERS, SLICE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "check"))
    parser.add_argument("--slice", choices=("l1", "l2"), required=True)
    args = parser.parse_args()
    SLICE = args.slice
    if SLICE == "l2":
        ORIGINAL = PREFIX + "repositories"
        OWNERS = {
            **REPOSITORY_OWNERS,
            "PostgresIdempotencyRepository": PREFIX + "record_repositories",
            "PostgresOutbox": PREFIX + "record_repositories",
        }
    path = ROOT / f"tests/fixtures/canonical_persistence_refactor/{SLICE}_contract.json"
    {"capture": capture, "check": check}[args.mode](path)


if __name__ == "__main__":
    main()
