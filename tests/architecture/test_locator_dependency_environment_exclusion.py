"""Dependency environments do not hide actual repository retrieval source."""

from pathlib import Path

import test_locator_retrieval_boundaries as boundary


def test_only_explicit_dependency_environments_are_excluded(tmp_path, monkeypatch):
    excluded = {
        Path(".venv/lib/third_party.py"),
        Path("benchmarks/mem0-oss-adapter-v5/.venv/lib/third_party.py"),
    }
    scanned = {
        Path("benchmarks/mem0-oss-adapter-v5/deployment/current.py"),
        Path("benchmarks/mem0-oss-adapter-v5/vendor/current.py"),
        Path("packages/example/.venv/current.py"),
    }
    for relative in excluded | scanned:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"import {boundary.OLD_SERVING_MODULE}\n")
    monkeypatch.setattr(boundary, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(boundary, "CURRENT_SOURCE_ROOTS", (tmp_path,))
    actual = {path.relative_to(tmp_path) for path in boundary._current_text_files()}
    assert actual == scanned
    for relative in actual:
        assert boundary._source_boundary_violations(relative, (tmp_path / relative).read_text())
    for relative in excluded:
        assert boundary._in_explicit_non_source_directory(tmp_path / relative)
        assert boundary._in_explicit_non_source_directory((tmp_path / relative).with_suffix(".whl"))
    for relative in scanned:
        assert not boundary._in_explicit_non_source_directory(tmp_path / relative)
        assert not boundary._in_explicit_non_source_directory(
            (tmp_path / relative).with_suffix(".whl")
        )
