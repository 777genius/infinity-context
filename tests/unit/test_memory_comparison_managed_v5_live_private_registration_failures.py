from __future__ import annotations

import pickle
from types import SimpleNamespace

import pytest
from infinity_context_server import (
    memory_comparison_managed_v5_live_private_dependencies as subject,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    REGISTRATION_SCHEMA_VERSION,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialCapabilities,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.resumable_operation_journal.domain import OperationManifest
from infinity_context_server.resumable_operation_journal.service import (
    ResumableOperationJournalService,
)
from test_memory_comparison_managed_v5_live_private_dependencies import _NOW, _operation


@pytest.mark.parametrize("created", (False, True))
@pytest.mark.parametrize("compensation_fails", (False, True))
def test_material_construction_failure_never_orphans_registration(
    monkeypatch: pytest.MonkeyPatch,
    compensation_fails: bool,
    created: bool,
) -> None:
    events: list[str] = []
    registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    registration = ManagedBenchmarkRunRegistration(
        schema_version=REGISTRATION_SCHEMA_VERSION,
        authority="infinity_canonical",
        run_id_sha256="1" * 64,
        binding_commitment_sha256="2" * 64,
        infinity_target_identity_sha256="3" * 64,
        space_id="space-1",
        space_slug="memory-comparison-run-1",
        state="active",
        cleanup_plan_sha256="4" * 64,
        cleanup_plan_state="sealed",
        created=created,
    )
    receipt_authority = subject.ManagedMem0V5OperationReceiptAuthority(
        key=b"r" * 32,
        key_id="receipt-key-v1",
        manifest=OperationManifest((_operation("live-run", 0),)),
    )
    credentials = ManagedMem0V5CredentialCapabilities(
        tuple(bytearray(bytes([65 + index]) * 32) for index in range(5))
    )
    monkeypatch.setattr(
        subject,
        "ManagedV5LivePrivateDependencyMaterial",
        lambda **_: (_ for _ in ()).throw(RuntimeError("injected constructor failure")),
    )
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "cleanup_receipt",
        property(lambda self: None),
    )

    def begin_cleanup(self: object) -> object:
        events.append("registry.begin_cleanup")
        if compensation_fails:
            raise RuntimeError("injected compensation failure")
        return SimpleNamespace(projection_cleanup="blocked", receipt_sha256="4" * 64)

    def finalize_abort(self: object, **kwargs: object) -> None:
        events.append("registry.finalize_unsealed_abort")
        assert kwargs == {"cleanup_initiation_receipt_sha256": "4" * 64}

    monkeypatch.setattr(ManagedBenchmarkRegistryHttpAdapter, "begin_cleanup", begin_cleanup)
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "finalize_unsealed_abort",
        finalize_abort,
    )
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError) as caught:
        subject._material_after_registration(
            budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=10),
            clean_state_snapshot_factory=object.__new__(ManagedMem0V5HttpCleanStateSnapshotFactory),
            durable_clean_state_factory=object.__new__(ManagedMem0V5HmacDurableCleanStateFactory),
            operation_journal=object.__new__(ResumableOperationJournalService),
            operation_signer_key_id="test-signer",
            operation_policy_commitment_sha256="a" * 64,
            operation_receipt_authority=receipt_authority,
            mem0_credential_capabilities=credentials,
            benchmark_registry=registry,
            benchmark_registration=registration,
            recovery_observer=object(),
            infinity_derived_transport_factory=None,
            infinity_cleanup_transport_factory=None,
        )
    assert caught.value.code == (
        "managed_v5_live_private_dependencies_material_construction_failed"
    )
    assert caught.value.recovery_registry is (registry if compensation_fails else None)
    if compensation_fails:
        assert caught.value.recovery_envelope.stage == "begin_cleanup"
        assert caught.value.recovery_envelope.registration is registration
    else:
        assert caught.value.recovery_envelope is None
    assert events == (
        ["registry.begin_cleanup"]
        if compensation_fails
        else ["registry.begin_cleanup", "registry.finalize_unsealed_abort"]
    )


def _register_failure(
    monkeypatch: pytest.MonkeyPatch,
    registry: object,
) -> subject.ManagedV5LivePrivateDependencyError:
    monkeypatch.setattr(
        subject,
        "register_and_observe_managed_v5",
        lambda value, **kwargs: value.register(**kwargs),
    )
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError) as captured:
        subject._register_final(
            registry,  # type: ignore[arg-type]
            cleanup_plan=object(),  # type: ignore[arg-type]
            recovery_authority=object(),  # type: ignore[arg-type]
            recovery_journal=object(),  # type: ignore[arg-type]
            registry_config=object(),  # type: ignore[arg-type]
            run_id_sha256="a" * 64,
            binding_commitment_sha256="b" * 64,
            infinity_target_identity_sha256="c" * 64,
            space_slug="memory-comparison-live-run",
            clock=lambda: _NOW,
        )
    return captured.value


def test_factory_closes_registry_when_registration_fails_without_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class _Registry:
        cleanup_required = False

        def register(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("rejected")

        def close(self) -> None:
            closed.append(True)

    captured = _register_failure(monkeypatch, _Registry())
    assert captured.recovery_registry is None
    assert closed == [True]


def test_factory_preserves_registry_when_registration_outcome_needs_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "cleanup_required",
        property(lambda self: True),
    )
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "register",
        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("outcome unknown")),
    )
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "close",
        lambda self: pytest.fail("recoverable registry must remain open"),
    )
    captured = _register_failure(monkeypatch, registry)
    assert captured.recovery_registry is registry
    envelope = captured.recovery_envelope
    assert envelope.stage == "registration_outcome_unknown"
    assert envelope.registration is None
    assert envelope.cleanup_receipt is None
    assert envelope.run_id_sha256 == "a" * 64
    assert envelope.binding_commitment_sha256 == "b" * 64
    assert envelope.infinity_target_identity_sha256 == "c" * 64
    assert envelope.space_slug == "memory-comparison-live-run"
    assert "ManagedBenchmarkRegistryHttpAdapter" not in repr(envelope)
    with pytest.raises(TypeError, match="nonserializable"):
        pickle.dumps(envelope)
