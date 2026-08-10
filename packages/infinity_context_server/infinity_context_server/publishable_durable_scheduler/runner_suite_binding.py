"""Frozen-suite and durable cross-store seal binding checks."""

from __future__ import annotations

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerBenchmark,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    SchedulerRunnerError,
    SchedulerRunStoreSpec,
    SchedulerSuiteSeal,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SchedulerSQLiteError,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.suite_seal_store import (
    SQLiteSchedulerSuiteSealStore,
)


def require_exact_suite(
    suite: SchedulerSuiteAuthority,
    specs: tuple[SchedulerRunStoreSpec, SchedulerRunStoreSpec],
) -> None:
    """Reject any drift from the exact two-run publishable suite."""

    expected_profiles = (
        (SchedulerBenchmark.LOCOMO, 1_540, 6_160),
        (SchedulerBenchmark.LONGMEMEVAL, 500, 2_000),
    )
    for index, (spec, profile) in enumerate(zip(specs, expected_profiles, strict=True)):
        expected_run = run_authority_from_suite(suite, run_index=index)
        manifest = spec.manifest
        if (
            spec.run != expected_run
            or (
                spec.run.binding.profile.benchmark,
                spec.run.binding.profile.case_count,
                spec.run.binding.profile.call_count,
            )
            != profile
            or manifest.authority.run_authority_sha256 != spec.run.commitment_sha256
            or manifest.authority.suite_authority_sha256 != suite.commitment_sha256
            or manifest.authority.case_manifest_sha256 != spec.run.binding.case_manifest_sha256
            or manifest.authority.call_count != profile[2]
        ):
            _fail("scheduler_runner_frozen_suite_invalid")
    if (
        sum(item.run.binding.profile.case_count for item in specs) != PUBLISHABLE_SUITE_CASE_COUNT
        or sum(item.run.binding.profile.call_count for item in specs)
        != PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
    ):
        _fail("scheduler_runner_frozen_suite_invalid")


def read_bound_suite_seal(
    *,
    suite: SchedulerSuiteAuthority,
    runs: tuple[SchedulerRunAuthority, SchedulerRunAuthority],
    stores: tuple[SQLiteDurableSchedulerStore, SQLiteDurableSchedulerStore],
    seal_store: SQLiteSchedulerSuiteSealStore,
) -> SchedulerSuiteSeal | None:
    """Return a seal only when both authenticated run heads bind to it exactly."""

    seal = seal_store.read()
    if seal is None:
        return None
    if (
        seal.suite_authority_sha256 != suite.commitment_sha256
        or seal.runtime_provenance_sha256 != suite.runtime_provenance_sha256
        or seal.ordered_run_authority_sha256 != tuple(run.commitment_sha256 for run in runs)
    ):
        _fail("scheduler_runner_suite_seal_divergent")
    try:
        for store in stores:
            store.verify_suite_seal_binding(
                suite_seal_sha256=seal.commitment_sha256,
            )
    except SchedulerSQLiteError as error:
        raise SchedulerRunnerError("scheduler_runner_suite_seal_run_binding_invalid") from error
    return seal


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = ("read_bound_suite_seal", "require_exact_suite")
