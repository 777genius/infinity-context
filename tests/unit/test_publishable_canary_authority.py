from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
    LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_publishable_canary_methodology import (
    PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256,
    PUBLISHABLE_CANARY_METHODOLOGY_ID,
    public_publishable_canary_methodology,
    publishable_canary_methodology,
)
from infinity_context_server.memory_comparison_publishable_canary_profile import (
    PUBLISHABLE_CANARY_CASE_ALIAS,
    PUBLISHABLE_CANARY_CASE_ID,
    PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT,
    PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256,
    PUBLISHABLE_CANARY_PROFILE_ID,
    public_publishable_canary_profile,
    publishable_canary_case_alias,
    publishable_canary_profile,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    freeze_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError
from infinity_context_server.publishable_durable_scheduler.contracts import (
    LOCOMO_PROFILE,
    LONGMEMEVAL_PROFILE,
    SchedulerBackendAuthority,
    SchedulerBridgeBootAuthority,
    SchedulerDeadlineTokenAuthority,
    SchedulerRunBinding,
    SchedulerSuiteAuthority,
    run_authority_from_suite,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerCaseAuthority,
    build_scheduler_manifest,
    case_manifest_sha256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_canary_authority import (
    PUBLISHABLE_CANARY_STATIC_AUTHORITY_SHA256,
    PublishableCanaryAuthorityError,
    bind_publishable_canary_authority,
    publishable_canary_static_authority_payload,
    validate_publishable_canary_static_authority,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _cases(
    prefix: str,
    count: int,
    *,
    first: SchedulerCaseAuthority | None = None,
) -> tuple[SchedulerCaseAuthority, ...]:
    start = 1 if first is not None else 0
    tail = tuple(
        SchedulerCaseAuthority(
            case_id=f"{prefix}-case-{index}",
            case_alias=f"{prefix}-alias-{index}",
        )
        for index in range(start, count)
    )
    return (first, *tail) if first is not None else tail


def _suite_and_manifests(
    *,
    first_case: SchedulerCaseAuthority | None = None,
    methodology_sha256: str = PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    answer_tokens: int = 4_096,
) -> tuple[SchedulerSuiteAuthority, BuiltSchedulerManifest, BuiltSchedulerManifest]:
    selected = first_case or SchedulerCaseAuthority(
        case_id=PUBLISHABLE_CANARY_CASE_ID,
        case_alias=PUBLISHABLE_CANARY_CASE_ALIAS,
    )
    locomo_cases = _cases("locomo", LOCOMO_PROFILE.case_count, first=selected)
    longmemeval_cases = _cases("longmemeval", LONGMEMEVAL_PROFILE.case_count)
    backends = (
        SchedulerBackendAuthority("infinity-context", _sha("infinity-target")),
        SchedulerBackendAuthority("mem0", _sha("mem0-target")),
    )
    bridge = SchedulerBridgeBootAuthority(
        bridge_id="canary-test-bridge",
        implementation_sha256=_sha("bridge-implementation"),
        runtime_authority_sha256=_sha("runtime-authority"),
        boot_nonce_sha256=_sha("boot-nonce"),
        receipt_verifier_policy_sha256=_sha("receipt-verifier"),
    )

    def binding(profile, run_id, cases, dataset_sha256):
        limits = SchedulerDeadlineTokenAuthority(
            dispatch_not_before_unix_ms=1_000,
            dispatch_deadline_unix_ms=100_000,
            answer_max_output_tokens=answer_tokens,
            judge_max_output_tokens=4_096,
            run_token_ceiling=(profile.case_count * 2 * (answer_tokens + 4_096)),
        )
        return SchedulerRunBinding(
            run_id=run_id,
            profile=profile,
            binding_commitment_sha256=_sha(f"{run_id}-binding"),
            dataset_sha256=dataset_sha256,
            case_manifest_sha256=case_manifest_sha256(cases),
            backends=backends,
            limits=limits,
        )

    suite = SchedulerSuiteAuthority(
        suite_id="publishable-full-suite",
        publication_bundle_sha256=_sha("publication-bundle"),
        methodology_sha256=methodology_sha256,
        source_commit_sha256=_sha("source-commit"),
        bridge_boot=bridge,
        ordered_runs=(
            binding(
                LOCOMO_PROFILE,
                "locomo-run",
                locomo_cases,
                LOCOMO_OFFICIAL_DATASET_SHA256,
            ),
            binding(
                LONGMEMEVAL_PROFILE,
                "longmemeval-run",
                longmemeval_cases,
                LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
            ),
        ),
    )
    locomo_run = run_authority_from_suite(suite, run_index=0)
    longmemeval_run = run_authority_from_suite(suite, run_index=1)
    return (
        suite,
        build_scheduler_manifest(locomo_run, suite=suite, ordered_cases=locomo_cases),
        build_scheduler_manifest(
            longmemeval_run,
            suite=suite,
            ordered_cases=longmemeval_cases,
        ),
    )


@pytest.fixture(scope="module")
def canary_suite() -> tuple[
    SchedulerSuiteAuthority,
    BuiltSchedulerManifest,
    BuiltSchedulerManifest,
]:
    return _suite_and_manifests()


def test_canary_methodology_is_exactly_the_v4_priority_lane() -> None:
    methodology = publishable_canary_methodology()
    public = public_publishable_canary_methodology(methodology)

    assert methodology.profile_id == PUBLISHABLE_CANARY_METHODOLOGY_ID
    assert methodology.commitment_sha256 == PUBLISHABLE_CANARY_METHODOLOGY_COMMITMENT_SHA256
    assert methodology.commitment_sha256 == (
        "931fc50aaacbd100b5714cf318aaabf75e356cec4c326ea04d2e1b21cfe2dc17"
    )
    assert public["publishable"] is False
    assert public["full_profile_admission"] == "review_required"
    assert public["same_lane"] == {
        "required_provider_kind": "subscription-runtime",
        "required_provider_trust": "codex_subscription_runtime",
        "required_model": "gpt-5.6-sol",
        "required_reasoning_effort": "high",
        "required_service_tier": "priority",
        "requested_max_output_tokens": 4_096,
        "required_runtime_authority": "production_fleet_readiness_and_runtime_provenance",
        "required_input_authority": "production_official_case_and_retrieval_authorities",
        "required_extraction_authority": "production_shared_full_run_extraction_terminal",
        "required_answer_judge_path": "production_paired_infinity_vs_mem0",
    }


def test_canary_profile_commits_exact_case_order_and_nonpublishable_policy() -> None:
    profile = publishable_canary_profile()
    public = public_publishable_canary_profile(profile)

    assert profile.profile_id == PUBLISHABLE_CANARY_PROFILE_ID
    assert profile.commitment_sha256 == PUBLISHABLE_CANARY_PROFILE_COMMITMENT_SHA256
    assert profile.commitment_sha256 == (
        "ef6badbd1659a8b3624a5f4e189d301af86f52c83ab562b21ba2638be1ec4a39"
    )
    assert publishable_canary_case_alias() == PUBLISHABLE_CANARY_CASE_ALIAS
    assert public["scope"] == {
        "benchmark": "locomo",
        "dataset_sha256": LOCOMO_OFFICIAL_DATASET_SHA256,
        "run_index": 0,
        "case_index": 0,
        "case_id": "conv-26:qa:1",
        "case_alias": PUBLISHABLE_CANARY_CASE_ALIAS,
        "case_count": 1,
    }
    assert public["provider_call_authority"] == {
        "expected_provider_call_count": 4,
        "caller_override_allowed": False,
        "ordered_calls": [
            {"ordinal": 0, "backend_role": "infinity-context", "stage": "answer"},
            {"ordinal": 1, "backend_role": "infinity-context", "stage": "judge"},
            {"ordinal": 2, "backend_role": "mem0", "stage": "answer"},
            {"ordinal": 3, "backend_role": "mem0", "stage": "judge"},
        ],
    }
    assert public["publishable"] is False
    assert public["activation_evidence_only"] is True
    assert public["full_receipt_eligible"] is False
    assert public["replay_or_substitution_as_full_receipt"] == "forbidden"


def test_canary_does_not_activate_or_mutate_target_v4() -> None:
    target = public_publishable_comparison_profile(publishable_priority_comparison_profile_v4())

    assert target["implementation_status"] == "contract_only"
    assert target["execution_enabled"] is False
    assert target["publishable"] is False


def test_canary_frozen_contracts_reject_relabelled_tamper() -> None:
    public = public_publishable_canary_profile(publishable_canary_profile())
    public["publishable"] = True
    tampered = freeze_publishable_payload(
        profile_id=PUBLISHABLE_CANARY_PROFILE_ID,
        payload=public,
    )

    with pytest.raises(BenchmarkValidationError, match="differs from frozen primitives"):
        public_publishable_canary_profile(tampered)


def test_static_authority_has_no_caller_scope_or_count(canary_suite) -> None:
    validate_publishable_canary_static_authority()
    payload = publishable_canary_static_authority_payload()
    parameters = inspect.signature(bind_publishable_canary_authority).parameters

    assert PUBLISHABLE_CANARY_STATIC_AUTHORITY_SHA256 == (
        "19412a1bb18f9c80c6a8d3470b50c7782be895031a243ba7347d3a19862e13b0"
    )
    assert payload["expected_provider_call_count"] == 4
    assert payload["caller_scope_or_count_override_allowed"] is False
    assert tuple(parameters) == ("suite", "manifest")


def test_binder_selects_existing_full_manifest_prefix_in_production_order(
    canary_suite,
) -> None:
    suite, locomo_manifest, _ = canary_suite
    authority = bind_publishable_canary_authority(
        suite=suite,
        manifest=locomo_manifest,
    )

    assert authority.expected_provider_call_count == PUBLISHABLE_CANARY_EXPECTED_PROVIDER_CALL_COUNT
    assert authority.ordered_calls == locomo_manifest.shards[0].calls[:4]
    assert tuple(
        (call.ordinal, call.backend_role, call.stage.value) for call in authority.ordered_calls
    ) == (
        (0, "infinity-context", "answer"),
        (1, "infinity-context", "judge"),
        (2, "mem0", "answer"),
        (3, "mem0", "judge"),
    )
    assert len(set(authority.ordered_logical_call_ids)) == 4
    assert authority.material()["publishable"] is False
    assert authority.material()["full_receipt_eligible"] is False


def test_binder_rejects_wrong_case_alias() -> None:
    suite, manifest, _ = _suite_and_manifests(
        first_case=SchedulerCaseAuthority(
            case_id=PUBLISHABLE_CANARY_CASE_ID,
            case_alias="locomo-case-wrong",
        )
    )

    with pytest.raises(PublishableCanaryAuthorityError, match="selected_case_invalid"):
        bind_publishable_canary_authority(suite=suite, manifest=manifest)


def test_binder_rejects_unresolved_methodology_before_selection() -> None:
    suite, manifest, _ = _suite_and_manifests(methodology_sha256=_sha("wrong-methodology"))

    with pytest.raises(PublishableCanaryAuthorityError, match="suite_invalid"):
        bind_publishable_canary_authority(suite=suite, manifest=manifest)


def test_binder_rejects_changed_token_lane_before_selection() -> None:
    suite, manifest, _ = _suite_and_manifests(answer_tokens=4_095)

    with pytest.raises(PublishableCanaryAuthorityError, match="suite_invalid"):
        bind_publishable_canary_authority(suite=suite, manifest=manifest)


def test_binder_rejects_crosswired_run_or_suite_manifest(canary_suite) -> None:
    suite, locomo_manifest, longmemeval_manifest = canary_suite
    other_suite = replace(suite, source_commit_sha256=_sha("different-source"))

    with pytest.raises(PublishableCanaryAuthorityError, match="manifest_invalid"):
        bind_publishable_canary_authority(
            suite=suite,
            manifest=longmemeval_manifest,
        )
    with pytest.raises(PublishableCanaryAuthorityError, match="manifest_invalid"):
        bind_publishable_canary_authority(
            suite=other_suite,
            manifest=locomo_manifest,
        )


def test_bound_authority_rejects_injected_provider_call_count(canary_suite) -> None:
    suite, manifest, _ = canary_suite
    authority = bind_publishable_canary_authority(suite=suite, manifest=manifest)

    with pytest.raises(PublishableCanaryAuthorityError, match="authority_invalid"):
        replace(authority, ordered_calls=authority.ordered_calls[:3])
