from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_server.publishable_durable_scheduler import (
    SCHEDULER_PAID_GO_READY,
    SchedulerCallStage,
    SchedulerContractError,
    SchedulerPageQuery,
    build_scheduler_manifest,
    run_authority_from_suite,
)
from publishable_durable_scheduler_test_support import (
    InMemoryManifestPageStore,
    built_runs,
    suite_and_cases,
)


@pytest.fixture(scope="module")
def manifests():
    return built_runs()


def test_exact_two_run_counts_order_and_case_aligned_shards(manifests) -> None:
    _, (locomo_run, locomo), (lme_run, lme) = manifests

    assert locomo.authority.call_count == 6160
    assert len(locomo.shards) == 25
    assert tuple(len(item.calls) for item in locomo.shards) == (256,) * 24 + (16,)
    assert lme.authority.call_count == 2000
    assert len(lme.shards) == 8
    assert tuple(len(item.calls) for item in lme.shards) == (256,) * 7 + (208,)
    assert locomo_run.binding.profile.case_count == 1540
    assert lme_run.binding.profile.case_count == 500

    for run, manifest in ((locomo_run, locomo), (lme_run, lme)):
        calls = tuple(call for shard in manifest.shards for call in shard.calls)
        assert tuple(call.ordinal for call in calls) == tuple(range(len(calls)))
        assert all(
            shard.start_ordinal % 4 == shard.end_ordinal % 4 == 0 for shard in manifest.shards
        )
        for case_index in range(run.binding.profile.case_count):
            group = calls[case_index * 4 : case_index * 4 + 4]
            assert tuple((call.backend_index, call.stage) for call in group) == (
                (0, SchedulerCallStage.ANSWER),
                (0, SchedulerCallStage.JUDGE),
                (1, SchedulerCallStage.ANSWER),
                (1, SchedulerCallStage.JUDGE),
            )
            assert group[1].depends_on_logical_call_id == group[0].logical_call_id
            assert group[3].depends_on_logical_call_id == group[2].logical_call_id


def test_suite_and_run_authorities_bind_every_manifest(manifests) -> None:
    _, (locomo_run, locomo), (lme_run, lme) = manifests

    assert locomo.authority.suite_authority_sha256 == lme.authority.suite_authority_sha256
    assert locomo.authority.run_authority_sha256 == locomo_run.commitment_sha256
    assert lme.authority.run_authority_sha256 == lme_run.commitment_sha256
    assert locomo.authority.run_authority_sha256 != lme.authority.run_authority_sha256
    assert locomo.authority.ordered_call_root_sha256 != lme.authority.ordered_call_root_sha256


def test_case_reorder_and_cross_suite_run_selection_reject() -> None:
    suite, locomo_cases, _ = suite_and_cases()
    run = run_authority_from_suite(suite, run_index=0)
    reordered = (locomo_cases[1], locomo_cases[0], *locomo_cases[2:])

    with pytest.raises(SchedulerContractError, match="case_manifest_binding"):
        build_scheduler_manifest(run, suite=suite, ordered_cases=reordered)
    with pytest.raises(SchedulerContractError, match="selection"):
        run_authority_from_suite(suite, run_index=2)


def test_deadline_and_token_ceilings_are_authority_bound() -> None:
    suite, locomo_cases, _ = suite_and_cases()
    run = run_authority_from_suite(suite, run_index=0)
    changed_limits = replace(
        run.binding.limits,
        dispatch_deadline_unix_ms=run.binding.limits.dispatch_deadline_unix_ms + 1,
    )
    changed_binding = replace(run.binding, limits=changed_limits)
    changed_suite = replace(suite, ordered_runs=(changed_binding, suite.ordered_runs[1]))
    changed_run = run_authority_from_suite(changed_suite, run_index=0)

    assert changed_limits.commitment_sha256 != run.binding.limits.commitment_sha256
    assert changed_run.commitment_sha256 != run.commitment_sha256
    assert changed_suite.commitment_sha256 != suite.commitment_sha256
    with pytest.raises(SchedulerContractError, match="suite_run_authority_binding"):
        build_scheduler_manifest(
            run,
            suite=changed_suite,
            ordered_cases=locomo_cases,
        )


def test_manifest_page_double_enforces_bounded_queries(manifests) -> None:
    _, (_, locomo), (_, lme) = manifests
    store = InMemoryManifestPageStore((locomo, lme))
    first = store.read(
        SchedulerPageQuery(
            run_id=locomo.authority.run_id,
            run_manifest_authority_sha256=locomo.authority.commitment_sha256,
            shard_index=0,
            limit=256,
        )
    )
    assert len(first.calls) == 256
    assert store.max_requested_limit == 256

    with pytest.raises(SchedulerContractError, match="page_query_invalid"):
        SchedulerPageQuery(
            run_id=locomo.authority.run_id,
            run_manifest_authority_sha256=locomo.authority.commitment_sha256,
            shard_index=0,
            limit=257,
        )
    with pytest.raises(SchedulerContractError, match="limit_exceeded"):
        store.read(
            SchedulerPageQuery(
                run_id=locomo.authority.run_id,
                run_manifest_authority_sha256=locomo.authority.commitment_sha256,
                shard_index=0,
                limit=255,
            )
        )


def test_standalone_contract_is_explicitly_not_paid_go() -> None:
    assert SCHEDULER_PAID_GO_READY is False
