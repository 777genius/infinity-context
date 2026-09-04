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
    ".env.production.example",
)

_PRIVATE_ENVIRONMENT_FILES = (".env", ".env.local", "config/.env.production")
_TRACKED_INPUTS = (*_FORMERLY_OMITTED_INPUTS, "build/.keep")


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
    _git(tmp_path, "add", "--all")
    for relative in _PRIVATE_ENVIRONMENT_FILES:
        private = tmp_path / relative
        private.parent.mkdir(parents=True, exist_ok=True)
        private.write_text("MUST_NOT_BE_READ=private\n", encoding="utf-8")
    return tmp_path


def test_manifest_includes_all_tracked_inputs_with_stable_order(
    tracked_repository: Path,
) -> None:
    manifest = build_manifest(tracked_repository)

    paths = [entry["path"] for entry in manifest["entries"]]
    expected = sorted(_TRACKED_INPUTS)
    assert paths == expected
    assert manifest["file_count"] == len(expected)
    assert manifest["excluded_private_environment_files"] == []
    assert manifest == build_manifest(tracked_repository)


@pytest.mark.parametrize("relative", _TRACKED_INPUTS)
def test_every_representative_tracked_input_alters_digest(
    tracked_repository: Path,
    relative: str,
) -> None:
    before = build_manifest(tracked_repository)["manifest_sha256"]

    with (tracked_repository / relative).open("ab") as stream:
        stream.write(b"changed\n")

    after = build_manifest(tracked_repository)["manifest_sha256"]
    assert after != before


@pytest.mark.parametrize("relative", _PRIVATE_ENVIRONMENT_FILES)
def test_tracked_private_dotenv_fails_closed_before_any_content_read(
    tracked_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    _git(tracked_repository, "add", "--force", "--", relative)

    def reject_content_read(path: Path) -> bytes:
        raise AssertionError(f"manifest input was read before fail-closed check: {path}")

    monkeypatch.setattr(Path, "read_bytes", reject_content_read)

    with pytest.raises(RuntimeError) as error:
        build_manifest(tracked_repository)

    assert str(error.value) == f"tracked private environment file is not permitted: {relative}"


def test_untracked_files_do_not_enter_release_manifest(tracked_repository: Path) -> None:
    untracked = tracked_repository / "runtime-secret.txt"
    untracked.write_text("not a release input\n", encoding="utf-8")

    manifest = build_manifest(tracked_repository)
    paths = {entry["path"] for entry in manifest["entries"]}
    assert "runtime-secret.txt" not in paths
    assert set(_PRIVATE_ENVIRONMENT_FILES).isdisjoint(paths)
