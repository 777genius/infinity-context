from __future__ import annotations

import copy
import hashlib
import pickle
from dataclasses import replace

import pytest
from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
    ManagedMem0RuntimeAuthorityDescriptor,
    ManagedMem0RuntimeAuthorityError,
    _consume_reserved_managed_mem0_runtime_deadline_lease,
    _issue_reserved_managed_mem0_runtime_deadline_lease,
    _register_pending_managed_mem0_runtime_authority,
    inspect_pending_managed_mem0_runtime_authority,
    reserve_pending_managed_mem0_runtime_authority,
)


def _descriptor() -> ManagedMem0RuntimeAuthorityDescriptor:
    return ManagedMem0RuntimeAuthorityDescriptor(
        adapter_id="test.mem0.runtime.v1",
        implementation_sha256="a" * 64,
        target_identity_sha256="b" * 64,
        probe_nonce_sha256="c" * 64,
        probe_token_credential_binding_id="sha256:" + "d" * 64,
        request_timeout_seconds=2.0,
        deadline_policy=MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
        deadline_budget_seconds=10.0,
        minimum_network_timeout_seconds=0.001,
        max_attempts=1,
        expected_runtime_mode="managed_platform",
    )


class _RegisteredTestDouble:
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


class _MonotonicClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_non_concrete_authority_requires_trusted_registration() -> None:
    descriptor = _descriptor()
    port = _RegisteredTestDouble(descriptor)

    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="not registered"):
        inspect_pending_managed_mem0_runtime_authority(port)

    _register_pending_managed_mem0_runtime_authority(port, descriptor)

    assert inspect_pending_managed_mem0_runtime_authority(port) is descriptor


def test_registered_authority_reservation_is_exact_and_single_use() -> None:
    descriptor = _descriptor()
    port = _RegisteredTestDouble(descriptor)
    _register_pending_managed_mem0_runtime_authority(port, descriptor)

    reserve_pending_managed_mem0_runtime_authority(port, descriptor)

    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="already reserved"):
        reserve_pending_managed_mem0_runtime_authority(port, descriptor)
    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="changed before"):
        reserve_pending_managed_mem0_runtime_authority(port, replace(descriptor))


def test_reserved_authority_issues_one_noncopyable_exact_deadline_lease() -> None:
    descriptor = _descriptor()
    port = _RegisteredTestDouble(descriptor)
    clock = _MonotonicClock(100.0)
    _register_pending_managed_mem0_runtime_authority(
        port,
        descriptor,
        monotonic_clock=clock,
        deadline_monotonic=1_000.0,
    )
    reserve_pending_managed_mem0_runtime_authority(port, descriptor)

    lease = _issue_reserved_managed_mem0_runtime_deadline_lease(
        port,
        run_id="test-run-1",
        probe_nonce_sha256=descriptor.probe_nonce_sha256,
        target_identity_sha256=descriptor.target_identity_sha256,
        validation_payload_fingerprint_sha256="d" * 64,
    )

    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(lease)
    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="already issued"):
        _issue_reserved_managed_mem0_runtime_deadline_lease(
            port,
            run_id="test-run-1",
            probe_nonce_sha256=descriptor.probe_nonce_sha256,
            target_identity_sha256=descriptor.target_identity_sha256,
            validation_payload_fingerprint_sha256="d" * 64,
        )

    material = _consume_reserved_managed_mem0_runtime_deadline_lease(lease)
    assert material.max_age_seconds == 900
    assert material.run_id_sha256 == hashlib.sha256(b"test-run-1").hexdigest()
    assert material.validation_payload_fingerprint_sha256 == "d" * 64
    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="already consumed"):
        _consume_reserved_managed_mem0_runtime_deadline_lease(lease)


def test_deadline_lease_requires_registered_clock_and_exact_probe_binding() -> None:
    descriptor = _descriptor()
    port = _RegisteredTestDouble(descriptor)
    _register_pending_managed_mem0_runtime_authority(port, descriptor)
    reserve_pending_managed_mem0_runtime_authority(port, descriptor)

    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="binding"):
        _issue_reserved_managed_mem0_runtime_deadline_lease(
            port,
            run_id="test-run-1",
            probe_nonce_sha256=descriptor.probe_nonce_sha256,
            target_identity_sha256=descriptor.target_identity_sha256,
            validation_payload_fingerprint_sha256="d" * 64,
        )


def test_registered_descriptor_tamper_is_rejected() -> None:
    descriptor = _descriptor()
    port = _RegisteredTestDouble(descriptor)
    _register_pending_managed_mem0_runtime_authority(port, descriptor)
    object.__setattr__(descriptor, "deadline_budget_seconds", float("inf"))

    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="descriptor changed"):
        inspect_pending_managed_mem0_runtime_authority(port)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("adapter_id", "bad adapter"),
        ("implementation_sha256", "0" * 63),
        ("target_identity_sha256", "x" * 64),
        ("probe_nonce_sha256", "1" * 63),
        ("probe_token_credential_binding_id", "plain-token"),
        ("deadline_policy", "wall-clock"),
        ("deadline_budget_seconds", float("nan")),
        ("minimum_network_timeout_seconds", 3.0),
        ("max_attempts", 2),
        ("expected_runtime_mode", "ambient"),
    ),
)
def test_descriptor_validates_its_full_structural_contract(
    field: str,
    value: object,
) -> None:
    arguments = {
        "adapter_id": "test.mem0.runtime.v1",
        "implementation_sha256": "a" * 64,
        "target_identity_sha256": "b" * 64,
        "probe_nonce_sha256": "c" * 64,
        "probe_token_credential_binding_id": "sha256:" + "d" * 64,
        "request_timeout_seconds": 2.0,
        "deadline_policy": MANAGED_MEM0_RUNTIME_DEADLINE_POLICY,
        "deadline_budget_seconds": 10.0,
        "minimum_network_timeout_seconds": 0.001,
        "max_attempts": 1,
        "expected_runtime_mode": "managed_platform",
    }
    arguments[field] = value

    with pytest.raises(ManagedMem0RuntimeAuthorityError, match="descriptor"):
        ManagedMem0RuntimeAuthorityDescriptor(**arguments)
