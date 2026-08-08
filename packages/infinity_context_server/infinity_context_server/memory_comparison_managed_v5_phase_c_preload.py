"""Fail-closed validation for already imported reviewed Phase C modules."""

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import importlib.util
import os
import stat
import sys
from pathlib import Path
from types import CodeType, FunctionType, ModuleType
from typing import final

_DOMAIN = "phase_c_canary"
_MAX_SOURCE_BYTES = 1_048_576


class PhaseCPreloadValidationError(ValueError):
    """A preloaded module is not the exact reviewed source implementation."""


@final
class ReviewedPhaseCPreloadValidator:
    """Validate module origin, bindings and source-declared code without imports."""

    __slots__ = ()

    def validate(
        self,
        root: Path,
        tree_snapshot: tuple[tuple[object, ...], ...],
    ) -> tuple[tuple[object, ...], ...]:
        expected = self._expected_files(tree_snapshot)
        loaded = {
            name: module
            for name, module in sys.modules.items()
            if name == _DOMAIN or name.startswith(f"{_DOMAIN}.")
        }
        if not loaded:
            return ()
        if _DOMAIN not in loaded:
            raise PhaseCPreloadValidationError("phase_c_parent_missing")
        package = root / _DOMAIN
        validated: list[tuple[object, ...]] = []
        for name, module in sorted(loaded.items()):
            relative = self._relative_source(name)
            if relative not in expected or type(module) is not ModuleType:
                raise PhaseCPreloadValidationError("phase_c_module_unreviewed")
            path = package / relative
            raw = self._read_exact_source(path, expected[relative])
            self._validate_module_metadata(name, module, path)
            api_fingerprint = self._validate_source_api(name, module, path, raw)
            validated.append((name, id(module), relative, api_fingerprint))
        return tuple(validated)

    @staticmethod
    def _expected_files(
        tree_snapshot: tuple[tuple[object, ...], ...],
    ) -> dict[str, tuple[object, ...]]:
        try:
            expected = {
                item[0]: tuple(item[1:])
                for item in tree_snapshot
                if type(item) is tuple and len(item) == 9 and type(item[0]) is str
            }
        except (IndexError, TypeError):
            raise PhaseCPreloadValidationError("phase_c_tree_snapshot_invalid") from None
        if len(expected) != len(tree_snapshot) or "__init__.py" not in expected:
            raise PhaseCPreloadValidationError("phase_c_tree_snapshot_invalid")
        return expected

    @staticmethod
    def _relative_source(name: str) -> str:
        if name == _DOMAIN:
            return "__init__.py"
        suffix = name.removeprefix(f"{_DOMAIN}.")
        if not suffix or any(part in {"", ".", ".."} for part in suffix.split(".")):
            raise PhaseCPreloadValidationError("phase_c_module_name_invalid")
        return f"{suffix.replace('.', '/')}.py"

    @staticmethod
    def _read_exact_source(path: Path, expected: tuple[object, ...]) -> bytes:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_uid,
                opened.st_gid,
                opened.st_mode,
                opened.st_size,
                opened.st_mtime_ns,
            )
            if (
                identity != expected[:-1]
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not 1 <= opened.st_size <= _MAX_SOURCE_BYTES
            ):
                raise ValueError
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65_536):
                chunks.append(chunk)
            final = os.fstat(descriptor)
            if identity != (
                final.st_dev,
                final.st_ino,
                final.st_uid,
                final.st_gid,
                final.st_mode,
                final.st_size,
                final.st_mtime_ns,
            ):
                raise ValueError
            raw = b"".join(chunks)
            if hashlib.sha256(raw).hexdigest() != expected[-1]:
                raise ValueError
            return raw
        except (OSError, ValueError):
            raise PhaseCPreloadValidationError("phase_c_source_identity_invalid") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _validate_module_metadata(
        name: str,
        module: ModuleType,
        path: Path,
    ) -> None:
        spec = module.__spec__
        expected_package = _DOMAIN if name == _DOMAIN else name.rpartition(".")[0]
        try:
            file_path = Path(module.__file__)
            origin_path = Path(spec.origin) if spec is not None and spec.origin else None
            valid = (
                module.__name__ == name
                and module.__package__ == expected_package
                and file_path == path
                and file_path.resolve(strict=True) == path
                and spec is not None
                and spec.name == name
                and origin_path == path
                and origin_path.resolve(strict=True) == path
                and type(spec.loader) is importlib.machinery.SourceFileLoader
            )
        except (AttributeError, OSError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PhaseCPreloadValidationError("phase_c_module_origin_invalid")

    def _validate_source_api(
        self,
        name: str,
        module: ModuleType,
        path: Path,
        raw: bytes,
    ) -> str:
        try:
            syntax = ast.parse(raw, filename=str(path))
            compiled = compile(
                raw,
                str(path),
                "exec",
                flags=0,
                dont_inherit=True,
                optimize=sys.flags.optimize,
            )
            expected_codes = self._code_fingerprints(compiled)
            observed_codes = self._runtime_code_fingerprints(name, module, path, syntax)
            if observed_codes != self._declared_code_fingerprints(syntax, expected_codes):
                raise ValueError
            imported = self._validate_import_bindings(name, module, syntax)
            constants = self._validate_literal_bindings(module, syntax)
            seals = self._validate_seals(module, syntax)
            payload = repr((sorted(observed_codes.items()), imported, constants, seals)).encode()
            return hashlib.sha256(payload).hexdigest()
        except (AttributeError, KeyError, OSError, SyntaxError, TypeError, ValueError):
            raise PhaseCPreloadValidationError("phase_c_module_api_invalid") from None

    @staticmethod
    def _code_fingerprints(code: CodeType) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}

        def visit(current: CodeType) -> None:
            result.setdefault(current.co_qualname, []).append(
                ReviewedPhaseCPreloadValidator._code_fingerprint(current)
            )
            for value in current.co_consts:
                if type(value) is CodeType:
                    visit(value)

        visit(code)
        return result

    @staticmethod
    def _code_fingerprint(code: CodeType) -> str:
        def normalize(value: object) -> object:
            if type(value) is CodeType:
                return code_payload(value)
            if type(value) is tuple:
                return ("tuple", tuple(normalize(item) for item in value))
            if type(value) is frozenset:
                items = tuple(sorted((normalize(item) for item in value), key=repr))
                return ("frozenset", items)
            if type(value) in {bool, bytes, complex, float, int, str, type(None)}:
                return (type(value).__name__, value)
            if value is Ellipsis:
                return ("ellipsis",)
            raise ValueError

        def code_payload(current: CodeType) -> tuple[object, ...]:
            return (
                current.co_argcount,
                current.co_posonlyargcount,
                current.co_kwonlyargcount,
                current.co_nlocals,
                current.co_stacksize,
                current.co_flags,
                current.co_code,
                normalize(current.co_consts),
                current.co_names,
                current.co_varnames,
                current.co_filename,
                current.co_name,
                current.co_qualname,
                current.co_firstlineno,
                current.co_linetable,
                current.co_exceptiontable,
                current.co_freevars,
                current.co_cellvars,
            )

        return hashlib.sha256(repr(code_payload(code)).encode()).hexdigest()

    @staticmethod
    def _declared_code_fingerprints(
        syntax: ast.Module,
        expected: dict[str, list[str]],
    ) -> dict[str, tuple[str, ...]]:
        names: list[str] = []
        for node in syntax.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(node.name)
            elif isinstance(node, ast.ClassDef):
                names.extend(
                    f"{node.name}.{member.name}"
                    for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        return {name: tuple(sorted(expected[name])) for name in sorted(set(names))}

    @staticmethod
    def _runtime_code_fingerprints(
        module_name: str,
        module: ModuleType,
        path: Path,
        syntax: ast.Module,
    ) -> dict[str, tuple[str, ...]]:
        observed: dict[str, list[str]] = {}

        def add(function: FunctionType, expected_qualname: str) -> None:
            if (
                type(function) is not FunctionType
                or function.__module__ != module_name
                or function.__globals__ is not vars(module)
                or function.__code__.co_qualname != expected_qualname
                or Path(function.__code__.co_filename) != path
            ):
                raise ValueError
            observed.setdefault(expected_qualname, []).append(
                ReviewedPhaseCPreloadValidator._code_fingerprint(function.__code__)
            )

        for node in syntax.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(vars(module)[node.name], node.name)
            elif isinstance(node, ast.ClassDef):
                cls = vars(module)[node.name]
                if (
                    not isinstance(cls, type)
                    or cls.__module__ != module_name
                    or cls.__qualname__ != node.name
                ):
                    raise ValueError
                for member in node.body:
                    if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    value = vars(cls)[member.name]
                    functions: tuple[FunctionType, ...]
                    if type(value) in {staticmethod, classmethod}:
                        functions = (value.__func__,)
                    elif type(value) is property:
                        functions = tuple(
                            item
                            for item in (value.fget, value.fset, value.fdel)
                            if item is not None
                        )
                    else:
                        functions = (value,)
                    for function in functions:
                        add(function, f"{node.name}.{member.name}")
        return {name: tuple(sorted(values)) for name, values in observed.items()}

    @staticmethod
    def _validate_import_bindings(
        module_name: str,
        module: ModuleType,
        syntax: ast.Module,
    ) -> tuple[tuple[str, int], ...]:
        bindings: list[tuple[str, int]] = []
        for node in syntax.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    target_name = alias.name if alias.asname else alias.name.split(".")[0]
                    target = sys.modules.get(target_name)
                    if target is None or vars(module).get(local) is not target:
                        raise ValueError
                    bindings.append((local, id(target)))
            elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
                absolute = importlib.util.resolve_name(
                    "." * node.level + (node.module or ""),
                    module.__package__ or module_name,
                )
                target = sys.modules.get(absolute)
                if target is None:
                    raise ValueError
                for alias in node.names:
                    if alias.name == "*":
                        raise ValueError
                    local = alias.asname or alias.name
                    expected = getattr(target, alias.name)
                    if vars(module).get(local) is not expected:
                        raise ValueError
                    bindings.append((local, id(expected)))
        return tuple(sorted(bindings))

    @staticmethod
    def _validate_literal_bindings(
        module: ModuleType,
        syntax: ast.Module,
    ) -> tuple[tuple[str, str], ...]:
        observed: list[tuple[str, str]] = []
        for node in syntax.body:
            name: str | None = None
            value_node: ast.expr | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name):
                    name, value_node = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value_node = node.target.id, node.value
            if name is None or value_node is None or not name.lstrip("_").isupper():
                continue
            try:
                expected = ast.literal_eval(value_node)
            except (ValueError, TypeError):
                continue
            if not ReviewedPhaseCPreloadValidator._is_immutable_literal(expected):
                continue
            actual = vars(module).get(name)
            if type(actual) is not type(expected) or actual != expected:
                raise ValueError
            observed.append((name, repr(actual)))
        return tuple(observed)

    @staticmethod
    def _is_immutable_literal(value: object) -> bool:
        if type(value) in {bool, bytes, complex, float, int, str, type(None)}:
            return True
        return type(value) is tuple and all(
            ReviewedPhaseCPreloadValidator._is_immutable_literal(item) for item in value
        )

    @staticmethod
    def _validate_seals(
        module: ModuleType,
        syntax: ast.Module,
    ) -> tuple[tuple[str, int], ...]:
        seals: list[tuple[str, int]] = []
        for node in syntax.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            call = node.value
            if (
                isinstance(target, ast.Name)
                and target.id.endswith("_SEAL")
                and isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "object"
                and not call.args
                and not call.keywords
            ):
                value = vars(module).get(target.id)
                if type(value) is not object:
                    raise ValueError
                seals.append((target.id, id(value)))
        if len({identity for _, identity in seals}) != len(seals):
            raise ValueError
        return tuple(seals)


__all__ = ("PhaseCPreloadValidationError", "ReviewedPhaseCPreloadValidator")
