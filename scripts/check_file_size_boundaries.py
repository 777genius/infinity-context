"""Enforce monotonic line budgets for tracked source files."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_NEW_FILE_LINES = 1000
CODE_ROOTS = frozenset({"frontend", "packages", "scripts", "tests"})
CODE_SUFFIXES = frozenset({".dart", ".js", ".py", ".rs", ".ts", ".tsx"})
IGNORED_PATH_PARTS = frozenset(
    {
        ".dart_tool",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "generated",
        "node_modules",
    }
)
DEFAULT_BASELINE_PATH = Path("tests/architecture/file_size_legacy_baseline.json")


class BaselineError(ValueError):
    """Raised when the checked-in legacy budget is malformed."""


@dataclass(frozen=True, slots=True)
class FileSizeViolation:
    """One actionable policy violation."""

    path: str
    reason: str
    actual_lines: int | None = None
    budget_lines: int | None = None

    def render(self) -> str:
        details = []
        if self.actual_lines is not None:
            details.append(f"actual={self.actual_lines}")
        if self.budget_lines is not None:
            details.append(f"budget={self.budget_lines}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"{self.path}: {self.reason}{suffix}"


def is_code_path(path: str) -> bool:
    """Return whether a repository-relative path is governed source code."""

    raw_parts = path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return False
    candidate = PurePosixPath(path)
    return (
        bool(candidate.parts)
        and candidate.parts[0] in CODE_ROOTS
        and candidate.suffix in CODE_SUFFIXES
        and not IGNORED_PATH_PARTS.intersection(candidate.parts)
    )


def load_baseline(path: Path) -> dict[str, int]:
    """Load and strictly validate the exact legacy line ceilings."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from exc
    return validate_baseline_payload(payload)


def validate_baseline_payload(payload: object) -> dict[str, int]:
    """Validate a decoded baseline from the worktree or a Git base ref."""

    if not isinstance(payload, dict):
        raise BaselineError("baseline must be a JSON object mapping paths to line ceilings")

    baseline: dict[str, int] = {}
    for raw_path, raw_budget in payload.items():
        if not isinstance(raw_path, str) or not is_code_path(raw_path):
            raise BaselineError(f"invalid governed code path in baseline: {raw_path!r}")
        if raw_path != PurePosixPath(raw_path).as_posix() or raw_path.startswith("/"):
            raise BaselineError(f"baseline path must be normalized and relative: {raw_path!r}")
        if isinstance(raw_budget, bool) or not isinstance(raw_budget, int):
            raise BaselineError(f"baseline ceiling for {raw_path} must be an integer")
        if raw_budget <= MAX_NEW_FILE_LINES:
            raise BaselineError(
                f"baseline ceiling for {raw_path} must exceed {MAX_NEW_FILE_LINES}; remove it"
            )
        baseline[raw_path] = raw_budget
    return baseline


def load_baseline_from_git_ref(
    repo_root: Path,
    ref: str,
    baseline_path: Path = DEFAULT_BASELINE_PATH,
) -> dict[str, int] | None:
    """Read the baseline at a Git ref, or return None for the one-time bootstrap."""

    relative_path = baseline_path.as_posix()
    command = ("git", "-C", str(repo_root), "show", f"{ref}:{relative_path}")
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        missing_probe = subprocess.run(
            ("git", "-C", str(repo_root), "cat-file", "-e", f"{ref}^{{commit}}"),
            capture_output=True,
        )
        if missing_probe.returncode != 0:
            raise BaselineError(f"base ref does not resolve to a commit: {ref}")
        return None
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError(f"baseline at {ref} is not valid JSON: {exc}") from exc
    return validate_baseline_payload(payload)


def check_baseline_monotonicity(
    current: Mapping[str, int],
    base: Mapping[str, int],
) -> tuple[FileSizeViolation, ...]:
    """Reject newly budgeted files and increases relative to an immutable base ref."""

    violations: list[FileSizeViolation] = []
    for path, current_budget in sorted(current.items()):
        base_budget = base.get(path)
        if base_budget is None:
            violations.append(
                FileSizeViolation(
                    path,
                    "new legacy baseline entries are prohibited",
                    budget_lines=current_budget,
                )
            )
        elif current_budget > base_budget:
            violations.append(
                FileSizeViolation(
                    path,
                    "legacy baseline ceiling increased relative to base ref",
                    actual_lines=current_budget,
                    budget_lines=base_budget,
                )
            )
    return tuple(violations)


def repository_code_paths(repo_root: Path) -> tuple[str, ...]:
    """List tracked and prospective tracked code, honoring repository ignores."""

    command = (
        "git",
        "-C",
        str(repo_root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *sorted(CODE_ROOTS),
    )
    try:
        output = subprocess.run(command, check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"cannot enumerate repository files: {exc}") from exc
    paths = (value.decode("utf-8") for value in output.split(b"\0") if value)
    return tuple(sorted(path for path in paths if is_code_path(path)))


def line_count(path: Path) -> int:
    """Count logical text lines consistently with Python splitlines."""

    return len(path.read_text(encoding="utf-8").splitlines())


def check_file_size_boundaries(
    repo_root: Path,
    baseline: Mapping[str, int],
    *,
    code_paths: Iterable[str] | None = None,
) -> tuple[FileSizeViolation, ...]:
    """Evaluate new-file limits and exact monotonic legacy budgets."""

    supplied_paths = set(code_paths if code_paths is not None else repository_code_paths(repo_root))
    governed_paths = {path for path in supplied_paths if is_code_path(path)}
    violations: list[FileSizeViolation] = []

    for invalid_path in sorted(supplied_paths - governed_paths):
        violations.append(FileSizeViolation(invalid_path, "invalid governed code path"))

    for baseline_path in sorted(baseline):
        baseline_target = repo_root / baseline_path
        if baseline_path not in governed_paths or (
            not baseline_target.is_symlink() and not baseline_target.is_file()
        ):
            violations.append(FileSizeViolation(baseline_path, "stale or deleted baseline entry"))

    for relative_path in sorted(governed_paths):
        path = repo_root / relative_path
        if path.is_symlink():
            violations.append(
                FileSizeViolation(relative_path, "governed code path must not be a symlink")
            )
            continue
        if not path.is_file():
            continue
        actual = line_count(path)
        budget = baseline.get(relative_path)
        if budget is None:
            if actual > MAX_NEW_FILE_LINES:
                violations.append(
                    FileSizeViolation(
                        relative_path,
                        "new or unbudgeted code file exceeds the 1000-line limit",
                        actual_lines=actual,
                        budget_lines=MAX_NEW_FILE_LINES,
                    )
                )
            continue
        if actual > budget:
            reason = "legacy file grew above its frozen ceiling"
        elif actual < budget:
            reason = (
                "legacy file shrank; lower its baseline ceiling"
                if actual > MAX_NEW_FILE_LINES
                else "legacy file is now within 1000 lines; remove its baseline entry"
            )
        else:
            continue
        violations.append(
            FileSizeViolation(
                relative_path,
                reason,
                actual_lines=actual,
                budget_lines=budget,
            )
        )

    return tuple(violations)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--base-ref", help="Git ref whose baseline ceilings may only decrease")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    baseline_path = args.baseline or repo_root / DEFAULT_BASELINE_PATH
    try:
        baseline = load_baseline(baseline_path)
        violations = list(check_file_size_boundaries(repo_root, baseline))
        if args.base_ref:
            base_baseline = load_baseline_from_git_ref(repo_root, args.base_ref)
            if base_baseline is not None:
                violations.extend(check_baseline_monotonicity(baseline, base_baseline))
    except (BaselineError, RuntimeError) as exc:
        print(f"file-size boundary configuration error: {exc}")
        return 2
    if violations:
        print("file-size boundary violations:")
        for violation in violations:
            print(f"- {violation.render()}")
        return 1
    print(f"file-size boundaries passed ({len(baseline)} frozen legacy ceilings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
