from __future__ import annotations

import copy
import hashlib
import pickle
from dataclasses import replace
from datetime import timedelta

import pytest
from infinity_context_server import memory_comparison_managed_attestation as managed
from infinity_context_server import memory_comparison_managed_runtime_validity as validity
from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
    ManagedMem0RuntimeAuthorityDescriptor,
    ManagedMem0RuntimeAuthorityError,
    _register_pending_managed_mem0_runtime_authority,
    inspect_pending_managed_mem0_runtime_authority,
    reserve_pending_managed_mem0_runtime_authority,
)
from infinity_context_server.memory_comparison_managed_runtime_validity import (
    _bind_managed_live_runtime_freshness_policy,
    _bind_managed_live_runtime_policy_from_reserved_authority,
    _bound_validation,
    _managed_live_runtime_validation_terminal_allowance,
    _ManagedLiveRuntimeFreshnessPolicy,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    public_mem0_runtime_attestation_validation,
)
from test_memory_comparison_managed_attestation import (
    _NONCE,
    _RUN,
    _TARGET,
    _issue,
    _ports,
    _public,
    _runtime_validation,
    _validation_clock,
)


class _MonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _TerminalPolicyAuthority:
    def __init__(self, descriptor: ManagedMem0RuntimeAuthorityDescriptor) -> None:
        self.descriptor = descriptor

    def authority_descriptor(self) -> ManagedMem0RuntimeAuthorityDescriptor:
        return self.descriptor

    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> object:
        return (run_id, probe_nonce_sha256, target_identity_sha256)


def _bind_terminal_policy(
    validation: VerifiedMem0RuntimeAttestationValidation,
    *,
    run_id: str = _RUN,
    nonce: str = _NONCE,
    target: str = _TARGET,
    max_age_seconds: int = 900,
    monotonic_clock: _MonotonicClock | None = None,
) -> tuple[_MonotonicClock, _ManagedLiveRuntimeFreshnessPolicy]:
    clock = monotonic_clock or _MonotonicClock(1_000.0)
    descriptor = ManagedMem0RuntimeAuthorityDescriptor(
        adapter_id="test.managed-terminal-policy.v1",
        implementation_sha256="a" * 64,
        target_identity_sha256=target,
        probe_nonce_sha256=hashlib.sha256(nonce.encode()).hexdigest(),
        probe_token_credential_binding_id="sha256:" + "b" * 64,
        request_timeout_seconds=0.5,
        deadline_policy=MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
        deadline_budget_seconds=float(max_age_seconds),
        minimum_network_timeout_seconds=0.001,
        max_attempts=1,
    )
    authority = _TerminalPolicyAuthority(descriptor)
    _register_pending_managed_mem0_runtime_authority(
        authority,
        descriptor,
        monotonic_clock=clock,
        deadline_monotonic=clock.value + float(max_age_seconds),
    )
    reserve_pending_managed_mem0_runtime_authority(authority, descriptor)
    _bind_managed_live_runtime_policy_from_reserved_authority(
        validation,
        authority=authority,
        run_id=run_id,
        probe_nonce_sha256=descriptor.probe_nonce_sha256,
        target_identity_sha256=target,
    )
    state = _bound_validation(validation)
    assert state is not None
    return clock, state.policy


def _terminal_report(attestation: object, bindings: object, ports: tuple[object, ...]):
    return managed._inspect_verified_managed_composition_attestation_for_terminal_composite(
        attestation,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )


def test_terminal_inspection_uses_sealed_budget_then_public_report_stops_decaying() -> None:
    validation = _runtime_validation()
    _bind_terminal_policy(validation)
    observed_at = _validation_clock(validation)
    ports = _ports(observed_at)
    attestation, bindings, _, _, ports = _issue(validation=validation, ports=ports)
    ports[3].current = observed_at + timedelta(seconds=121)

    with pytest.raises(managed.ManagedCompositionAttestationError, match="stale"):
        _public(attestation, bindings, ports)
    terminal = _terminal_report(attestation, bindings, ports)
    consumed = managed._consume_verified_managed_composition_attestation_for_composite(
        attestation,
        bindings=bindings,
        reset_port=ports[0],
        attestation_port=ports[1],
        ingest_port=ports[2],
        clock=ports[3],
    )
    assert consumed == terminal
    ports[3].current = observed_at + timedelta(seconds=901)
    assert _public(attestation, bindings, ports) == terminal
    ports[0].adapter_id = "mutated-reset"
    with pytest.raises(managed.ManagedCompositionAttestationError, match="live capability changed"):
        _public(attestation, bindings, ports)


def test_terminal_inspection_without_policy_keeps_120_second_limit() -> None:
    attestation, bindings, validation, _, ports = _issue()
    ports[3].current = _validation_clock(validation) + timedelta(seconds=121)
    with pytest.raises(managed.ManagedCompositionAttestationError, match="stale"):
        _terminal_report(attestation, bindings, ports)


def test_terminal_inspection_rejects_after_sealed_wall_deadline() -> None:
    validation = _runtime_validation()
    _bind_terminal_policy(validation)
    observed_at = _validation_clock(validation)
    ports = _ports(observed_at)
    attestation, bindings, _, _, ports = _issue(validation=validation, ports=ports)
    ports[3].current = observed_at + timedelta(seconds=901)
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="terminal deadline is stale",
    ):
        _terminal_report(attestation, bindings, ports)


def test_terminal_inspection_rejects_monotonic_expiry_after_wall_clock_rollback() -> None:
    validation = _runtime_validation()
    observed_at = _validation_clock(validation)
    monotonic = _MonotonicClock(1_000.0)
    _bind_terminal_policy(validation, monotonic_clock=monotonic)
    allowance = _managed_live_runtime_validation_terminal_allowance(validation)
    assert allowance is not None and allowance.monotonic_current is True
    ports = _ports(observed_at)
    attestation, bindings, _, _, ports = _issue(validation=validation, ports=ports)
    ports[3].current = observed_at + timedelta(seconds=121)
    monotonic.value = 1_900.001
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="terminal deadline is stale",
    ):
        _terminal_report(attestation, bindings, ports)


def test_terminal_inspection_treats_exact_monotonic_deadline_as_expired() -> None:
    validation = _runtime_validation()
    observed_at = _validation_clock(validation)
    monotonic = _MonotonicClock(1_000.0)
    _bind_terminal_policy(validation, monotonic_clock=monotonic)
    attestation, bindings, _, _, ports = _issue(
        validation=validation,
        ports=_ports(observed_at),
    )
    ports[3].current = observed_at + timedelta(seconds=121)
    monotonic.value = 1_899.999
    assert _terminal_report(attestation, bindings, ports)["max_age_seconds"] == 120
    monotonic.value = 1_900.0
    with pytest.raises(
        managed.ManagedCompositionAttestationError,
        match="terminal deadline is stale",
    ):
        _terminal_report(attestation, bindings, ports)


def test_private_policy_cannot_upgrade_cross_run_public_validation() -> None:
    validation_a = _runtime_validation()
    _, policy = _bind_terminal_policy(validation_a)
    validation_b = _runtime_validation(run_id="managed-composition-run-b")
    assert public_mem0_runtime_attestation_validation(validation_b)["max_age_seconds"] == 120
    with pytest.raises(ValueError, match="policy"):
        _bind_managed_live_runtime_freshness_policy(validation_b, policy=policy)


def test_private_policy_rejects_cross_payload_replay_copy_replace_and_pickle() -> None:
    validation_a = _runtime_validation()
    _, policy = _bind_terminal_policy(validation_a)
    validation_b = _runtime_validation()
    with pytest.raises(ValueError, match="policy"):
        _bind_managed_live_runtime_freshness_policy(validation_b, policy=policy)
    for operation in (copy.copy, copy.deepcopy, replace, pickle.dumps):
        with pytest.raises(TypeError):
            operation(policy)


def test_policy_issuance_failure_retires_lease_and_authority_without_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation = _runtime_validation()
    clock = _MonotonicClock(1_000.0)
    descriptor = ManagedMem0RuntimeAuthorityDescriptor(
        adapter_id="test.failed-policy-issuance.v1",
        implementation_sha256="a" * 64,
        target_identity_sha256=_TARGET,
        probe_nonce_sha256=hashlib.sha256(_NONCE.encode()).hexdigest(),
        probe_token_credential_binding_id="sha256:" + "b" * 64,
        request_timeout_seconds=0.5,
        deadline_policy=MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
        deadline_budget_seconds=900.0,
        minimum_network_timeout_seconds=0.001,
        max_attempts=1,
    )
    authority = _TerminalPolicyAuthority(descriptor)
    _register_pending_managed_mem0_runtime_authority(
        authority,
        descriptor,
        monotonic_clock=clock,
        deadline_monotonic=1_900.0,
    )
    reserve_pending_managed_mem0_runtime_authority(authority, descriptor)

    def fail_policy_issuance(**_: object) -> object:
        raise ValueError("injected policy failure")

    monkeypatch.setattr(
        validity,
        "_issue_managed_live_runtime_freshness_policy",
        fail_policy_issuance,
    )
    with pytest.raises(ValueError, match="injected policy failure"):
        _bind_managed_live_runtime_policy_from_reserved_authority(
            validation,
            authority=authority,
            run_id=_RUN,
            probe_nonce_sha256=descriptor.probe_nonce_sha256,
            target_identity_sha256=_TARGET,
        )
    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="not registered"):
        inspect_pending_managed_mem0_runtime_authority(authority)
    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="not registered"):
        _bind_managed_live_runtime_policy_from_reserved_authority(
            validation,
            authority=authority,
            run_id=_RUN,
            probe_nonce_sha256=descriptor.probe_nonce_sha256,
            target_identity_sha256=_TARGET,
        )


def test_private_policy_submicrosecond_deadline_mutation_breaks_terminal_binding() -> None:
    validation = _runtime_validation()
    _, policy = _bind_terminal_policy(validation)
    object.__setattr__(policy, "deadline_at", policy.deadline_at + timedelta(microseconds=1))
    assert _managed_live_runtime_validation_terminal_allowance(validation) is None
