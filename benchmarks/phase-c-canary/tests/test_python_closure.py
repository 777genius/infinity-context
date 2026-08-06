from __future__ import annotations

import subprocess
import types
from dataclasses import replace
from pathlib import Path

import pytest

from phase_c_canary.authority import immutable_authority
from phase_c_canary.environment import immutable_python_environment
from phase_c_canary.hashing import sha256_file
from phase_c_canary.python_closure import (
    PythonClosureError,
    immutable_infinity_python_path,
    immutable_python_command,
    require_bytecode_disabled,
    verify_python_import_closure,
    verify_venv_closure,
)


def _venv(tmp_path: Path) -> Path:
    site_packages = tmp_path / "venv/lib/python3.12/site-packages"
    site_packages.mkdir(parents=True)
    dependency = site_packages / "dependency.py"
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    declared_pth = site_packages / "_virtualenv.pth"
    declared_pth.write_text("# inert under -S\n", encoding="utf-8")
    config = tmp_path / "venv/pyvenv.cfg"
    config.write_text("home = /usr/bin\n", encoding="utf-8")
    bin_directory = tmp_path / "venv/bin"
    bin_directory.mkdir()
    (bin_directory / "python").symlink_to("/usr/bin/python3")
    attestation = tmp_path / "attestation"
    attestation.mkdir(exist_ok=True)
    regular = (dependency, declared_pth, config)
    (attestation / "venv-files.sha256").write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(tmp_path).as_posix()}\n" for path in regular
        ),
        encoding="utf-8",
    )
    (attestation / "venv-symlinks.txt").write_text(
        "venv/bin/python -> /usr/bin/python3\n", encoding="utf-8"
    )
    packages = tmp_path / "source/packages"
    for name in (
        "infinity_context_core",
        "infinity_context_adapters",
        "infinity_context_contracts",
        "infinity_context_server",
    ):
        (packages / name).mkdir(parents=True, exist_ok=True)
    return site_packages


def _closure(tmp_path: Path) -> tuple[object, Path]:
    _venv(tmp_path)
    package = tmp_path / "source/packages/infinity_context_fake"
    package.mkdir(parents=True)
    module = package / "__init__.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    attestation = tmp_path / "attestation"
    attestation.mkdir(exist_ok=True)
    relative = module.relative_to(tmp_path).as_posix()
    (attestation / "source-files.sha256").write_text(
        f"{sha256_file(module)}  {relative}\n", encoding="utf-8"
    )
    return replace(immutable_authority(), infinity_source_root=tmp_path), module


def test_immutable_python_command_always_disables_bytecode() -> None:
    authority = immutable_authority()
    assert immutable_python_command(authority, "infinity_context_server.cli") == (
        str(authority.infinity_source_root / "venv/bin/python"),
        "-B",
        "-P",
        "-S",
        "-m",
        "infinity_context_server.cli",
    )


def test_runner_rejects_python_without_bytecode_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.dont_write_bytecode", False)
    with pytest.raises(PythonClosureError, match="Python -B"):
        require_bytecode_disabled()


def test_immutable_python_environment_is_explicit_and_disables_bytecode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_PASSWORD", "must-not-leak")
    authority = immutable_authority()
    environment = immutable_python_environment(authority=authority, path="/usr/bin:/bin")
    assert environment == {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": immutable_infinity_python_path(authority),
        "PYTHONSAFEPATH": "1",
    }


def test_infinity_python_path_is_derived_from_immutable_authority() -> None:
    python_path = immutable_infinity_python_path(immutable_authority())
    assert python_path.split(":") == [
        str(immutable_authority().infinity_source_root / "source/packages" / name)
        for name in (
            "infinity_context_core",
            "infinity_context_adapters",
            "infinity_context_contracts",
            "infinity_context_server",
        )
    ] + [str(immutable_authority().infinity_source_root / "venv/lib/python3.12/site-packages")]


def test_manifest_bound_loaded_module_is_accepted(tmp_path: Path) -> None:
    authority, path = _closure(tmp_path)
    module = types.ModuleType("infinity_context_fake")
    module.__file__ = str(path)
    verify_python_import_closure(authority, {module.__name__: module})


@pytest.mark.parametrize("rogue", ["rogue.py", "rogue.pyc"])
def test_unmanifested_import_affecting_file_is_rejected(tmp_path: Path, rogue: str) -> None:
    authority, path = _closure(tmp_path)
    (path.parent / rogue).write_bytes(b"rogue")
    with pytest.raises(PythonClosureError, match="import-affecting|bytecode"):
        verify_python_import_closure(authority, {})


def test_import_affecting_symlink_is_rejected(tmp_path: Path) -> None:
    authority, path = _closure(tmp_path)
    (path.parent / "alias.py").symlink_to(path.name)
    with pytest.raises(PythonClosureError, match="unsealed"):
        verify_python_import_closure(authority, {})


def test_loaded_module_outside_closure_is_rejected(tmp_path: Path) -> None:
    authority, _ = _closure(tmp_path)
    outside = tmp_path.parent / "outside-infinity-module.py"
    outside.write_text("VALUE = 2\n", encoding="utf-8")
    module = types.ModuleType("infinity_context_impostor")
    module.__file__ = str(outside)
    with pytest.raises(PythonClosureError, match="escapes"):
        verify_python_import_closure(authority, {module.__name__: module})


@pytest.mark.parametrize("extra", ["sitecustomize.py", "injected.pth", "regular.py", "native.so"])
def test_extra_venv_startup_file_is_rejected(tmp_path: Path, extra: str) -> None:
    site_packages = _venv(tmp_path)
    authority = replace(immutable_authority(), infinity_source_root=tmp_path)
    (site_packages / extra).write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    with pytest.raises(PythonClosureError, match="extra, missing, or type-drift"):
        verify_venv_closure(authority)


def test_missing_declared_venv_file_is_rejected(tmp_path: Path) -> None:
    site_packages = _venv(tmp_path)
    authority = replace(immutable_authority(), infinity_source_root=tmp_path)
    (site_packages / "dependency.py").unlink()
    with pytest.raises(PythonClosureError, match="extra, missing, or type-drift"):
        verify_venv_closure(authority)


def test_venv_regular_to_symlink_type_drift_is_rejected(tmp_path: Path) -> None:
    site_packages = _venv(tmp_path)
    authority = replace(immutable_authority(), infinity_source_root=tmp_path)
    dependency = site_packages / "dependency.py"
    dependency.unlink()
    dependency.symlink_to("_virtualenv.pth")
    with pytest.raises(PythonClosureError, match="extra, missing, or type-drift"):
        verify_venv_closure(authority)


def test_extra_importable_venv_symlink_is_rejected(tmp_path: Path) -> None:
    site_packages = _venv(tmp_path)
    authority = replace(immutable_authority(), infinity_source_root=tmp_path)
    (site_packages / "alias.py").symlink_to("dependency.py")
    with pytest.raises(PythonClosureError, match="extra, missing, or type-drift"):
        verify_venv_closure(authority)


def test_arbitrary_absolute_interpreter_is_rejected(tmp_path: Path) -> None:
    _venv(tmp_path)
    authority = replace(immutable_authority(), infinity_source_root=tmp_path)
    with pytest.raises(PythonClosureError, match="arbitrary Python interpreter"):
        immutable_python_command(
            authority,
            "infinity_context_server.cli",
            interpreter=Path("/usr/bin/python3"),
        )


def test_minus_s_runs_declared_module_without_executing_sitecustomize(tmp_path: Path) -> None:
    site_packages = _venv(tmp_path)
    sentinel = tmp_path / "sitecustomize-executed"
    sitecustomize = site_packages / "sitecustomize.py"
    sitecustomize.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('unsafe')\n",
        encoding="utf-8",
    )
    probe = site_packages / "closure_probe.py"
    probe.write_text("print('closure-probe-ok')\n", encoding="utf-8")
    manifest = tmp_path / "attestation/venv-files.sha256"
    with manifest.open("a", encoding="utf-8") as stream:
        for path in (sitecustomize, probe):
            stream.write(f"{sha256_file(path)}  {path.relative_to(tmp_path).as_posix()}\n")
    authority = replace(immutable_authority(), infinity_source_root=tmp_path)
    command = immutable_python_command(authority, "closure_probe")
    environment = immutable_python_environment(authority=authority, path="/usr/bin:/bin")
    completed = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert completed.stdout == "closure-probe-ok\n"
    assert not sentinel.exists()
