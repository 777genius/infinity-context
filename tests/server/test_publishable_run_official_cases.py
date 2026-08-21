from __future__ import annotations

import stat
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
)
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT,
    SchedulerOfficialCaseRunScope,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_official_cases import (
    prepare_publishable_official_cases,
)
from publishable_run_outer_test_support import (
    PRIVATE_CASE_SENTINEL,
    SyntheticOfficialCaseProjection,
    private_run_files,
)
from scheduler_subscription_bridge_composition_test_support import (
    bridge_fleet_readiness,
    official_suite_and_manifests,
)


def test_prepares_and_exactly_replays_all_2040_synthetic_cases(tmp_path: Path) -> None:
    files = private_run_files(tmp_path)
    suite, expected_runs, expected_manifests, _ = official_suite_and_manifests(
        bridge_fleet_readiness()
    )
    first_projection = SyntheticOfficialCaseProjection()

    first = prepare_publishable_official_cases(
        suite=suite,
        projection=first_projection,
        config=files.config,
        secrets=files.secrets,
    )
    terminal = first.terminal
    manifest_authorities = tuple(item.authority for item in first.manifests)
    assert terminal.case_count == 2_040
    assert terminal.page_count == 9
    assert first.runs == expected_runs
    assert manifest_authorities == tuple(item.authority for item in expected_manifests)
    assert first_projection.emitted_case_count == 2_040
    assert max(limit for _, _, limit in first_projection.page_calls) == (
        SCHEDULER_OFFICIAL_CASE_PAGE_ROW_LIMIT
    )
    assert len(first_projection.page_calls) == 11
    for run, index in ((first.runs[0], 0), (first.runs[1], 499)):
        benchmark = run.binding.profile.benchmark.value
        readback = first.reader.read_exact(
            key=_scope(suite, run).case_key(
                case_index=index,
                case_id=f"{benchmark}-case-{index}",
                case_alias=f"{benchmark}-{index}",
                authority_root_sha256=terminal.authority_root_sha256,
            )
        )
        assert readback.case.question == f"{PRIVATE_CASE_SENTINEL}:{benchmark}:{index}"
    first.close()

    replay_projection = SyntheticOfficialCaseProjection()
    replay = prepare_publishable_official_cases(
        suite=suite,
        projection=replay_projection,
        config=files.config,
        secrets=files.secrets,
    )
    try:
        assert replay.terminal == terminal
        assert tuple(item.authority for item in replay.manifests) == manifest_authorities
        assert replay_projection.emitted_case_count == 2_040
        assert stat.S_IMODE(files.config.official_case_authority_path.stat().st_mode) == 0o600
    finally:
        replay.close()


def test_incomplete_projection_fails_closed_without_scheduler_state(tmp_path: Path) -> None:
    files = private_run_files(tmp_path)
    suite, *_ = official_suite_and_manifests(bridge_fleet_readiness())

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_official_case_projection_incomplete",
    ):
        prepare_publishable_official_cases(
            suite=suite,
            projection=_IncompleteProjection(),
            config=files.config,
            secrets=files.secrets,
        )

    assert files.config.official_case_authority_path.exists()
    assert all(not path.exists() for path in files.config.scheduler_database_paths)
    assert not files.config.suite_seal_database_path.exists()


def test_partial_official_authority_build_replays_and_resumes_exactly(
    tmp_path: Path,
) -> None:
    files = private_run_files(tmp_path)
    suite, *_ = official_suite_and_manifests(bridge_fleet_readiness())
    interrupted = SyntheticOfficialCaseProjection(crash_on_page_call=4)

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_official_case_projection_failed",
    ):
        prepare_publishable_official_cases(
            suite=suite,
            projection=interrupted,
            config=files.config,
            secrets=files.secrets,
        )

    assert files.config.official_case_authority_path.exists()
    assert all(not path.exists() for path in files.config.scheduler_database_paths)
    resumed_projection = SyntheticOfficialCaseProjection()
    prepared = prepare_publishable_official_cases(
        suite=suite,
        projection=resumed_projection,
        config=files.config,
        secrets=files.secrets,
    )
    try:
        assert prepared.terminal.case_count == 2_040
        assert resumed_projection.emitted_case_count == 2_040
        assert prepared.reader.authority_root_sha256 == (prepared.terminal.authority_root_sha256)
    finally:
        prepared.close()


class _IncompleteProjection(SyntheticOfficialCaseProjection):
    def read_page(self, *, run, start_case_index: int, limit: int):
        if run.binding.profile.benchmark.value == "locomo" and start_case_index >= 512:
            return ()
        return super().read_page(
            run=run,
            start_case_index=start_case_index,
            limit=limit,
        )


def _scope(suite, run) -> SchedulerOfficialCaseRunScope:
    binding = run.binding
    return SchedulerOfficialCaseRunScope(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        run_binding_commitment_sha256=binding.binding_commitment_sha256,
        run_id=binding.run_id,
        benchmark=binding.profile.benchmark,
        scheduler_profile_id=binding.profile.profile_id,
        publishable_profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        publishable_profile_sha256=PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
        methodology_sha256=suite.methodology_sha256,
        dataset_sha256=binding.dataset_sha256,
        case_manifest_sha256=binding.case_manifest_sha256,
        case_count=binding.profile.case_count,
    )
