"""Bounded static ownership analysis, extending the existing architecture helpers.

This is a source guard, not a proof of arbitrary Python dynamic reachability.
It follows imports/reexports, ordinary assignment aliases and local helper calls.
Reflection, runtime monkeypatches and external consumers require separate review.
No application modules are imported or executed by this analysis.
"""

from __future__ import annotations

import ast
from pathlib import Path

from test_feature_owned_vertical_slices import (
    REPO_ROOT,
    _resolve_import_from,
    _server_route_modules,
)

CORE = "infinity_context_core"
SERVER = "infinity_context_server"
ADAPTERS = "infinity_context_adapters"
CONTAINER = f"{SERVER}.composition.Container"


def module_name(path: Path) -> str:
    parts = path.relative_to(REPO_ROOT / "packages").with_suffix("").parts[1:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def dotted(node: ast.AST | None, bindings: dict[str, str]) -> str:
    if isinstance(node, ast.Subscript):
        item = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
        return dotted(item, bindings)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return dotted(node.left, bindings)
    if isinstance(node, ast.Name):
        return bindings.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = dotted(node.value, bindings)
        return f"{base}.{node.attr}" if base else ""
    if isinstance(node, ast.Call):
        target = dotted(node.func, bindings)
        if target.endswith(".get_container"):
            return "$container"
        return target if target.rsplit(".", 1)[-1][:1].isupper() else ""
    if isinstance(node, ast.Await):
        return dotted(node.value, bindings)
    return ""


class SourceIndex:
    """Resolve static Python symbols including lazy factories and public reexports."""

    def __init__(self, sources: dict[Path, str]) -> None:
        self.trees = {path: ast.parse(source) for path, source in sources.items()}
        self.paths = {module_name(path): path for path in sources}
        self.bindings: dict[str, dict[str, str]] = {}
        for path, tree in self.trees.items():
            module = module_name(path)
            bindings = {}
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    bindings[node.name] = f"{module}.{node.name}"
                self.import_binding(path, node, bindings)
            self.bindings[module] = bindings
        # Composition's existing explicit export shim uses a star import. Expand
        # only statically indexed names, never evaluate __all__ or import code.
        for path, tree in self.trees.items():
            bindings = self.bindings[module_name(path)]
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                    target = _resolve_import_from(path, node)
                    bindings.update(self.bindings.get(target or "", {}))

    @staticmethod
    def import_binding(path: Path, node: ast.AST, bindings: dict[str, str]) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, node)
            if module:
                for alias in node.names:
                    if alias.name != "*":
                        bindings[alias.asname or alias.name] = f"{module}.{alias.name}"

    def resolve(self, symbol: str) -> str:
        seen = set()
        while symbol not in seen:
            seen.add(symbol)
            parts = symbol.split(".")
            replacement = symbol
            for end in range(len(parts) - 1, 0, -1):
                module = ".".join(parts[:end])
                target = self.bindings.get(module, {}).get(parts[end])
                if target:
                    replacement = ".".join([target, *parts[end + 1 :]])
                    break
            if replacement == symbol:
                break
            symbol = replacement
        return symbol

    def fields(self, path: Path, class_name: str) -> dict[str, str]:
        bindings = self.bindings[module_name(path)]
        cls = next(
            n for n in self.trees[path].body if isinstance(n, ast.ClassDef) and n.name == class_name
        )
        return {
            node.target.id: self.resolve(dotted(node.annotation, bindings))
            for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }

    def calls(self, path: Path) -> list[tuple[str, str, tuple[str, ...]]]:
        """Return lexical caller, call target, and statically named arguments.

        Function scopes get independent bindings. A conservative union of calls
        in both branches is intentional: configuration must not hide a new owner.
        """
        result = []
        module = module_name(path)
        index = self

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.bindings = dict(index.bindings[module])
                self.scope = module

            def visit_Import(self, node: ast.Import) -> None:
                index.import_binding(path, node, self.bindings)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                index.import_binding(path, node, self.bindings)

            def symbol(self, node: ast.AST | None) -> str:
                return index.resolve(dotted(node, self.bindings))

            def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                for value in (
                    *node.decorator_list,
                    *node.args.defaults,
                    *(v for v in node.args.kw_defaults if v is not None),
                ):
                    self.visit(value)
                previous, scope = self.bindings, self.scope
                self.bindings = dict(previous)
                self.scope = f"{scope}.{node.name}"
                for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                    annotation = self.symbol(arg.annotation)
                    if annotation == CONTAINER:
                        self.bindings[arg.arg] = "$container"
                    elif legacy_owner(annotation) or any(
                        annotation.startswith(f"{module}.") for module in DORMANT_MODULES
                    ):
                        self.bindings[arg.arg] = annotation
                    else:
                        self.bindings[arg.arg] = arg.arg
                for item in node.body:
                    self.visit(item)
                self.bindings, self.scope = previous, scope

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                for value in (
                    *node.decorator_list,
                    *node.bases,
                    *(kw.value for kw in node.keywords),
                ):
                    self.visit(value)
                scope = self.scope
                self.scope = f"{scope}.{node.name}"
                for item in node.body:
                    self.visit(item)
                self.scope = scope

            def visit_Assign(self, node: ast.Assign) -> None:
                self.visit(node.value)
                value = self.symbol(node.value)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.bindings[target.id] = value or target.id

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if node.value:
                    self.visit(node.value)
                if isinstance(node.target, ast.Name) and node.value:
                    self.bindings[node.target.id] = self.symbol(node.value) or node.target.id

            def visit_Call(self, node: ast.Call) -> None:
                arguments = tuple(
                    self.symbol(arg) for arg in (*node.args, *(kw.value for kw in node.keywords))
                )
                result.append((self.scope, self.symbol(node.func), arguments))
                self.generic_visit(node)

        Visitor().visit(self.trees[path])
        return result


def legacy_owner(symbol: str) -> bool:
    return symbol.startswith(f"{CORE}.application.use_cases.") and any(
        part.endswith("UseCase") for part in symbol.split(".")
    )


def require_inventory(actual: set[tuple[str, ...]], recorded: set[tuple[str, ...]]) -> None:
    added, removed = actual - recorded, recorded - actual
    assert not added, f"New execution debt/ownership edges require review: {sorted(added)}"
    assert not removed, (
        f"Migration progressed; explicitly remove stale inventory: {sorted(removed)}"
    )


def route_edges(
    index: SourceIndex, paths: list[Path], fields: dict[str, str]
) -> set[tuple[str, str]]:
    """Executing Container owners, including local forwarding helpers.

    Call arguments count only when they name an owner: this captures the existing
    _execute_fact_command(use_case, command) seam without counting DTO imports.
    """
    edges: set[tuple[str, str]] = set()
    calls = [call for path in paths for call in index.calls(path)]
    for caller, target, arguments in calls:
        for symbol in (target, *arguments):
            if not symbol.startswith("$container."):
                continue
            owner = symbol.removeprefix("$container.")
            field = owner.split(".")[0]
            if field not in fields:
                continue
            if not (legacy_owner(fields[field]) or field in FEATURE_OWNERS):
                continue
            # Retain method identity; forwarded owner is explicitly labelled.
            edges.add((caller, owner))
    # Attribute owner edges to actual decorated entry points through local calls.
    for _ in range(len(calls) + 1):
        previous = set(edges)
        for caller, target, _ in calls:
            edges.update((caller, owner) for origin, owner in previous if origin == target)
        if previous == edges:
            break
    return edges


FEATURE_OWNERS = frozenset(
    {
        "memory_fact_lifecycle",
        "memory_fact_reads",
        "memory_fact_temporal",
        "build_canonical_fact_context",
        "projected_document_ingestion",
        "reconcile_exact_document",
        "locator_retrieval",
    }
)

# Semantic equivalence is deliberate. Locator retrieval, selection/hydration,
# generic relations and temporal mutations are distinct responsibilities.
OVERLAP_TYPES = {
    "RememberFactUseCase": ("MemoryFactLifecycleUseCases", "remember_fact"),
    "UpdateFactUseCase": ("MemoryFactLifecycleUseCases", "update_fact"),
    "ForgetFactUseCase": ("MemoryFactLifecycleUseCases", "forget_fact"),
    "GetFactUseCase": ("MemoryFactReadUseCases", "get_fact"),
    "ListFactsUseCase": ("MemoryFactReadUseCases", "list_facts"),
    "ListFactVersionsUseCase": ("MemoryFactReadUseCases", "list_versions"),
    "BuildContextUseCase": ("BuildContextHandler", ""),
    "IngestDocumentUseCase": ("PostgresProjectedDocumentIngestor", ""),
}


def container_overlaps(fields: dict[str, str]) -> set[tuple[str, str]]:
    pairs = set()
    for name, owner in fields.items():
        if not legacy_owner(owner):
            continue
        counterpart = OVERLAP_TYPES.get(owner.rsplit(".", 1)[-1])
        if counterpart:
            type_name, member = counterpart
            for other, other_type in fields.items():
                if other_type.rsplit(".", 1)[-1] == type_name:
                    pairs.add((name, f"{other}.{member}" if member else other))
    return pairs


def legacy_execution_edges(index: SourceIndex, paths: list[Path]) -> set[tuple[str, str]]:
    """Direct legacy construction/invocation, distinct from error and DTO use."""
    return {
        (caller, symbol)
        for path in paths
        for caller, target, arguments in index.calls(path)
        for symbol in (target, *arguments)
        if legacy_owner(symbol)
    }


def compatibility_imports(index: SourceIndex, path: Path) -> set[str]:
    """Classify resolved legacy DTO/domain/error imports without treating them as owners."""
    return {
        index.resolve(symbol)
        for symbol in index.bindings[module_name(path)].values()
        if index.resolve(symbol).startswith((f"{CORE}.application.dto", f"{CORE}.domain."))
    }


DORMANT_MODULES = frozenset(
    f"{ADAPTERS}.features.{suffix}"
    for suffix in (
        "document_ingestion.postgres_document_store",
        "document_ingestion.qdrant_chunk_index",
        "memory_scopes.postgres_scope_store",
        "memory_facts.qdrant_fact_projection",
        "memory_facts.graphiti_fact_projection",
    )
)


def dormant_edges(index: SourceIndex, paths: list[Path]) -> set[tuple[str, str]]:
    """Forbid calls or injection of scaffold symbols outside their exact modules.

    Factories and internal constructors inside these five modules remain legal.
    Reexports alone are legal. A call into an exported factory, an ordinary alias,
    or passing that factory to production wiring is an execution dependency.
    This deliberately rejects even unmounted new production helper functions.
    """
    return {
        (caller, symbol)
        for path in paths
        for caller, target, arguments in index.calls(path)
        if module_name(path) not in DORMANT_MODULES or caller == module_name(path)
        for symbol in (target, *arguments)
        if any(symbol.startswith(f"{module}.") for module in DORMANT_MODULES)
    }


def index_repository() -> SourceIndex:
    """Index imports with bounded memory; retain trees only for requested scans.

    All package modules contribute reexport bindings. Tests are not production.
    ASTs are parsed one at a time to avoid retaining the repository's large trees.
    """
    index = SourceIndex({})
    for path in sorted((REPO_ROOT / "packages").rglob("*.py")):
        if "tests" in path.relative_to(REPO_ROOT / "packages").parts:
            continue
        module = module_name(path)
        index.paths[module] = path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bindings = {}
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                bindings[node.name] = f"{module}.{node.name}"
            index.import_binding(path, node, bindings)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = dotted(node.value, bindings) or target.id
        index.bindings[module] = bindings
    # Reuse the existing, explicit composition export shim only.
    shim = f"{SERVER}.composition_use_cases"
    index.bindings[shim].update(index.bindings[f"{CORE}.application"])
    index.bindings[f"{SERVER}.composition"].update(index.bindings[shim])
    return index


def load_trees(index: SourceIndex, paths: list[Path]) -> None:
    index.trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in paths}


# The thirteen audited hybrid surfaces, plus their shared scope helper and client
# compatibility entry points. This is scope selection, not thirteen duplicate
# owners. Benchmark-only routes and unrelated feature lanes are not frozen here.
TARGET_ROUTE_MODULES = frozenset(
    {
        "assets",
        "context",
        "context_retrieval",
        "digest",
        "documents",
        "export",
        "facts",
        "insights",
        "memory_browser",
        "operations",
        "spaces_memory_scopes",
        "suggestions",
        "thread_memory",
        "scope_resolution",
        "legacy_client",
    }
)


def canonicalization_routes() -> list[Path]:
    return [path for path in _server_route_modules() if path.stem in TARGET_ROUTE_MODULES]
