"""Tests for the monotonic file-size architecture boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_file_size_boundaries import (
    BaselineError,
    check_baseline_monotonicity,
    check_file_size_boundaries,
    load_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "tests" / "architecture" / "file_size_legacy_baseline.json"


def _write_lines(root: Path, relative_path: str, count: int) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("line\n" * count, encoding="utf-8")


def _reasons(root: Path, baseline: dict[str, int], paths: tuple[str, ...]) -> list[str]:
    return [
        violation.reason
        for violation in check_file_size_boundaries(root, baseline, code_paths=paths)
    ]


def test_repository_respects_exact_legacy_line_budgets() -> None:
    baseline = load_baseline(BASELINE_PATH)

    assert len(baseline) == 111
    assert check_file_size_boundaries(REPO_ROOT, baseline) == ()


def test_new_oversized_file_fails(tmp_path: Path) -> None:
    path = "packages/example/new_module.py"
    _write_lines(tmp_path, path, 1001)

    assert _reasons(tmp_path, {}, (path,)) == [
        "new or unbudgeted code file exceeds the 1000-line limit"
    ]


def test_legacy_growth_by_one_line_fails(tmp_path: Path) -> None:
    path = "tests/example/legacy.py"
    _write_lines(tmp_path, path, 1201)

    assert _reasons(tmp_path, {path: 1200}, (path,)) == [
        "legacy file grew above its frozen ceiling"
    ]


def test_legacy_shrink_requires_lowered_baseline(tmp_path: Path) -> None:
    path = "scripts/legacy.py"
    _write_lines(tmp_path, path, 1100)

    assert _reasons(tmp_path, {path: 1200}, (path,)) == [
        "legacy file shrank; lower its baseline ceiling"
    ]
    assert _reasons(tmp_path, {path: 1100}, (path,)) == []


def test_legacy_entry_must_be_removed_at_limit(tmp_path: Path) -> None:
    path = "scripts/legacy.py"
    _write_lines(tmp_path, path, 1000)

    assert _reasons(tmp_path, {path: 1200}, (path,)) == [
        "legacy file is now within 1000 lines; remove its baseline entry"
    ]
    assert _reasons(tmp_path, {}, (path,)) == []


def test_stale_baseline_entry_fails(tmp_path: Path) -> None:
    path = "tests/example/deleted.py"

    assert _reasons(tmp_path, {path: 1200}, ()) == ["stale or deleted baseline entry"]


def test_base_ref_rejects_new_baseline_entry() -> None:
    violations = check_baseline_monotonicity(
        {"scripts/legacy.py": 1200, "tests/new_debt.py": 1100},
        {"scripts/legacy.py": 1200},
    )

    assert [(item.path, item.reason) for item in violations] == [
        ("tests/new_debt.py", "new legacy baseline entries are prohibited")
    ]


def test_base_ref_rejects_increased_ceiling_and_allows_decrease() -> None:
    path = "scripts/legacy.py"

    increased = check_baseline_monotonicity({path: 1201}, {path: 1200})
    decreased = check_baseline_monotonicity({path: 1100}, {path: 1200})

    assert [item.reason for item in increased] == [
        "legacy baseline ceiling increased relative to base ref"
    ]
    assert decreased == ()


def test_frontend_dart_is_governed(tmp_path: Path) -> None:
    path = "frontend/lib/oversized_widget.dart"
    _write_lines(tmp_path, path, 1001)

    violations = check_file_size_boundaries(tmp_path, {}, code_paths=(path,))

    assert [violation.path for violation in violations] == [path]


@pytest.mark.parametrize(
    "payload",
    (
        "[]",
        '{"README.md": 1200}',
        '{"scripts/../outside.py": 1200}',
        '{"scripts/./legacy.py": 1200}',
        '{"scripts/legacy.py": 1000}',
        '{"scripts/legacy.py": "1200"}',
    ),
)
def test_malformed_baseline_fails(tmp_path: Path, payload: str) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(payload, encoding="utf-8")

    with pytest.raises(BaselineError):
        load_baseline(baseline_path)


@pytest.mark.parametrize("broken", (False, True))
def test_governed_symlink_fails_without_following_target(tmp_path: Path, broken: bool) -> None:
    path = "packages/example/link.py"
    link = tmp_path / path
    link.parent.mkdir(parents=True)
    target = tmp_path.parent / f"outside-{tmp_path.name}.py"
    if not broken:
        target.write_text("outside\n" * 1001, encoding="utf-8")
    link.symlink_to(target)

    violations = check_file_size_boundaries(tmp_path, {}, code_paths=(path,))

    assert [(item.path, item.reason) for item in violations] == [
        (path, "governed code path must not be a symlink")
    ]
