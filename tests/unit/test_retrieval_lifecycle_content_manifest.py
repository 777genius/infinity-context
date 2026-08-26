from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.retrieval_lifecycle_content_manifest import build_manifest

_FORMERLY_OMITTED_INPUTS = (
    "benchmarks/qualification/run.py",
    "frontend/lib/main.dart",
    "frontend/package.json",
    "frontend/vitest.config.cjs",
    "plugins/bridge/bin/launch",
    "plugins/bridge/package.json",
    "plugins/bridge/tests/config.mts",
    "packages/infinity_context_sdk/package.json",
    "config/release.settings",
    "examples/retrieval/request.input",
    "Dockerfile",
    "Makefile",
    ".env.example",
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def tracked_repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    for relative in reversed(_FORMERLY_OMITTED_INPUTS):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"original:{relative}\n", encoding="utf-8")
    generated_placeholder = tmp_path / "build" / ".keep"
    generated_placeholder.parent.mkdir(parents=True)
    generated_placeholder.write_bytes(b"")
    (tmp_path / ".env").write_text("MUST_NOT_BE_READ=private\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("MUST_NOT_BE_READ=private\n", encoding="utf-8")
    _git(tmp_path, "add", "--all")
    return tmp_path


def test_manifest_includes_all_tracked_inputs_with_stable_order(
    tracked_repository: Path,
) -> None:
    manifest = build_manifest(tracked_repository)

    paths = [entry["path"] for entry in manifest["entries"]]
    assert paths == sorted(paths)
    assert set(_FORMERLY_OMITTED_INPUTS).issubset(paths)
    assert "build/.keep" in paths
    assert manifest["excluded_private_environment_files"] == [".env", ".env.local"]


@pytest.mark.parametrize("relative", _FORMERLY_OMITTED_INPUTS)
def test_every_representative_tracked_input_alters_digest(
    tracked_repository: Path,
    relative: str,
) -> None:
    before = build_manifest(tracked_repository)["manifest_sha256"]

    with (tracked_repository / relative).open("ab") as stream:
        stream.write(b"changed\n")

    after = build_manifest(tracked_repository)["manifest_sha256"]
    assert after != before


def test_private_dotenv_files_are_excluded_without_being_opened(
    tracked_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.read_bytes

    def reject_private_environment_read(path: Path) -> bytes:
        if path.name in {".env", ".env.local"}:
            raise AssertionError("private environment file was read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", reject_private_environment_read)

    manifest = build_manifest(tracked_repository)
    assert manifest["excluded_private_environment_files"] == [".env", ".env.local"]


def test_untracked_files_do_not_enter_release_manifest(tracked_repository: Path) -> None:
    untracked = tracked_repository / "runtime-secret.txt"
    untracked.write_text("not a release input\n", encoding="utf-8")

    manifest = build_manifest(tracked_repository)
    assert "runtime-secret.txt" not in {entry["path"] for entry in manifest["entries"]}
