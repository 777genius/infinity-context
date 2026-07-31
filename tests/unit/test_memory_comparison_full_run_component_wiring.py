from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import memory_comparison_full_policy_component_fixtures as policy_fixtures
import pytest
from infinity_context_server import memory_comparison_full_run_evidence as evidence_module
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionValidationError,
    consume_full_execution_validation,
)
from infinity_context_server.memory_comparison_full_policy_component_validation import (
    create_full_policy_component_validation_session,
    seal_full_policy_component_validation,
)
from infinity_context_server.memory_comparison_full_run_components import (
    issue_execution_component_evidence_set,
    issue_gold_blind_component_evidence,
    issue_policy_component_evidence_set,
    issue_runtime_component_evidence_from_managed_attestation,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FULL_COMPARISON_COMPONENT_KINDS,
    FullComparisonEvidenceError,
    create_full_comparison_evidence_issuer,
    issue_full_comparison_run_evidence,
)
from infinity_context_server.memory_comparison_full_verdict import (
    public_full_comparison_verdict,
    verify_full_comparison_run,
)
from infinity_context_server.memory_comparison_managed_attestation import (
    ManagedCompositionAttestationError,
    _consume_verified_managed_composition_attestation_for_composite,
    public_managed_composition_attestation,
)
from test_memory_comparison_full_binding_replay import _gold_validation
from test_memory_comparison_full_execution_validation import (
    _identity as _execution_identity,
)
from test_memory_comparison_full_execution_validation import _inputs as _execution_inputs
from test_memory_comparison_full_execution_validation import _proof as _execution_proof
from test_memory_comparison_managed_attestation import _bindings as _managed_bindings
from test_memory_comparison_managed_attestation import _issue as _managed_issue
from test_memory_comparison_managed_attestation import (
    _runtime_validation as _managed_runtime_validation,
)


def _aggregate_inputs():
    inputs = _execution_inputs()
    old_bindings = inputs["bindings"]
    bindings = _managed_bindings(
        run_id=old_bindings.run_id,
        selection=old_bindings.selection_fingerprint_sha256,
    )
    inputs["bindings"] = bindings
    inputs["provider_calls"] = tuple(
        replace(call, comparison_commitment_sha256=bindings.binding_commitment_sha256)
        for call in inputs["provider_calls"]
    )
    runtime = _managed_runtime_validation(
        run_id=bindings.run_id,
        target=bindings.backend_targets[1].target_identity_sha256,
    )
    managed, _, _, _, ports = _managed_issue(
        bindings=bindings,
        validation=runtime,
        route=inputs["required_route"],
    )
    return inputs, managed, ports


def _issue_runtime(issuer, managed, bindings, ports):
    component = issue_runtime_component_evidence_from_managed_attestation(
        issuer,
        managed,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    report = public_managed_composition_attestation(
        managed,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    return component, report


def _policy_validation(monkeypatch: pytest.MonkeyPatch, bindings, managed_commitment: str):
    monkeypatch.setattr(policy_fixtures, "RUN", bindings.run_id)
    monkeypatch.setattr(policy_fixtures, "PROFILE", bindings.profile_id)
    monkeypatch.setattr(policy_fixtures, "ATTESTATION", managed_commitment)
    fixture = policy_fixtures.build_policy_aggregate_fixture(
        item_attestation=managed_commitment,
        delete_attestation=managed_commitment,
        item_count=1,
    )
    session = create_full_policy_component_validation_session(
        manifest=fixture.manifest,
        evidence_pairs=fixture.pairs,
        terminal_delete=fixture.terminal_delete,
        consumer_id="full-run-wiring",
    )
    return seal_full_policy_component_validation(session)


def test_all_nine_slots_wire_from_nominal_aggregates_and_revalidate_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    runtime, managed_report = _issue_runtime(issuer, managed, bindings, ports)
    _, execution = _execution_proof(inputs)
    execution_components = issue_execution_component_evidence_set(
        issuer,
        execution,
        case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
    )
    policy = _policy_validation(
        monkeypatch,
        bindings,
        str(managed_report["composition_attestation_sha256"]),
    )
    policy_components = issue_policy_component_evidence_set(issuer, policy)
    gold = issue_gold_blind_component_evidence(issuer, _gold_validation(bindings))
    components = (
        execution_components[0],
        runtime,
        execution_components[1],
        execution_components[2],
        gold,
        execution_components[3],
        *policy_components,
    )

    assert len(FULL_COMPARISON_COMPONENT_KINDS) == 9
    evidence = issue_full_comparison_run_evidence(bindings, components, issuer)
    verdict = verify_full_comparison_run(evidence)
    first = public_full_comparison_verdict(verdict)
    second = public_full_comparison_verdict(verdict)

    assert first == second
    assert first["publishable"] is True
    assert [item["component_kind"] for item in first["components"]] == list(
        FULL_COMPARISON_COMPONENT_KINDS
    )
    assert {item["status"] for item in first["components"]} == {"verified"}


def test_runtime_consume_is_one_shot_but_public_revalidation_remains_live() -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    _, first = _issue_runtime(issuer, managed, bindings, ports)

    second = public_managed_composition_attestation(
        managed,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    assert second == first
    with pytest.raises(ManagedCompositionAttestationError, match="already consumed"):
        _consume_verified_managed_composition_attestation_for_composite(
            managed,
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
        )

    ports[0].adapter_id = "changed-reset"
    with pytest.raises(ManagedCompositionAttestationError, match="live capability changed"):
        public_managed_composition_attestation(
            managed,
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
        )


def test_runtime_public_revalidation_rejects_stale_consumed_attestation() -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    _, report = _issue_runtime(issuer, managed, bindings, ports)
    ports[3].current += timedelta(seconds=int(report["max_age_seconds"]) + 1)

    with pytest.raises(ManagedCompositionAttestationError, match="stale"):
        public_managed_composition_attestation(
            managed,
            bindings=bindings,
            reset_port=ports[0],
            attestation_port=ports[1],
            ingest_port=ports[2],
            clock=ports[3],
        )


def test_execution_set_is_one_shot_under_concurrency_and_replay() -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    _issue_runtime(issuer, managed, bindings, ports)
    _, execution = _execution_proof(inputs)

    def issue():
        try:
            return issue_execution_component_evidence_set(
                issuer,
                execution,
                case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
            )
        except FullComparisonEvidenceError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: issue(), range(2)))

    assert sum(type(result) is tuple for result in results) == 1
    assert sum("already reserved" in result for result in results if type(result) is str) == 1
    with pytest.raises(FullComparisonEvidenceError, match="already reserved"):
        issue_execution_component_evidence_set(
            issuer,
            execution,
            case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
        )


def test_mapping_rejection_rolls_back_before_consume_and_real_proof_can_retry() -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    _issue_runtime(issuer, managed, bindings, ports)
    _, execution = _execution_proof(inputs)

    with pytest.raises(FullComparisonEvidenceError, match="type must be exact"):
        issue_execution_component_evidence_set(
            issuer,
            {"component_only": True},  # type: ignore[arg-type]
            case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
        )
    assert (
        len(
            issue_execution_component_evidence_set(
                issuer,
                execution,
                case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
            )
        )
        == 4
    )


def test_case_manifest_mismatch_does_not_consume_and_correct_retry_succeeds() -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    _issue_runtime(issuer, managed, bindings, ports)
    _, execution = _execution_proof(inputs)

    with pytest.raises(FullComparisonEvidenceError, match="case manifest differs"):
        issue_execution_component_evidence_set(
            issuer,
            execution,
            case_manifest_sha256="f" * 64,
        )
    assert (
        len(
            issue_execution_component_evidence_set(
                issuer,
                execution,
                case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
            )
        )
        == 4
    )


def test_post_consume_mint_failure_cleans_partial_slots_and_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, managed, ports = _aggregate_inputs()
    bindings = inputs["bindings"]
    issuer = create_full_comparison_evidence_issuer(bindings)
    _issue_runtime(issuer, managed, bindings, ports)
    _, execution = _execution_proof(inputs)
    before = set(evidence_module._COMPONENTS)
    original = evidence_module._issue_component
    calls = 0

    def fail_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        component = original(*args, **kwargs)
        if calls == 3:
            raise KeyboardInterrupt
        return component

    monkeypatch.setattr(evidence_module, "_issue_component", fail_third)
    with pytest.raises(KeyboardInterrupt):
        issue_execution_component_evidence_set(
            issuer,
            execution,
            case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
        )

    assert set(evidence_module._COMPONENTS) == before
    with pytest.raises(FullComparisonEvidenceError, match="already reserved"):
        issue_execution_component_evidence_set(
            issuer,
            execution,
            case_manifest_sha256=_execution_identity(inputs)["case_manifest_sha256"],
        )
    with pytest.raises(FullExecutionValidationError, match="already consumed"):
        consume_full_execution_validation(execution, **_execution_identity(inputs))
