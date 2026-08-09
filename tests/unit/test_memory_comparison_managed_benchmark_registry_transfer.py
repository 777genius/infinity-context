from __future__ import annotations

import httpx
import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
    ManagedBenchmarkRegistryHttpError,
)
from memory_comparison_managed_benchmark_registry_test_support import (
    BINDING,
    RUN,
    SPACE_SLUG,
    _config,
    _plan,
    _target,
)


def test_lost_registration_response_can_transfer_exact_attempt_authority_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("response lost", request=request)

    transport = httpx.MockTransport(lost)
    closed: list[bool] = []
    original_close = httpx.MockTransport.close
    monkeypatch.setattr(
        httpx.MockTransport,
        "close",
        lambda self: (closed.append(True), original_close(self))[1],
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(transport))
    with pytest.raises(ManagedBenchmarkRegistryHttpError):
        adapter.register(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
            cleanup_plan=_plan(),
        )

    receipt = adapter.relinquish_recovery_authority(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=_target(),
        space_slug=SPACE_SLUG,
        cleanup_plan_sha256=_plan().sha256,
    )

    assert receipt.prior_phase == "registration_outcome_unknown"
    assert receipt.transport_close_confirmed is True
    assert receipt.transport_close_warning is None
    assert len(closed) == 1
    with pytest.raises(ManagedBenchmarkRegistryHttpError):
        adapter.relinquish_recovery_authority(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=_target(),
            space_slug=SPACE_SLUG,
            cleanup_plan_sha256=_plan().sha256,
        )
    assert len(closed) == 1


def test_lost_fresh_get_can_transfer_exact_recovery_attempt_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("response lost", request=request)

    transport = httpx.MockTransport(lost)
    closed: list[bool] = []
    original_close = httpx.MockTransport.close
    monkeypatch.setattr(
        httpx.MockTransport,
        "close",
        lambda self: (closed.append(True), original_close(self))[1],
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(transport))
    with pytest.raises(ManagedBenchmarkRegistryHttpError):
        adapter.recover_lifecycle(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
            cleanup_plan_sha256=_plan().sha256,
        )

    receipt = adapter.relinquish_recovery_authority(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=_target(),
        space_slug=SPACE_SLUG,
        cleanup_plan_sha256=_plan().sha256,
    )

    assert receipt.prior_phase == "recovery_outcome_unknown"
    assert receipt.transport_close_confirmed is True
    assert receipt.transport_close_warning is None
    assert len(closed) == 1


def test_transport_close_failure_returns_exact_transfer_receipt_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("response lost", request=request)

    monkeypatch.setattr(
        httpx.MockTransport,
        "close",
        lambda _self: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    adapter = ManagedBenchmarkRegistryHttpAdapter(_config(httpx.MockTransport(lost)))
    with pytest.raises(ManagedBenchmarkRegistryHttpError):
        adapter.register(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            space_slug=SPACE_SLUG,
            cleanup_plan=_plan(),
        )

    receipt = adapter.relinquish_recovery_authority(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=_target(),
        space_slug=SPACE_SLUG,
        cleanup_plan_sha256=_plan().sha256,
    )

    assert receipt.schema_version == "memory-comparison-benchmark-recovery-authority-transfer.v2"
    assert receipt.prior_phase == "registration_outcome_unknown"
    assert receipt.transport_close_confirmed is False
    assert (
        receipt.transport_close_warning == "managed_benchmark_registry_transport_close_unconfirmed"
    )
    with pytest.raises(ManagedBenchmarkRegistryHttpError):
        adapter.relinquish_recovery_authority(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=_target(),
            space_slug=SPACE_SLUG,
            cleanup_plan_sha256=_plan().sha256,
        )
