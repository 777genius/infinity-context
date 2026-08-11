from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_publishable_contracts import (
    freeze_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_go_readiness import (
    PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION,
    PublishableExecutionMethodologyAuthority,
    PublishableExecutionOrchestrationAuthority,
    PublishableExecutionPolicyError,
    PublishableExecutionProfileAuthority,
    PublishableExecutionReview,
    active_publishable_execution_authorities,
    publishable_execution_methodology_authority,
    publishable_execution_profile_authority,
    require_active_publishable_execution_authority,
    require_publishable_execution_authority,
    require_publishable_execution_authority_binding,
    reviewed_publishable_execution_binding,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    public_publishable_methodology,
    publishable_priority_methodology_v4,
    resolve_publishable_methodology,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
    resolve_publishable_comparison_profile,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_production_composition as production_composition,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_production import (
    PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256,
)


def test_stale_profile_fails_closed_against_reviewed_v4_binding() -> None:
    stale_profile = resolve_publishable_comparison_profile()
    stale_methodology = resolve_publishable_methodology()
    assert stale_profile is not None and stale_methodology is not None

    with pytest.raises(
        PublishableExecutionPolicyError,
        match="publishable_execution_profile_stale",
    ):
        require_publishable_execution_authority(
            profile=publishable_execution_profile_authority(stale_profile),
            methodology=publishable_execution_methodology_authority(stale_methodology),
            orchestration=(
                production_composition.publishable_production_execution_orchestration_authority()
            ),
            review=reviewed_publishable_execution_binding(),
        )


def test_active_v4_false_flags_and_unresolved_capability_fail_closed() -> None:
    profile, methodology = active_publishable_execution_authorities()
    orchestration = (
        production_composition.publishable_production_execution_orchestration_authority()
    )
    review = reviewed_publishable_execution_binding()

    assert profile.implementation_status == "contract_only"
    assert profile.execution_enabled is False
    assert profile.publishable is False
    assert profile.activation_blockers
    assert profile.benchmark_execution_enabled == (
        ("locomo", False),
        ("longmemeval", False),
    )
    assert profile.methodology_observed is False
    assert methodology.current_capability_satisfies_requirement is False
    assert orchestration.scheduler_paid_go_ready is False
    assert orchestration.runner_paid_go_ready is False
    assert orchestration.durable_store_paid_go_ready is False
    assert orchestration.publishable is False
    assert orchestration.schema_version == review.orchestration_schema_version
    assert orchestration.commitment_sha256 == review.orchestration_commitment_sha256
    assert (
        orchestration.paired_outcome_sealing_policy_sha256
        == PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256
    )

    with pytest.raises(
        PublishableExecutionPolicyError,
        match="publishable_execution_not_ready",
    ):
        require_publishable_execution_authority(
            profile=profile,
            methodology=methodology,
            orchestration=orchestration,
            review=review,
        )


def test_paired_outcome_production_authority_drift_fails_closed(monkeypatch) -> None:
    reviewed_orchestration = (
        production_composition.publishable_production_execution_orchestration_authority()
    )
    drifted_policy_sha256 = "4" * 64
    monkeypatch.setattr(
        production_composition,
        "PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256",
        drifted_policy_sha256,
    )

    drifted_orchestration = (
        production_composition.publishable_production_execution_orchestration_authority()
    )

    assert drifted_orchestration.paired_outcome_sealing_policy_sha256 == drifted_policy_sha256
    assert drifted_orchestration.commitment_sha256 != reviewed_orchestration.commitment_sha256
    with pytest.raises(PublishableExecutionPolicyError) as raised:
        require_active_publishable_execution_authority(drifted_orchestration)
    assert raised.value.code == "publishable_execution_commitment_drift"


def test_authenticated_false_execution_flag_fails_closed() -> None:
    profile, methodology, orchestration, review = _ready_binding(profile_execution_enabled=False)

    with pytest.raises(
        PublishableExecutionPolicyError,
        match="publishable_execution_not_ready",
    ):
        require_publishable_execution_authority(
            profile=profile,
            methodology=methodology,
            orchestration=orchestration,
            review=review,
        )


@pytest.mark.parametrize(
    "drift",
    ("profile", "methodology", "orchestration"),
)
def test_reviewed_commitment_drift_fails_closed(drift: str) -> None:
    profile, methodology, orchestration, review = _ready_binding()
    if drift == "profile":
        review = replace(review, profile_commitment_sha256="1" * 64)
    elif drift == "methodology":
        review = replace(review, methodology_commitment_sha256="2" * 64)
    else:
        review = replace(review, orchestration_commitment_sha256="3" * 64)

    with pytest.raises(
        PublishableExecutionPolicyError,
        match="publishable_execution_commitment_drift",
    ):
        require_publishable_execution_authority(
            profile=profile,
            methodology=methodology,
            orchestration=orchestration,
            review=review,
        )


def test_exact_reviewed_executable_binding_issues_non_publication_authority() -> None:
    profile, methodology, orchestration, review = _ready_binding()

    authority = require_publishable_execution_authority(
        profile=profile,
        methodology=methodology,
        orchestration=orchestration,
        review=review,
    )

    assert profile.execution_enabled is True
    assert profile.publishable is False
    assert orchestration.publishable is False
    assert repr(authority) == "PublishableExecutionAuthority(<static-reviewed>)"
    require_publishable_execution_authority_binding(
        authority,
        orchestration=orchestration,
        review=review,
        suite_methodology_sha256=methodology.commitment_sha256,
    )


def _ready_binding(
    *,
    profile_execution_enabled: bool = True,
) -> tuple[
    PublishableExecutionProfileAuthority,
    PublishableExecutionMethodologyAuthority,
    PublishableExecutionOrchestrationAuthority,
    PublishableExecutionReview,
]:
    methodology_payload = public_publishable_methodology(publishable_priority_methodology_v4())
    equivalence = methodology_payload["required_full_run_extraction_equivalence"]
    equivalence["current_runtime_capability"] = equivalence["required_capacity"]
    equivalence["current_capability_satisfies_requirement"] = True
    methodology_frozen = freeze_publishable_payload(
        profile_id=methodology_payload["methodology_id"],
        payload=methodology_payload,
    )
    methodology = publishable_execution_methodology_authority(methodology_frozen)

    profile_payload = public_publishable_comparison_profile(
        publishable_priority_comparison_profile_v4()
    )
    profile_payload["implementation_status"] = "executable"
    profile_payload["execution_enabled"] = profile_execution_enabled
    profile_payload["activation_blockers"] = []
    profile_payload["methodology"]["commitment_sha256"] = methodology.commitment_sha256
    profile_payload["methodology"]["observed"] = True
    for benchmark in ("locomo", "longmemeval"):
        profile_payload["benchmarks"][benchmark]["execution_enabled"] = True
    profile_frozen = freeze_publishable_payload(
        profile_id=profile_payload["profile_id"],
        payload=profile_payload,
    )
    profile = publishable_execution_profile_authority(profile_frozen)

    orchestration = PublishableExecutionOrchestrationAuthority(
        schema_version=PUBLISHABLE_PRODUCTION_ORCHESTRATION_SCHEMA_VERSION,
        profile_id=profile.profile_id,
        profile_commitment_sha256=profile.commitment_sha256,
        methodology_id=methodology.methodology_id,
        methodology_commitment_sha256=methodology.commitment_sha256,
        scheduler_paid_go_ready=True,
        runner_paid_go_ready=True,
        durable_store_paid_go_ready=True,
        production_bridge_adapter_ready=True,
        paired_outcome_sealing_policy_sha256=(PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256),
        publishable=False,
        readiness_blockers=(),
    )
    review = PublishableExecutionReview(
        profile_schema_version=profile.schema_version,
        profile_id=profile.profile_id,
        profile_commitment_sha256=profile.commitment_sha256,
        methodology_schema_version=methodology.schema_version,
        methodology_id=methodology.methodology_id,
        methodology_commitment_sha256=methodology.commitment_sha256,
        orchestration_schema_version=orchestration.schema_version,
        orchestration_commitment_sha256=orchestration.commitment_sha256,
    )
    return profile, methodology, orchestration, review
