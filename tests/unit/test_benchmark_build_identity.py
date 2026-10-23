"""Moved benchmark runtime code remains covered by existing build identity checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import build_identity

PACKAGES = (
    "infinity_context_adapters",
    "infinity_context_benchmarks",
    "infinity_context_contracts",
    "infinity_context_core",
    "infinity_context_server",
)


@pytest.mark.parametrize("policy_path", ("evidence.py", "retrieval_intent/contracts.py"))
def test_benchmark_source_is_part_of_repository_runtime_identity(
    tmp_path: Path, policy_path: str
) -> None:
    for name in PACKAGES:
        path = tmp_path / "packages" / name / name / "__init__.py"
        path.parent.mkdir(parents=True)
        path.write_text('"""Synthetic package."""\n')
    for name in ("pyproject.toml", "uv.lock"):
        (tmp_path / name).write_text("version = 1\n")
    original = build_identity.repository_source_release_identity(
        tmp_path, service_revision="a" * 40
    )
    benchmark = tmp_path / "packages/infinity_context_benchmarks/infinity_context_benchmarks"
    policy = benchmark / policy_path
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text('POLICY = "changed"\n')
    changed = build_identity.repository_source_release_identity(tmp_path, service_revision="a" * 40)
    assert changed.runtime_modules_digest_sha256 != original.runtime_modules_digest_sha256
    assert changed.installed_distribution_digest_sha256 != (
        original.installed_distribution_digest_sha256
    )


class _Distribution:
    def __init__(self, root: Path, files: list[Path]) -> None:
        self.root = root
        self.files = files

    def locate_file(self, path: Path) -> Path:
        return self.root / path


def _installation(tmp_path: Path, monkeypatch, policy_path: str = "evidence.py"):
    root = tmp_path / "site-packages"
    files = []
    modules = {}
    for name in PACKAGES:
        relative = Path(name) / "__init__.py"
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_text('"""Synthetic installed package."""\n')
        files.append(relative)
        modules[name] = SimpleNamespace(__file__=str(path))
    policy = root / "infinity_context_benchmarks" / policy_path
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text('POLICY = "original"\n')
    files.append(policy.relative_to(root))
    monkeypatch.setattr(build_identity.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(build_identity.importlib, "import_module", modules.__getitem__)
    return _Distribution(root, files), modules, policy


@pytest.mark.parametrize("policy_path", ("evidence.py", "retrieval_intent/contracts.py"))
def test_installed_benchmark_policy_changes_runtime_digest(
    tmp_path: Path, monkeypatch, policy_path: str
) -> None:
    distribution, _modules, policy = _installation(tmp_path, monkeypatch, policy_path)
    original = build_identity.installed_artifact_digests(distribution)
    policy.write_text('POLICY = "changed"\n')
    changed = build_identity.installed_artifact_digests(distribution)
    assert changed[0] != original[0]
    assert changed[1] != original[1]


def test_benchmark_module_missing_from_record_is_rejected(tmp_path: Path, monkeypatch) -> None:
    distribution, _modules, _policy = _installation(tmp_path, monkeypatch)
    distribution.files.remove(Path("infinity_context_benchmarks/__init__.py"))
    with pytest.raises(RuntimeError, match="imported runtime module is absent"):
        build_identity.installed_artifact_digests(distribution)


def test_shadow_benchmark_module_outside_installation_is_rejected(
    tmp_path: Path, monkeypatch
) -> None:
    distribution, modules, _policy = _installation(tmp_path, monkeypatch)
    shadow = tmp_path / "shadow/infinity_context_benchmarks/__init__.py"
    shadow.parent.mkdir(parents=True)
    shadow.write_text('"""Shadow package."""\n')
    modules["infinity_context_benchmarks"].__file__ = str(shadow)
    with pytest.raises(RuntimeError, match="outside installed distribution"):
        build_identity.installed_artifact_digests(distribution)
