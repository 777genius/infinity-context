from __future__ import annotations

import hashlib
from collections.abc import Callable

from infinity_context_server.publishable_durable_scheduler import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    BuiltSchedulerManifest,
    SchedulerBackendAuthority,
    SchedulerBridgeBootAuthority,
    SchedulerCallState,
    SchedulerCaseAuthority,
    SchedulerContractError,
    SchedulerDeadlineTokenAuthority,
    SchedulerPageQuery,
    SchedulerProfile,
    SchedulerRunAuthority,
    SchedulerRunBinding,
    SchedulerRunState,
    SchedulerStateTransitionValidator,
    SchedulerSuiteAuthority,
    build_scheduler_manifest,
    case_manifest_sha256,
    run_authority_from_suite,
)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def cases(prefix: str, count: int) -> tuple[SchedulerCaseAuthority, ...]:
    return tuple(
        SchedulerCaseAuthority(case_id=f"{prefix}-case-{index}", case_alias=f"{prefix}-{index}")
        for index in range(count)
    )


def suite_and_cases() -> tuple[
    SchedulerSuiteAuthority,
    tuple[SchedulerCaseAuthority, ...],
    tuple[SchedulerCaseAuthority, ...],
]:
    locomo_cases = cases("locomo", LOCOMO_PROFILE.case_count)
    lme_cases = cases("lme", LONGMEMEVAL_PROFILE.case_count)
    bridge = SchedulerBridgeBootAuthority(
        bridge_id="reviewed-bridge",
        implementation_sha256=sha("bridge-implementation"),
        runtime_authority_sha256=sha("bridge-runtime"),
        boot_nonce_sha256=sha("bridge-boot"),
        receipt_verifier_policy_sha256=sha("receipt-verifier"),
    )
    backends = (
        SchedulerBackendAuthority("infinity-context", sha("infinity-target")),
        SchedulerBackendAuthority("mem0", sha("mem0-target")),
    )

    def binding(
        profile: SchedulerProfile,
        run_id: str,
        run_cases: tuple[SchedulerCaseAuthority, ...],
    ) -> SchedulerRunBinding:
        answer_tokens = 128
        judge_tokens = 64
        case_count = len(run_cases)
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=1_000,
            dispatch_deadline_unix_ms=100_000,
            answer_max_output_tokens=answer_tokens,
            judge_max_output_tokens=judge_tokens,
            run_token_ceiling=case_count * 2 * (answer_tokens + judge_tokens),
        )
        return SchedulerRunBinding(
            run_id=run_id,
            profile=profile,
            binding_commitment_sha256=sha(f"{run_id}-binding"),
            dataset_sha256=sha(f"{run_id}-dataset"),
            case_manifest_sha256=case_manifest_sha256(run_cases),
            backends=backends,
            limits=limits,
        )

    suite = SchedulerSuiteAuthority(
        suite_id="publishable-full-suite",
        publication_bundle_sha256=sha("publication-bundle"),
        methodology_sha256=sha("methodology"),
        source_commit_sha256=sha("source-commit"),
        bridge_boot=bridge,
        ordered_runs=(
            binding(LOCOMO_PROFILE, "locomo-run", locomo_cases),
            binding(LONGMEMEVAL_PROFILE, "longmemeval-run", lme_cases),
        ),
    )
    return suite, locomo_cases, lme_cases


def built_runs() -> tuple[
    SchedulerSuiteAuthority,
    tuple[SchedulerRunAuthority, BuiltSchedulerManifest],
    tuple[SchedulerRunAuthority, BuiltSchedulerManifest],
]:
    suite, locomo_cases, lme_cases = suite_and_cases()
    locomo = run_authority_from_suite(suite, run_index=0)
    lme = run_authority_from_suite(suite, run_index=1)
    return (
        suite,
        (
            locomo,
            build_scheduler_manifest(locomo, suite=suite, ordered_cases=locomo_cases),
        ),
        (
            lme,
            build_scheduler_manifest(lme, suite=suite, ordered_cases=lme_cases),
        ),
    )


class InMemoryManifestPageStore:
    def __init__(self, manifests: tuple[BuiltSchedulerManifest, ...]) -> None:
        self._manifests = {item.authority.run_id: item for item in manifests}
        self.max_requested_limit = 0

    def read(self, query: SchedulerPageQuery):
        if type(query) is not SchedulerPageQuery:
            raise SchedulerContractError("scheduler_test_page_query_invalid")
        self.max_requested_limit = max(self.max_requested_limit, query.limit)
        manifest = self._manifests.get(query.run_id)
        if (
            manifest is None
            or manifest.authority.commitment_sha256 != query.run_manifest_authority_sha256
        ):
            raise SchedulerContractError("scheduler_test_page_binding_invalid")
        try:
            shard = manifest.shards[query.shard_index]
        except IndexError as error:
            raise SchedulerContractError("scheduler_test_page_missing") from error
        if len(shard.calls) > query.limit:
            raise SchedulerContractError("scheduler_test_page_limit_exceeded")
        return shard


class InMemorySchedulerStateStore:
    def __init__(
        self,
        suite: SchedulerSuiteAuthority,
        authority: SchedulerRunAuthority,
        manifest: BuiltSchedulerManifest,
    ) -> None:
        self.validator = SchedulerStateTransitionValidator(suite, authority, manifest.authority)
        self.run = self.validator.initial_run()
        self.calls = {
            call.logical_call_id: self.validator.initial_call(call, shard=shard)
            for shard in manifest.shards
            for call in shard.calls
        }

    def apply(
        self,
        logical_call_id: str,
        transition: Callable[
            [SchedulerRunState, SchedulerCallState],
            tuple[SchedulerRunState, SchedulerCallState],
        ],
    ) -> SchedulerCallState:
        call = self.calls[logical_call_id]
        self.run, updated = transition(self.run, call)
        self.calls[logical_call_id] = updated
        return updated

    def read_page(self, *, after_ordinal: int, limit: int) -> tuple[SchedulerCallState, ...]:
        if (
            type(after_ordinal) is not int
            or after_ordinal < -1
            or type(limit) is not int
            or not 1 <= limit <= 256
        ):
            raise SchedulerContractError("scheduler_test_state_query_invalid")
        ordered = sorted(self.calls.values(), key=lambda item: item.ordinal)
        return tuple(item for item in ordered if item.ordinal > after_ordinal)[:limit]
