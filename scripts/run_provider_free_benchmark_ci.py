"""Collect, guard, and run the provider-free benchmark CI selections."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / ".github" / "benchmark-provider-free-tests.toml"

_CREDENTIAL_ENVIRONMENT_NAMES = (
    "OPENAI_API_KEY",
    "MEMORY_OPENAI_API_KEY",
    "MEMORY_AGENT_BENCH_OPENAI_API_KEY",
    "MEM0_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "COHERE_API_KEY",
    "VOYAGE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)

_PROVIDER_FREE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "MEM0_TELEMETRY": "false",
    "MEM0_TELEMETRY_SAMPLE_RATE": "0",
    "QDRANT__TELEMETRY_DISABLED": "true",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "PYTHONHASHSEED": "0",
}


class CollectionGuardError(RuntimeError):
    """Raised when the explicit CI selection does not collect as promised."""


@dataclass(frozen=True)
class Suite:
    name: str
    project_directory: Path
    minimum_selected_nodes: int
    deferred_node_ids: tuple[str, ...]
    test_paths: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    collected_node_ids: tuple[str, ...]
    selected_node_ids: tuple[str, ...]
    name_guard_excluded_node_ids: tuple[str, ...]
    deferred_node_ids: tuple[str, ...]
    selected_counts_by_path: Mapping[str, int]


def load_suites(config_path: Path = CONFIG_PATH) -> tuple[dict[str, Suite], tuple[str, ...]]:
    document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise CollectionGuardError("unsupported benchmark CI selection schema")

    raw_forbidden_terms = document.get("forbidden_node_terms")
    if not isinstance(raw_forbidden_terms, list):
        raise CollectionGuardError("forbidden node terms must be unique lowercase words")
    forbidden_terms = tuple(raw_forbidden_terms)
    if not forbidden_terms or any(not _valid_term(term) for term in forbidden_terms):
        raise CollectionGuardError("forbidden node terms must be unique lowercase words")
    if len(set(forbidden_terms)) != len(forbidden_terms):
        raise CollectionGuardError("forbidden node terms must be unique lowercase words")

    raw_suites = document.get("suites")
    if not isinstance(raw_suites, dict) or not raw_suites:
        raise CollectionGuardError("benchmark CI selection must define suites")

    suites: dict[str, Suite] = {}
    for name, raw_suite in raw_suites.items():
        if not isinstance(name, str) or not isinstance(raw_suite, dict):
            raise CollectionGuardError("benchmark CI suite entry is invalid")
        project_directory = _project_directory(raw_suite.get("project_directory"))
        minimum_selected_nodes = raw_suite.get("minimum_selected_nodes")
        if (
            not isinstance(minimum_selected_nodes, int)
            or isinstance(minimum_selected_nodes, bool)
            or minimum_selected_nodes < 1
        ):
            raise CollectionGuardError("suite minimum_selected_nodes must be a positive integer")
        test_paths = _test_paths(
            project_directory,
            raw_suite.get("test_paths"),
            forbidden_terms,
        )
        deferred_node_ids = _deferred_node_ids(
            test_paths,
            raw_suite.get("deferred_node_ids"),
            forbidden_terms,
        )
        suites[name] = Suite(
            name=name,
            project_directory=project_directory,
            minimum_selected_nodes=minimum_selected_nodes,
            deferred_node_ids=deferred_node_ids,
            test_paths=test_paths,
        )
    return suites, forbidden_terms


def select_node_ids(
    suite: Suite,
    collection_output: str,
    forbidden_terms: Sequence[str],
) -> Selection:
    """Parse quiet pytest collection output and enforce per-file coverage."""

    collected_by_path: dict[str, list[str]] = {path: [] for path in suite.test_paths}
    collected: list[str] = []
    for line in collection_output.splitlines():
        candidate = line.strip()
        for path in suite.test_paths:
            if candidate.startswith(f"{path}::"):
                collected.append(candidate)
                collected_by_path[path].append(candidate)
                break

    if len(collected) != len(set(collected)):
        raise CollectionGuardError(f"{suite.name}: pytest emitted duplicate node IDs")

    missing_collection = [path for path, nodes in collected_by_path.items() if not nodes]
    if missing_collection:
        joined = ", ".join(missing_collection)
        raise CollectionGuardError(f"{suite.name}: no tests collected from {joined}")

    collected_node_ids = set(collected)
    missing_deferred = [
        node_id for node_id in suite.deferred_node_ids if node_id not in collected_node_ids
    ]
    if missing_deferred:
        joined = ", ".join(missing_deferred)
        raise CollectionGuardError(f"{suite.name}: deferred nodes were not collected: {joined}")

    deferred_node_ids = set(suite.deferred_node_ids)
    selected: list[str] = []
    name_guard_excluded: list[str] = []
    deferred: list[str] = []
    selected_counts: dict[str, int] = {}
    for path, nodes in collected_by_path.items():
        selected_for_path = [
            node
            for node in nodes
            if not _has_forbidden_test_name(node, forbidden_terms) and node not in deferred_node_ids
        ]
        if not selected_for_path:
            raise CollectionGuardError(
                f"{suite.name}: name guard excluded every test collected from {path}"
            )
        selected.extend(selected_for_path)
        name_guard_excluded.extend(
            node for node in nodes if _has_forbidden_test_name(node, forbidden_terms)
        )
        deferred.extend(node for node in nodes if node in deferred_node_ids)
        selected_counts[path] = len(selected_for_path)

    if len(selected) < suite.minimum_selected_nodes:
        raise CollectionGuardError(
            f"{suite.name}: selected {len(selected)} nodes; "
            f"minimum is {suite.minimum_selected_nodes}"
        )

    return Selection(
        collected_node_ids=tuple(collected),
        selected_node_ids=tuple(selected),
        name_guard_excluded_node_ids=tuple(name_guard_excluded),
        deferred_node_ids=tuple(deferred),
        selected_counts_by_path=selected_counts,
    )


def _valid_term(value: object) -> bool:
    return isinstance(value, str) and value.isalpha() and value == value.casefold()


def _project_directory(value: object) -> Path:
    if not isinstance(value, str):
        raise CollectionGuardError("suite project_directory must be a string")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
        raise CollectionGuardError("suite project_directory must stay inside the repository")
    project_directory = (REPOSITORY_ROOT / relative).resolve()
    if not project_directory.is_relative_to(REPOSITORY_ROOT) or not project_directory.is_dir():
        raise CollectionGuardError("suite project_directory does not exist in the repository")
    return project_directory


def _test_paths(
    project_directory: Path,
    value: object,
    forbidden_terms: Sequence[str],
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CollectionGuardError("suite test_paths must be a non-empty list")
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise CollectionGuardError("suite test path must be a string")
        relative = PurePosixPath(item)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != item:
            raise CollectionGuardError("suite test path must be a normalized relative path")
        if not item.endswith(".py") or not (project_directory / relative).is_file():
            raise CollectionGuardError(f"suite test path does not name a Python file: {item}")
        path_tokens = set(re.findall(r"[a-z]+", relative.stem.casefold()))
        if path_tokens.intersection(forbidden_terms):
            raise CollectionGuardError(f"suite test path overclaims provider-free scope: {item}")
        paths.append(item)
    if len(paths) != len(set(paths)):
        raise CollectionGuardError("suite test paths must be unique")
    return tuple(paths)


def _deferred_node_ids(
    test_paths: Sequence[str],
    value: object,
    forbidden_terms: Sequence[str],
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CollectionGuardError("suite deferred_node_ids must be a list")
    node_ids: list[str] = []
    for item in value:
        if not isinstance(item, str) or "::" not in item:
            raise CollectionGuardError("suite deferred node must be an exact pytest node ID")
        path, _ = item.split("::", maxsplit=1)
        if path not in test_paths:
            raise CollectionGuardError("suite deferred node must belong to a selected test path")
        if _has_forbidden_test_name(item, forbidden_terms):
            raise CollectionGuardError("suite deferred node name must remain provider-free")
        node_ids.append(item)
    if len(node_ids) != len(set(node_ids)):
        raise CollectionGuardError("suite deferred node IDs must be unique")
    return tuple(node_ids)


def _has_forbidden_test_name(node_id: str, forbidden_terms: Sequence[str]) -> bool:
    _, test_name = node_id.split("::", maxsplit=1)
    tokens = set(re.findall(r"[a-z]+", test_name.casefold()))
    return any(term in tokens for term in forbidden_terms)


def _provider_free_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in _CREDENTIAL_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment.update(_PROVIDER_FREE_ENVIRONMENT)
    return environment


def _collect(suite: Suite, environment: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    command = (
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-o",
        "addopts=",
        *suite.test_paths,
    )
    print(f"benchmark-ci collect command: {shlex.join(command)}", flush=True)
    completed = subprocess.run(
        command,
        cwd=suite.project_directory,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(completed.stdout, end="", flush=True)
    return completed


def _run(
    suite: Suite,
    selected_node_ids: Sequence[str],
    environment: Mapping[str, str],
    *,
    run_kind: str,
) -> int:
    command = (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-ra",
        "--tb=short",
        "-o",
        "addopts=",
        *selected_node_ids,
    )
    print(
        f"benchmark-ci run: suite={suite.name} kind={run_kind} "
        f"exact_node_count={len(selected_node_ids)}",
        flush=True,
    )
    return subprocess.run(
        command,
        cwd=suite.project_directory,
        env=environment,
        check=False,
    ).returncode


def run_suite(
    suite: Suite,
    forbidden_terms: Sequence[str],
    *,
    deferred_only: bool = False,
) -> int:
    environment = _provider_free_environment()
    print(
        f"benchmark-ci selection: suite={suite.name} "
        f"explicit_path_count={len(suite.test_paths)} "
        f"minimum_selected_nodes={suite.minimum_selected_nodes}",
        flush=True,
    )
    for path in suite.test_paths:
        print(f"benchmark-ci selected path: {path}", flush=True)

    completed = _collect(suite, environment)
    if completed.returncode:
        return completed.returncode

    selection = select_node_ids(suite, completed.stdout, forbidden_terms)
    print(
        "benchmark-ci collection: "
        f"suite={suite.name} collected={len(selection.collected_node_ids)} "
        f"selected={len(selection.selected_node_ids)} "
        f"name_guard_excluded={len(selection.name_guard_excluded_node_ids)} "
        f"deferred={len(selection.deferred_node_ids)}",
        flush=True,
    )
    for path, count in selection.selected_counts_by_path.items():
        print(f"benchmark-ci collected path: {path} selected={count}", flush=True)
    for node_id in selection.name_guard_excluded_node_ids:
        print(f"benchmark-ci name-guard exclusion: {node_id}", flush=True)
    for node_id in selection.deferred_node_ids:
        print(f"benchmark-ci deferred long node: {node_id}", flush=True)

    if deferred_only:
        if not selection.deferred_node_ids:
            raise CollectionGuardError(f"{suite.name}: no deferred nodes are configured")
        return _run(
            suite,
            selection.deferred_node_ids,
            environment,
            run_kind="deferred-only",
        )
    return _run(
        suite,
        selection.selected_node_ids,
        environment,
        run_kind="mandatory",
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", help="suite key from the benchmark CI selection config")
    parser.add_argument(
        "--deferred-only",
        action="store_true",
        help="run only the explicitly deferred synthetic contracts",
    )
    parsed = parser.parse_args(arguments)
    try:
        suites, forbidden_terms = load_suites()
        suite = suites.get(parsed.suite)
        if suite is None:
            choices = ", ".join(sorted(suites))
            raise CollectionGuardError(f"unknown benchmark CI suite; choose one of: {choices}")
        return run_suite(suite, forbidden_terms, deferred_only=parsed.deferred_only)
    except CollectionGuardError as error:
        print(f"benchmark-ci collection guard failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
