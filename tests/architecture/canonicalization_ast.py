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


def annotation_symbol(node: ast.AST | None, bindings: dict[str, str]) -> str:
    """Parse forward references only in type positions, never ordinary strings."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return annotation_symbol(ast.parse(node.value, mode="eval").body, bindings)
    if isinstance(node, ast.Subscript):
        items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        wrapper = dotted(node.value, bindings).rsplit(".", 1)[-1]
        if wrapper == "Annotated":
            return annotation_symbol(items[0], bindings)
        symbols = {annotation_symbol(item, bindings) for item in items}
        symbols.discard("")
        symbols.discard("None")
        if len(symbols) > 1:
            assert not any(
                name == CONTAINER or legacy_owner(name) or name.startswith(tuple(DORMANT_MODULES))
                for name in symbols
            ), "Unresolved ownership-relevant union annotation"
            return dotted(node, bindings)
        return next(iter(symbols), "")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        symbols = {annotation_symbol(node.left, bindings), annotation_symbol(node.right, bindings)}
        symbols -= {"", "None"}
        if len(symbols) > 1:
            assert not any(
                name == CONTAINER or legacy_owner(name) or name.startswith(tuple(DORMANT_MODULES))
                for name in symbols
            ), "Unresolved ownership-relevant union annotation"
            return dotted(node, bindings)
        return next(iter(symbols), "")
    return dotted(node, bindings)


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
                self.top_binding(path, node, bindings)
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

    def top_binding(self, path: Path, node: ast.AST, bindings: dict[str, str]) -> None:
        """Shared extraction for repository scans and in-memory counterexamples."""
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[node.name] = f"{module_name(path)}.{node.name}"
        self.import_binding(path, node, bindings)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    value = dotted(node.value, bindings)
                    if isinstance(node.value, ast.Call) and value.endswith(".APIRouter"):
                        value = f"{module_name(path)}.{target.id}"
                    bindings[target.id] = value or target.id

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
            node.target.id: self.resolve(annotation_symbol(node.annotation, bindings))
            for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }

    def calls(
        self, path: Path, *, eager_only: bool = False
    ) -> list[tuple[str, str, tuple[str, ...]]]:
        """Return lexical caller, call target, and statically named arguments.

        Function scopes get independent bindings. A conservative union of calls
        in both branches is intentional: configuration must not hide a new owner.
        """
        result = []
        module = module_name(path)
        index = self
        postponed = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in self.trees[path].body
        )
        self.parameters = getattr(self, "parameters", {})
        self.positional_parameters = getattr(self, "positional_parameters", {})
        self.variadic_parameters = getattr(self, "variadic_parameters", {})
        self.named_calls = getattr(self, "named_calls", {})

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.bindings = dict(index.bindings[module])
                self.scope = module
                self.eager = True
                self.class_outer = None

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
                if not postponed:
                    for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                        if arg.annotation:
                            self.visit(arg.annotation)
                    if node.returns:
                        self.visit(node.returns)
                previous, scope = self.bindings, self.scope
                previous[node.name] = f"{scope}.{node.name}"
                self.bindings = dict(self.class_outer or previous)
                self.scope = f"{scope}.{node.name}"
                eager, outer = self.eager, self.class_outer
                self.eager, self.class_outer = False, None
                params = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                index.parameters[self.scope] = [arg.arg for arg in params]
                index.positional_parameters[self.scope] = [
                    arg.arg for arg in (*node.args.posonlyargs, *node.args.args)
                ]
                index.variadic_parameters[self.scope] = node.args.vararg is not None
                # Python determines function locals for the whole block. Do not
                # let a local definition resolve to a same-named module import.
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        self.bindings[item.name] = f"{self.scope}.{item.name}"
                for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                    annotation = index.resolve(annotation_symbol(arg.annotation, previous))
                    if annotation == CONTAINER:
                        self.bindings[arg.arg] = "$container"
                    elif legacy_owner(annotation) or any(
                        annotation.startswith(f"{module}.") for module in DORMANT_MODULES
                    ):
                        self.bindings[arg.arg] = annotation
                    else:
                        self.bindings[arg.arg] = (
                            arg.arg
                            if arg.arg in {"self", "cls"}
                            else f"$param:{self.scope}:{arg.arg}"
                        )
                for item in node.body:
                    self.visit(item)
                self.bindings, self.scope = previous, scope
                self.eager, self.class_outer = eager, outer

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Lambda(self, node: ast.Lambda) -> None:
                for value in (*node.args.defaults, *filter(None, node.args.kw_defaults)):
                    self.visit(value)
                eager = self.eager
                self.eager = False
                self.visit(node.body)
                self.eager = eager

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                for value in (
                    *node.decorator_list,
                    *node.bases,
                    *(kw.value for kw in node.keywords),
                ):
                    self.visit(value)
                previous, scope, outer = self.bindings, self.scope, self.class_outer
                previous[node.name] = f"{scope}.{node.name}"
                self.bindings = dict(previous)
                self.class_outer = outer or previous
                self.scope = f"{scope}.{node.name}"
                for item in node.body:
                    self.visit(item)
                self.bindings, self.scope, self.class_outer = previous, scope, outer

            def visit_Assign(self, node: ast.Assign) -> None:
                self.visit(node.value)
                value = self.symbol(node.value)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.bindings[target.id] = value or target.id

            def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                if not postponed and (self.scope == module or self.class_outer is not None):
                    self.visit(node.annotation)
                if node.value:
                    self.visit(node.value)
                if isinstance(node.target, ast.Name) and node.value:
                    self.bindings[node.target.id] = self.symbol(node.value) or node.target.id

            def visit_Call(self, node: ast.Call) -> None:
                target = self.symbol(node.func)

                def argument(arg: ast.AST) -> str:
                    if isinstance(arg, (ast.Starred, ast.Dict, ast.List, ast.Tuple)):
                        assert not any(
                            self.symbol(item) == "$container" for item in ast.walk(arg)
                        ), f"Unresolved Container forwarding: {self.scope} -> {target}"
                    if target.endswith((".add_api_route", ".include_router")):
                        # Keep imported router provenance, even though its value
                        # is an APIRouter instance rather than a Python function.
                        value = arg.func if isinstance(arg, ast.Call) else arg
                        return dotted(value, self.bindings)
                    return self.symbol(arg)

                arguments = tuple(
                    argument(arg) for arg in (*node.args, *(kw.value for kw in node.keywords))
                )
                if not eager_only or self.eager:
                    result.append((self.scope, target, arguments))
                    index.named_calls.setdefault((self.scope, target, arguments), set()).add(
                        (
                            tuple(argument(arg) for arg in node.args),
                            tuple((kw.arg, argument(kw.value)) for kw in node.keywords),
                        )
                    )
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
    calls = ownership_calls(index, paths)
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
    # Attribute owner edges to entry points through resolved helper calls.
    for _ in range(len(calls) + 1):
        previous = set(edges)
        for caller, target, _ in calls:
            edges.update((caller, owner) for origin, owner in previous if origin == target)
        if previous == edges:
            break
    return edges


def ownership_calls(
    index: SourceIndex, paths: list[Path]
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Bounded Container parameter substitution and imported route reachability.

    Only whole Container forwarding is specialized; member forwarding is already
    an explicit execution edge. Unknown whole-Container recipients fail closed.
    Imported registration targets must have indexed source. Benchmark surfaces
    are explicitly outside this inventory, even when a route imports them.
    """
    pending = [(path, None) for path in paths]
    visited = set()
    calls = []
    while pending:
        path, selected = pending.pop()
        if (path, selected) in visited or benchmark_path(path):
            continue
        visited.add((path, selected))
        if path not in index.trees:
            index.trees[path] = ast.parse(path.read_text(encoding="utf-8"))
        current = [
            call
            for call in index.calls(path)
            if selected is None or call[0] == selected or call[0].startswith(selected + ".")
        ]
        calls.extend(current)
        for caller, target, arguments in current:
            registration = target.endswith((".add_api_route", ".include_router"))
            candidates = [target]
            for positional, keywords in index.named_calls[(caller, target, arguments)]:
                if registration:
                    name, offset = (
                        ("endpoint", 1) if target.endswith(".add_api_route") else ("router", 0)
                    )
                    candidate = dict(keywords).get(name)
                    if candidate is None and len(positional) > offset:
                        candidate = positional[offset]
                    assert candidate, f"Unresolved route registration: {caller}"
                    resolved = index.resolve(candidate)
                    if any(resolved.startswith(module + ".") for module in index.paths):
                        candidate = resolved
                    candidates.append(candidate)
            for candidate in candidates:
                modules = [m for m in index.paths if candidate.startswith(m + ".")]
                module = max(modules, key=len) if modules else None
                if registration and candidate != target:
                    assert module, f"Unresolved route registration target: {candidate}"
                    name = candidate.removeprefix(module + ".").split(".")[0]
                    assert (
                        name in index.bindings[module] and index.resolve(candidate) == candidate
                    ), f"Unresolved route registration binding: {candidate}"
                if module:
                    dependency = index.paths[module]
                    # Follow imported functions/handlers, not all composition
                    # constructors simply because get_container is a dependency.
                    if module != f"{SERVER}.composition" and dependency != path:
                        pending.append((dependency, None if registration else candidate))
    original = list(calls)
    substitutions = set()
    for _ in range(len(original) + 1):
        before = set(substitutions)
        for caller, target, arguments in original:
            for positional, keywords in index.named_calls[(caller, target, arguments)]:
                params = index.parameters.get(target, [])
                positional_params = index.positional_parameters.get(target, [])
                # Retain surplus values until after propagated Container substitution.
                # Keyword-only formals cannot receive positional arguments.
                supplied = [
                    (positional_params[offset] if offset < len(positional_params) else None, value)
                    for offset, value in enumerate(positional)
                ]
                for name, value in supplied:
                    values = {value}
                    values.update(value.replace(old, new) for old, new in before if old in value)
                    if "$container" in values and name is None:
                        assert not index.variadic_parameters.get(target, False), (
                            f"Unsupported variadic Container forwarding: {caller} -> {target}"
                        )
                        raise AssertionError(
                            f"Unresolved Container forwarding: {caller} -> {target}"
                        )
                supplied.extend(keywords)
                for name, value in supplied:
                    values = {value}
                    values.update(value.replace(old, new) for old, new in before if old in value)
                    if "$container" in values:
                        assert name in params, (
                            f"Unresolved Container forwarding: {caller} -> {target}"
                        )
                        substitutions.add((f"$param:{target}:{name}", "$container"))
                if "$container" in arguments:
                    assert params, f"Unresolved Container forwarding: {caller} -> {target}"
                    assert not any(
                        name is None and value == "$container" for name, value in keywords
                    ), f"Unresolved Container keyword forwarding: {caller}"
        if before == substitutions:
            break
    else:
        raise AssertionError("Container propagation did not converge")
    for caller, target, arguments in original:
        for old, new in substitutions:
            if old in target or any(old in arg for arg in arguments):
                calls.append(
                    (
                        caller,
                        target.replace(old, new),
                        tuple(arg.replace(old, new) for arg in arguments),
                    )
                )
    return calls


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
        for caller, target, arguments in ownership_calls(index, paths)
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
        for caller, target, arguments in index.calls(
            path, eager_only=module_name(path) in DORMANT_MODULES
        )
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
            index.top_binding(path, node, bindings)
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
# owners. Feature modules are additionally scanned regardless of filename or
# mounting style; benchmark-only routes remain explicitly excluded.
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


def benchmark_path(path: Path) -> bool:
    return any("benchmark" in part or "memory_comparison" in part for part in path.parts)


def canonicalization_routes() -> list[Path]:
    feature_root = REPO_ROOT / f"packages/{SERVER}/{SERVER}/features"
    return sorted(
        {
            path
            for path in [*_server_route_modules(), *feature_root.rglob("*.py")]
            if (path.stem in TARGET_ROUTE_MODULES or "features" in path.parts)
            and not benchmark_path(path)
        }
    )
