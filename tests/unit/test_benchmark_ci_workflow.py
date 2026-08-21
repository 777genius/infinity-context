from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.run_provider_free_benchmark_ci import (
    CollectionGuardError,
    Suite,
    load_suites,
    select_node_ids,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "infinity-context-ci.yml"
RUNNER = PROJECT_ROOT / "scripts" / "run_provider_free_benchmark_ci.py"
NESTED_ROOT = PROJECT_ROOT / "benchmarks" / "mem0-oss-adapter-v5"


def _workflow_job(name: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = f"\n  {name}:\n"
    assert workflow.count(marker) == 1
    tail = workflow.split(marker, maxsplit=1)[1]
    next_job = re.search(r"\n  [a-zA-Z0-9_-]+:\n", tail)
    return tail if next_job is None else tail[: next_job.start()]


def _benchmark_job() -> str:
    return _workflow_job("benchmark-contracts")


def test_benchmark_job_is_mandatory_locked_and_provider_free() -> None:
    job = _benchmark_job()
    quality_job = _workflow_job("quality")
    runner = RUNNER.read_text(encoding="utf-8")

    assert "name: Provider-free benchmark contracts" in job
    assert "runs-on: ubuntu-latest" in job
    assert "timeout-minutes: 45" in job
    assert "if:" not in job
    assert "continue-on-error:" not in job
    assert "actions/checkout@v7.0.1" in job
    assert "actions/setup-python@v7.0.0" in job
    assert 'python-version: "3.11.15"' in job
    assert 'python -m pip install --disable-pip-version-check "uv==0.11.28"' in job
    assert "pip install --upgrade" not in job

    assert "uv lock --check" in job
    assert "uv lock --directory benchmarks/mem0-oss-adapter-v5 --check" in job
    assert "uv sync --extra dev --frozen" in job
    assert "uv sync --directory benchmarks/mem0-oss-adapter-v5 --group dev --frozen" in job
    assert "uv run --frozen --no-sync python" in job
    assert "uv run --directory benchmarks/mem0-oss-adapter-v5 --frozen --no-sync" in job
    assert "run_provider_free_benchmark_ci.py root" in job
    assert 'run_provider_free_benchmark_ci.py" mem0-v5' in job

    for name in (
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
    ):
        assert f'{name}: ""' in job
    assert "${{ secrets." not in job
    assert "--allow-live" not in job
    assert "--allow-subscription-dispatch" not in job
    assert 'PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"' in job
    assert 'PYTHONHASHSEED: "0"' in job
    assert '"--collect-only"' in runner
    assert '"-ra"' in runner
    assert "*selected_node_ids" in runner
    assert "minimum_selected_nodes" in runner
    assert "- benchmark-contracts" in quality_job
    assert (
        "BENCHMARK_CONTRACTS_RESULT: ${{ needs.benchmark-contracts.result }}"
        in quality_job
    )
    assert 'test "$BENCHMARK_CONTRACTS_RESULT" = "success"' in quality_job


def test_synthetic_2040_lane_is_opt_in_and_provider_free() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = _workflow_job("benchmark-synthetic-2040")
    test_suite_job = _workflow_job("test_suite")

    assert "synthetic_2040:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "name: Optional synthetic 2040 benchmark contracts" in job
    assert "if: github.event_name == 'workflow_dispatch' && inputs.synthetic_2040" in job
    assert "timeout-minutes: 90" in job
    assert "actions/checkout@v7.0.1" in job
    assert "actions/setup-python@v7.0.0" in job
    assert 'python-version: "3.11.15"' in job
    assert '"uv==0.11.28"' in job
    assert "uv lock --check" in job
    assert "uv sync --extra dev --frozen" in job
    assert "scripts/run_provider_free_benchmark_ci.py root --deferred-only" in job
    assert "continue-on-error:" not in job
    assert "benchmarks/mem0-oss-adapter-v5" not in job
    assert "${{ secrets." not in job
    assert "--allow-live" not in job
    assert '-m "not synthetic_2040"' in test_suite_job


def test_benchmark_selection_inventory_is_explicit_and_complete() -> None:
    suites, forbidden_terms = load_suites()

    assert forbidden_terms == ("full", "production", "paid")
    assert set(suites) == {"root", "mem0-v5"}
    root_paths = set(suites["root"].test_paths)
    assert suites["root"].project_directory == PROJECT_ROOT
    assert suites["root"].minimum_selected_nodes == 360
    assert set(suites["root"].deferred_node_ids) == {
        "tests/unit/test_publishable_durable_scheduler_sqlite_security.py::"
        "test_runner_exact_two_run_cardinality_is_2040_cases_and_8160_calls",
        "tests/server/test_publishable_scheduler_official_request_renderer.py::"
        "test_fake_2040_case_manifest_traversal_keeps_reads_one_case_bounded",
        "tests/server/test_scheduler_official_sqlite_authorities.py::"
        "test_bounded_2040_case_streaming_build_and_indexed_read_traversal",
        "tests/server/test_scheduler_subscription_bridge_composition.py::"
        "test_official_composition_suite_seal_replay_and_synthetic_2040_traversal",
        "tests/server/test_publishable_composition_synthetic_2040.py::"
        "test_composition_traverses_exact_2040_pairs_and_replays_with_zero_calls",
    }
    assert root_paths == {
        "tests/unit/test_publishable_durable_scheduler_manifest.py",
        "tests/unit/test_publishable_durable_scheduler_state.py",
        "tests/unit/test_publishable_durable_scheduler_sqlite.py",
        "tests/unit/test_publishable_durable_scheduler_sqlite_security.py",
        "tests/unit/test_publishable_durable_scheduler_v2.py",
        "tests/unit/test_publishable_durable_scheduler_v2_security.py",
        "tests/server/test_scheduler_subscription_bridge_composition.py",
        "tests/server/test_scheduler_retrieval_capture_service.py",
        "tests/server/test_scheduler_retrieval_capture_composition.py",
        "tests/server/test_scheduler_retrieval_capture_http_adapters.py",
        "tests/server/test_scheduler_paired_outcome_contracts.py",
        "tests/server/test_publishable_scheduler_official_request_renderer.py",
        "tests/server/test_scheduler_official_sqlite_authorities.py",
        "tests/server/test_publishable_composition_synthetic_2040.py",
        "tests/server/test_publishable_run_attestation.py",
        "tests/server/test_subscription_runtime_bridge_provider_receipt_replay.py",
        "tests/server/test_publishable_canary_activation_evidence.py",
        "tests/server/test_publishable_canary_cli.py",
        "tests/server/test_publishable_canary_composition.py",
        "tests/server/test_publishable_canary_orchestrator.py",
        "tests/unit/test_publishable_canary_authority.py",
        "tests/architecture/test_cognitive_memory_boundaries.py",
        "tests/architecture/test_feature_owned_vertical_slices.py",
        "tests/architecture/test_file_size_boundaries.py",
        "tests/architecture/test_mem0_v5_live_micro_canary_topology.py",
        "tests/architecture/test_memory_boundaries.py",
        "tests/architecture/test_memory_comparison_provider_boundaries.py",
        "tests/architecture/test_publishable_checkpoint_journal_boundaries.py",
        "tests/architecture/test_resumable_operation_journal_boundaries.py",
    }

    nested = suites["mem0-v5"]
    assert nested.project_directory == NESTED_ROOT
    assert nested.minimum_selected_nodes == 190
    assert nested.deferred_node_ids == ()
    nested_paths = set(nested.test_paths)
    package_paths = {
        "tests/test_package_import_boundary.py",
        "tests/test_publishable_input_provider.py",
        "tests/test_publishable_provider_attestation.py",
        "tests/test_publishable_run_provider_http.py",
        "tests/test_publishable_run_provider_preflight.py",
        "tests/test_composition_provider_free.py",
    }
    e2e_paths = {
        path.relative_to(NESTED_ROOT).as_posix()
        for path in (NESTED_ROOT / "e2e" / "tests").glob("test_*.py")
    }
    assert {path for path in nested_paths if path.startswith("tests/")} == package_paths
    assert {path for path in nested_paths if path.startswith("e2e/tests/")} == e2e_paths
    assert all(
        not set(Path(path).stem.casefold().split("_")).intersection(forbidden_terms)
        for path in nested_paths
    )


def test_collection_guard_requires_each_path_and_filters_overclaims() -> None:
    suite = Suite(
        name="sample",
        project_directory=PROJECT_ROOT,
        minimum_selected_nodes=2,
        deferred_node_ids=("e2e/tests/two.py::test_synthetic_2040_contract",),
        test_paths=("tests/one.py", "e2e/tests/two.py"),
    )
    collection = "\n".join(
        (
            "tests/one.py::test_provider_free_contract",
            "tests/one.py::test_paid_contract",
            "e2e/tests/two.py::test_fake_receipt",
            "e2e/tests/two.py::test_synthetic_2040_contract",
            "4 tests collected in 0.01s",
        )
    )

    selection = select_node_ids(suite, collection, ("full", "production", "paid"))

    assert selection.collected_node_ids == (
        "tests/one.py::test_provider_free_contract",
        "tests/one.py::test_paid_contract",
        "e2e/tests/two.py::test_fake_receipt",
        "e2e/tests/two.py::test_synthetic_2040_contract",
    )
    assert selection.selected_node_ids == (
        "tests/one.py::test_provider_free_contract",
        "e2e/tests/two.py::test_fake_receipt",
    )
    assert selection.name_guard_excluded_node_ids == ("tests/one.py::test_paid_contract",)
    assert selection.deferred_node_ids == ("e2e/tests/two.py::test_synthetic_2040_contract",)
    assert selection.selected_counts_by_path == {
        "tests/one.py": 1,
        "e2e/tests/two.py": 1,
    }

    with pytest.raises(CollectionGuardError, match="no tests collected"):
        select_node_ids(
            suite,
            "tests/one.py::test_provider_free_contract\n",
            ("full", "production", "paid"),
        )
