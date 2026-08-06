from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

from .authority import AuthorityContract
from .hashing import sha256_file


class PythonClosureError(RuntimeError):
    pass


_IMPORT_SUFFIXES = frozenset({".py", ".pyi", ".pyc", ".pyo", ".so", ".pth"})


def immutable_python_command(
    authority: AuthorityContract,
    module: str,
    *,
    interpreter: Path | None = None,
) -> tuple[str, ...]:
    expected = authority.infinity_source_root / "venv" / "bin" / "python"
    verify_venv_closure(authority)
    if interpreter is not None and interpreter != expected:
        raise PythonClosureError("arbitrary Python interpreter is forbidden")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", module) is None:
        raise PythonClosureError("immutable Python command is invalid")
    return (str(expected), "-B", "-P", "-S", "-m", module)


def immutable_infinity_python_path(authority: AuthorityContract) -> str:
    verify_venv_closure(authority)
    packages = authority.infinity_source_root / "source" / "packages"
    roots = tuple(
        packages / name
        for name in (
            "infinity_context_core",
            "infinity_context_adapters",
            "infinity_context_contracts",
            "infinity_context_server",
        )
    )
    if any(not root.is_dir() or root.is_symlink() for root in roots):
        raise PythonClosureError("immutable Infinity package roots are incomplete")
    site_packages = tuple(
        (authority.infinity_source_root / "venv" / "lib").glob("python*/site-packages")
    )
    if len(site_packages) != 1 or site_packages[0].is_symlink():
        raise PythonClosureError("immutable venv site-packages identity is ambiguous")
    return os.pathsep.join(str(root.resolve(strict=True)) for root in (*roots, site_packages[0]))


def require_bytecode_disabled() -> None:
    if not sys.dont_write_bytecode:
        raise PythonClosureError("runner requires Python -B / PYTHONDONTWRITEBYTECODE=1")


def verify_python_import_closure(
    authority: AuthorityContract,
    modules: Mapping[str, ModuleType | None] | None = None,
) -> None:
    verify_venv_closure(authority)
    inventory = _source_inventory(authority)
    source = authority.infinity_source_root / "source"
    packages = source / "packages"
    for root in sorted(packages.glob("infinity_context_*")):
        _verify_package_tree(root, authority.infinity_source_root, inventory)
    for name, module in (modules or sys.modules).items():
        if not name.startswith("infinity_context_") or module is None:
            continue
        raw_path = getattr(module, "__file__", None)
        if not isinstance(raw_path, str):
            raise PythonClosureError(f"loaded Infinity module has no file: {name}")
        path = Path(raw_path)
        if path.is_symlink() or path.suffix in {".pyc", ".pyo"}:
            raise PythonClosureError(f"loaded Infinity module is unsealed: {name}")
        try:
            relative = (
                path.resolve(strict=True)
                .relative_to(authority.infinity_source_root.resolve(strict=True))
                .as_posix()
            )
        except (FileNotFoundError, ValueError) as exc:
            raise PythonClosureError(
                f"loaded Infinity module escapes source closure: {name}"
            ) from exc
        expected = inventory.get(relative)
        if expected is None or sha256_file(path) != expected:
            raise PythonClosureError(f"loaded Infinity module is not manifest-bound: {name}")
        cached = getattr(module, "__cached__", None)
        if cached and Path(cached).exists():
            raise PythonClosureError(f"loaded Infinity module produced bytecode: {name}")


def verify_venv_closure(authority: AuthorityContract) -> None:
    root = authority.infinity_source_root
    venv = root / "venv"
    regular = _sha256_inventory(root / "attestation" / "venv-files.sha256")
    symlinks = _symlink_inventory(root / "attestation" / "venv-symlinks.txt")
    if set(regular) & set(symlinks):
        raise PythonClosureError("venv entry is declared with conflicting types")
    expected_entries = set(regular) | set(symlinks)
    if not expected_entries or any(not path.startswith("venv/") for path in expected_entries):
        raise PythonClosureError("venv inventory contains an invalid path")
    expected_directories = {"venv"}
    for relative in expected_entries:
        parent = Path(relative).parent
        while parent.as_posix() != ".":
            expected_directories.add(parent.as_posix())
            if parent.as_posix() == "venv":
                break
            parent = parent.parent

    actual_regular: set[str] = set()
    actual_symlinks: set[str] = set()
    actual_directories: set[str] = set()
    _scan_venv(
        venv,
        root=root,
        regular=actual_regular,
        symlinks=actual_symlinks,
        directories=actual_directories,
    )
    if (
        actual_regular != set(regular)
        or actual_symlinks != set(symlinks)
        or actual_directories != expected_directories
    ):
        raise PythonClosureError("venv inventory has extra, missing, or type-drift entries")
    for relative, expected_sha in regular.items():
        if sha256_file(root / relative) != expected_sha:
            raise PythonClosureError(f"venv file identity mismatch: {relative}")
    for relative, expected_target in symlinks.items():
        if (root / relative).readlink().as_posix() != expected_target:
            raise PythonClosureError(f"venv symlink identity mismatch: {relative}")
    post_regular: set[str] = set()
    post_symlinks: set[str] = set()
    post_directories: set[str] = set()
    _scan_venv(
        venv,
        root=root,
        regular=post_regular,
        symlinks=post_symlinks,
        directories=post_directories,
    )
    if (
        post_regular != set(regular)
        or post_symlinks != set(symlinks)
        or post_directories != expected_directories
    ):
        raise PythonClosureError("venv inventory changed during verification")
    interpreter = venv / "bin" / "python"
    if (
        "venv/bin/python" not in symlinks
        or not interpreter.is_symlink()
        or interpreter.readlink().as_posix() != symlinks["venv/bin/python"]
    ):
        raise PythonClosureError("authority venv interpreter identity is invalid")


def _scan_venv(
    directory: Path,
    *,
    root: Path,
    regular: set[str],
    symlinks: set[str],
    directories: set[str],
) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise PythonClosureError("authority venv root is not a regular directory")
    directories.add(directory.relative_to(root).as_posix())
    for entry in os.scandir(directory):
        path = Path(entry.path)
        relative = path.relative_to(root).as_posix()
        if entry.is_symlink():
            symlinks.add(relative)
        elif entry.is_dir(follow_symlinks=False):
            _scan_venv(
                path,
                root=root,
                regular=regular,
                symlinks=symlinks,
                directories=directories,
            )
        elif entry.is_file(follow_symlinks=False):
            regular.add(relative)
        else:
            raise PythonClosureError(f"venv contains a special node: {relative}")


def _sha256_inventory(path: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or parts[1] in inventory:
            raise PythonClosureError("venv regular-file inventory is invalid")
        inventory[parts[1]] = parts[0]
    return inventory


def _symlink_inventory(path: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(" -> ", 1)
        if len(parts) != 2 or parts[0] in inventory:
            raise PythonClosureError("venv symlink inventory is invalid")
        inventory[parts[0]] = parts[1]
    return inventory


def _source_inventory(authority: AuthorityContract) -> dict[str, str]:
    manifest = authority.infinity_source_root / "attestation" / "source-files.sha256"
    inventory: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or parts[1] in inventory:
            raise PythonClosureError("Infinity source inventory is invalid")
        inventory[parts[1]] = parts[0]
    return inventory


def _verify_package_tree(root: Path, closure_root: Path, inventory: dict[str, str]) -> None:
    for directory, names, files in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in tuple(names):
            path = directory_path / name
            if path.is_symlink():
                raise PythonClosureError(f"import-affecting directory symlink: {path}")
            if name == "__pycache__":
                raise PythonClosureError(f"bytecode cache is forbidden: {path}")
        for name in files:
            path = directory_path / name
            if path.suffix not in _IMPORT_SUFFIXES:
                continue
            if path.is_symlink() or path.suffix in {".pyc", ".pyo"}:
                raise PythonClosureError(f"unsealed import-affecting file: {path}")
            relative = path.relative_to(closure_root).as_posix()
            expected = inventory.get(relative)
            if expected is None or sha256_file(path) != expected:
                raise PythonClosureError(f"unmanifested import-affecting file: {path}")
