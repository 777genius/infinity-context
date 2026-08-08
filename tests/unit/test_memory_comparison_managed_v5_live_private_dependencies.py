from __future__ import annotations

import hashlib
import pickle
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from infinity_context_server import memory_comparison_managed_v5_live_preparation as preparation
from infinity_context_server import (
    memory_comparison_managed_v5_live_private_dependencies as subject,
)
from infinity_context_server import memory_comparison_managed_v5_production_runner as runner
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonBackendTarget,
    FullComparisonRunBindings,
    _binding_fields,
    _json_sha256,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    REGISTRATION_SCHEMA_VERSION,
    ManagedBenchmarkRegistryHttpConfig,
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
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    VerifiedManagedRunPlan,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials_models import (
    ManagedRuntimeCredentialError,
)
from infinity_context_server.memory_comparison_managed_v5_extraction_budget import (
    ManagedV5ExtractionReservationUnit,
    ManagedV5ExtractionTokenBudget,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_credentials import (
    ManagedV5InfinityCredentialBundle,
    _InfinityCredentialState,
    _state_integrity,
)
from infinity_context_server.memory_comparison_managed_v5_live_config import (
    ManagedV5LiveConfig,
)
from infinity_context_server.resumable_operation_journal.crypto import (
    HmacSha256OperationJournalSigner,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationJournalError,
    OperationManifest,
    OperationReceipt,
    OperationRunIdentity,
)
from infinity_context_server.resumable_operation_journal.service import (
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal

_NOW = datetime(2026, 8, 8, tzinfo=UTC)
_DEADLINE = _NOW + timedelta(minutes=5)
_ORIGIN = "https://infinity.example.test"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _operation(run_id: str, ordinal: int) -> LogicalOperationIdentity:
    return LogicalOperationIdentity(
        run_id=run_id,
        operation_key=f"operation-{ordinal}",
        operation_kind="managed_mem0_v5_extraction",
        ordinal=ordinal,
        authority_commitment_sha256=_sha("authority"),
    )


def test_operation_policy_commitment_binds_exact_extraction_budget() -> None:
    authority_commitment = _sha("production-authority")
    unit = ManagedV5ExtractionReservationUnit(100, 4096)
    bounded = ManagedMem0V5BudgetPolicy(
        100,
        ManagedV5ExtractionTokenBudget.reserve(
            (unit,),
            operator_extraction_token_ceiling=5000,
            operator_total_token_ceiling=10_000,
        ),
    )
    raised = ManagedMem0V5BudgetPolicy(
        100,
        ManagedV5ExtractionTokenBudget.reserve(
            (unit,),
            operator_extraction_token_ceiling=6000,
            operator_total_token_ceiling=10_000,
        ),
    )
    commitment = subject.managed_v5_live_operation_policy_commitment
    assert commitment(
        production_authority_commitment_sha256=authority_commitment,
        budget_policy=bounded,
    ) != commitment(
        production_authority_commitment_sha256=authority_commitment,
        budget_policy=raised,
    )
    assert commitment(
        production_authority_commitment_sha256=authority_commitment,
        budget_policy=bounded,
    ) != commitment(
        production_authority_commitment_sha256=authority_commitment,
        budget_policy=ManagedMem0V5BudgetPolicy(100),
    )


def _secret_fixture(
    tmp_path: Path,
    *,
    collision: tuple[int, int] | None = None,
) -> tuple[SimpleNamespace, ManagedMem0V5CredentialPaths]:
    state_root = tmp_path / "state"
    secret_root = tmp_path / "secrets"
    state_root.mkdir(mode=0o700)
    secret_root.mkdir(mode=0o700)
    names = (
        "bearer",
        "evidence",
        "receipt",
        "checkpoint-signing",
        "checkpoint-head",
        "operation-signer",
        "durable-hmac",
    )
    values = [f"secret-role-{index}-".encode() + bytes([65 + index]) * 32 for index in range(7)]
    if collision is not None:
        values[collision[1]] = values[collision[0]]
    paths = tuple(secret_root / name for name in names)
    for path, value in zip(paths, values, strict=True):
        path.write_bytes(value)
        path.chmod(0o600)
    filesystem = SimpleNamespace(
        state_root=state_root,
        secret_root=secret_root,
        operation_journal=state_root / "operations.sqlite3",
        durable_clean_state=state_root / "durable-clean-state.json",
        ingress_bearer_file=paths[0],
        evidence_key_file=paths[1],
        receipt_secret_file=paths[2],
        checkpoint_signing_key_file=paths[3],
        checkpoint_head_key_file=paths[4],
        operation_journal_signer_secret_file=paths[5],
        durable_clean_state_hmac_secret_file=paths[6],
    )
    return filesystem, ManagedMem0V5CredentialPaths(*paths[:5])


def test_production_receipt_verifier_enforces_exact_namespace_and_binding() -> None:
    identity = _operation("live-run", 0)
    manifest = OperationManifest((identity,))
    authority = subject.ManagedMem0V5OperationReceiptAuthority(
        key=b"r" * 32,
        key_id="receipt-key-v1",
        manifest=manifest,
    )
    assert not hasattr(authority, "issue")
    receipt = authority._issue_exact(
        identity=identity,
        request_commitment_sha256=_sha("request"),
        result_commitment_sha256=_sha("result"),
    )
    verified = authority.verify(identity=identity, receipt=receipt)
    assert verified.receipt is receipt
    assert verified.verifier_key_id == "receipt-key-v1"
    assert (
        authority._issue_exact(
            identity=identity,
            request_commitment_sha256=_sha("request"),
            result_commitment_sha256=_sha("result"),
        )
        is receipt
    )

    forged = OperationReceipt(
        run_id=receipt.run_id,
        logical_operation_id=receipt.logical_operation_id,
        request_commitment_sha256=receipt.request_commitment_sha256,
        receipt_id="m5r_" + "0" * 64,
        result_commitment_sha256=receipt.result_commitment_sha256,
    )
    with pytest.raises(OperationJournalError, match="authentication_failed"):
        authority.verify(identity=identity, receipt=forged)
    changed_result = OperationReceipt(
        run_id=receipt.run_id,
        logical_operation_id=receipt.logical_operation_id,
        request_commitment_sha256=receipt.request_commitment_sha256,
        receipt_id=receipt.receipt_id,
        result_commitment_sha256=_sha("changed-result"),
    )
    with pytest.raises(OperationJournalError, match="authentication_failed"):
        authority.verify(identity=identity, receipt=changed_result)
    with pytest.raises(OperationJournalError, match="replay_divergent"):
        authority._issue_exact(
            identity=identity,
            request_commitment_sha256=_sha("request"),
            result_commitment_sha256=_sha("changed-result"),
        )
    cross_run = _operation("other-run", 0)
    with pytest.raises(OperationJournalError, match="identity_invalid"):
        authority.verify(identity=cross_run, receipt=receipt)


def test_fourth_registry_lane_is_transport_separate_and_one_shot() -> None:
    transports = tuple(httpx.MockTransport(lambda _request: httpx.Response(500)) for _ in range(4))
    state = _InfinityCredentialState(
        run_id="live-run",
        origin=_ORIGIN,
        target_identity_sha256=managed_backend_target_identity_sha256(
            backend_role="infinity-context", base_url=_ORIGIN
        ),
        auth_token="registry-secret",
        timeout_seconds=30.0,
        execution_transport=transports[0],
        lifecycle_transport=transports[1],
        registry_policy_transport=transports[2],
        benchmark_registry_transport=transports[3],
        deadline=_DEADLINE,
        request_identity=1,
        request_commitment=_sha("request"),
        binding_key=b"k" * 32,
        preparation_identity=2,
        preparation_commitment=_sha("preparation"),
        activation_identity=3,
        activation_commitment=_sha("activation"),
        activation_phase="bound",
    )
    state.integrity = _state_integrity(state)
    bundle = object.__new__(ManagedV5InfinityCredentialBundle)
    object.__setattr__(bundle, "_ManagedV5InfinityCredentialBundle__state", state)
    object.__setattr__(bundle, "_ManagedV5InfinityCredentialBundle__lock", threading.RLock())

    config = bundle.issue_benchmark_registry_config(now=_NOW, clock=lambda: _NOW)
    assert config.transport is transports[3]
    assert all(config.transport is not item for item in transports[:3])
    with pytest.raises(ManagedRuntimeCredentialError, match="terminal"):
        bundle.issue_benchmark_registry_config(now=_NOW, clock=lambda: _NOW)


def test_credential_activation_binding_is_idempotent_only_for_exact_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_identity = managed_backend_target_identity_sha256(
        backend_role="infinity-context", base_url=_ORIGIN
    )
    state = _InfinityCredentialState(
        run_id="live-run",
        origin=_ORIGIN,
        target_identity_sha256=target_identity,
        auth_token="registry-secret",
        timeout_seconds=30.0,
        execution_transport=None,
        lifecycle_transport=None,
        registry_policy_transport=None,
        benchmark_registry_transport=None,
        deadline=_DEADLINE,
        request_identity=1,
        request_commitment=_sha("request"),
        binding_key=b"k" * 32,
        preparation_identity=2,
        preparation_commitment=_sha("preparation"),
    )
    state.integrity = _state_integrity(state)
    bundle = object.__new__(ManagedV5InfinityCredentialBundle)
    object.__setattr__(bundle, "_ManagedV5InfinityCredentialBundle__state", state)
    object.__setattr__(bundle, "_ManagedV5InfinityCredentialBundle__lock", threading.RLock())
    target = SimpleNamespace(
        backend_role="infinity-context",
        target_identity_sha256=target_identity,
    )

    def material() -> SimpleNamespace:
        return SimpleNamespace(
            request=SimpleNamespace(run_id="live-run"),
            preparation_identity=2,
            preparation_commitment=_sha("preparation"),
            composition_binding=SimpleNamespace(
                deadline=_DEADLINE,
                backend_targets=(target,),
            ),
            integrity_mac=b"activated-mac",
        )

    exact = material()
    monkeypatch.setattr(
        preparation,
        "_authenticate_activated_managed_v5_public_run",
        lambda value: value,
    )
    bundle._bind_activated_preparation(exact, now=_NOW)
    bundle._bind_activated_preparation(exact, now=_NOW)
    with pytest.raises(ManagedRuntimeCredentialError, match="terminal"):
        bundle._bind_activated_preparation(material(), now=_NOW)


def test_seven_secret_snapshot_returns_sealed_one_shot_capabilities(tmp_path: Path) -> None:
    filesystem, paths = _secret_fixture(tmp_path)
    credentials, signer, durable = subject._load_seven_distinct_secrets(
        filesystem=filesystem,
        credential_paths=paths,
    )
    assert type(credentials) is ManagedMem0V5CredentialCapabilities
    assert signer != durable
    capability = subject._OneShotSecretCapability(durable)
    capability.validate()
    assert capability.consume() == durable
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError, match="secret_terminal"):
        capability.consume()

    credentials.close()
    filesystem.operation_journal_signer_secret_file.chmod(0o640)
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError, match="secret_invalid"):
        subject._load_seven_distinct_secrets(
            filesystem=filesystem,
            credential_paths=paths,
        )


@pytest.mark.parametrize("existing_role", range(5))
@pytest.mark.parametrize("new_role", (5, 6))
def test_new_secret_roles_cannot_reuse_any_existing_mem0_secret(
    tmp_path: Path,
    existing_role: int,
    new_role: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls: list[str] = []
    monkeypatch.setattr(
        subject,
        "ManagedBenchmarkRegistryHttpAdapter",
        lambda _config: network_calls.append("registry"),
    )
    filesystem, paths = _secret_fixture(
        tmp_path,
        collision=(existing_role, new_role),
    )
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError, match="secret_reused"):
        subject._load_seven_distinct_secrets(
            filesystem=filesystem,
            credential_paths=paths,
        )
    assert network_calls == []


def test_factory_registers_last_and_recovers_multi_operation_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "live-run"
    operations = (_operation(run_id, 0), _operation(run_id, 1))
    manifest = OperationManifest(operations)
    backend_targets = (
        FullComparisonBackendTarget("infinity-context", _sha("infinity-target")),
        FullComparisonBackendTarget("mem0", _sha("mem0-target")),
    )
    binding_values = {
        "run_id": run_id,
        "run_nonce_commitment_sha256": _sha("run-nonce"),
        "runtime_probe_nonce_sha256": _sha("probe-nonce"),
        "profile_id": "mem0-locomo-top50-v1",
        "methodology_commitment_sha256": _sha("methodology"),
        "dataset_sha256": _sha("dataset"),
        "selection_fingerprint_sha256": _sha("selection"),
        "backend_targets": backend_targets,
        "mem0_expected_runtime_mode": "oss",
        "scope": "canary",
    }
    binding_sha = _json_sha256(_binding_fields(**binding_values))
    run_bindings = FullComparisonRunBindings(
        **binding_values,
        binding_commitment_sha256=binding_sha,
    )
    plan = object.__new__(VerifiedManagedRunPlan)
    activated = SimpleNamespace(
        plan=plan,
        request=SimpleNamespace(run_id=run_id),
        composition_binding=SimpleNamespace(deadline=_DEADLINE),
        production_authority=object(),
        operation_manifest=manifest,
    )
    descriptor = SimpleNamespace(
        run_id_sha256=_sha(run_id),
        authority_commitment_sha256=_sha("production-authority"),
    )
    monkeypatch.setattr(
        subject,
        "_authenticate_activated_managed_v5_public_run",
        lambda value: activated,
    )
    monkeypatch.setattr(
        subject,
        "_inspect_verified_managed_run_plan",
        lambda value: SimpleNamespace(run_id=run_id),
    )
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_run_bindings",
        lambda value: run_bindings,
    )
    monkeypatch.setattr(
        subject,
        "inspect_managed_mem0_v5_production_authority",
        lambda value: descriptor,
    )

    target = managed_backend_target_identity_sha256(
        backend_role="infinity-context", base_url=_ORIGIN
    )
    network_events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        network_events.append(request.method)
        assert (tmp_path / "state" / "operations.sqlite3").exists()
        return httpx.Response(
            201,
            json={
                "data": {
                    "schema_version": "memory-comparison-run-registration-response.v1",
                    "authority": "infinity_canonical",
                    "run_id_sha256": descriptor.run_id_sha256,
                    "binding_commitment_sha256": binding_sha,
                    "infinity_target_identity_sha256": target,
                    "space_id": "space-live-run",
                    "space_slug": "memory-comparison-live-run",
                    "state": "active",
                    "created": True,
                }
            },
        )

    registry_config = ManagedBenchmarkRegistryHttpConfig(
        base_url=_ORIGIN,
        admin_bearer_token="registry-secret",
        target_identity_sha256=target,
        timeout_seconds=30,
        benchmark_deadline=_DEADLINE,
        cleanup_recovery_timeout_seconds=30,
        transport=httpx.MockTransport(handler),
        clock=lambda: _NOW,
    )
    credentials = object.__new__(ManagedV5InfinityCredentialBundle)
    monkeypatch.setattr(
        ManagedV5InfinityCredentialBundle,
        "_bind_activated_preparation",
        lambda self, value, *, now: None,
    )
    monkeypatch.setattr(
        ManagedV5InfinityCredentialBundle,
        "issue_benchmark_registry_config",
        lambda self, *, now, clock: registry_config,
    )

    filesystem, credential_paths = _secret_fixture(tmp_path)
    state_root = filesystem.state_root
    config = object.__new__(ManagedV5LiveConfig)
    object.__setattr__(config, "filesystem", filesystem)
    object.__setattr__(config, "runtime", object())
    factory = subject.ManagedV5LivePrivateDependencyFactory(
        config=config,
        budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=100),
    )
    captured: dict[str, object] = {}
    original_create = subject.ManagedV5LivePrivateDependencyFactory.create

    def capture_material(self, **kwargs):
        material = original_create(self, **kwargs)
        captured["material"] = material
        return material

    runtime_sentinel = object()
    monkeypatch.setattr(
        subject.ManagedV5LivePrivateDependencyFactory,
        "create",
        capture_material,
    )
    monkeypatch.setattr(runner, "_activate_managed_v5_public_run", lambda *_, **__: activated)

    def capture_runtime(**kwargs):
        captured["runtime_identity"] = kwargs["operation_run_identity"]
        return runtime_sentinel

    monkeypatch.setattr(runner, "create_managed_v5_production_runtime", capture_runtime)
    runtime = runner.activate_managed_v5_production_runtime_with_factory(
        object(),
        cases=(),
        request=activated.request,
        composition_binding=activated.composition_binding,
        receipt_authority=object(),
        production_authority=activated.production_authority,
        plan=plan,
        run_bindings=run_bindings,
        now=_NOW,
        deadline=_DEADLINE,
        infinity_credentials=credentials,
        dependency_factory=factory,
        current_date="2026-08-08",
        mem0_origin=_ORIGIN,
        timeout_seconds=30,
        state_paths=object(),
        credential_paths=credential_paths,
        runtime_receipt_boundary=object(),
        trusted_runtime_binding=object(),
        clock=lambda: _NOW,
    )
    material = captured["material"]
    runtime_identity = captured["runtime_identity"]
    assert runtime is runtime_sentinel
    assert type(material) is subject.ManagedV5LivePrivateDependencyMaterial
    assert type(runtime_identity) is OperationRunIdentity
    assert runtime_identity.policy_commitment_sha256 == (
        material.operation_policy_commitment_sha256
    )
    assert network_events == ["POST"]
    prepared = material.operation_journal.prepare_dispatch_batch(
        tuple((item, _sha(f"request-{item.ordinal}")) for item in operations)
    )
    assert tuple(item.should_dispatch for item in prepared) == (True, True)

    signer = HmacSha256OperationJournalSigner(
        key_id=material.operation_signer_key_id,
        secret=filesystem.operation_journal_signer_secret_file.read_bytes(),
    )
    identity = OperationRunIdentity(
        run_id=run_id,
        operation_namespace="managed_mem0_v5_production",
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=material.operation_policy_commitment_sha256,
        signer_key_id=signer.key_id,
        expected_operation_count=2,
    )
    recovered = ResumableOperationJournalService(
        journal=SQLiteOperationJournal(
            filesystem.operation_journal,
            private_directory=state_root,
        ),
        signer=signer,
        manifest_policy=subject._ExactManifestPolicy(identity, manifest),
        receipt_verifier=material.operation_receipt_authority,
        notifications=NullOperationNotification(),
    )
    state = recovered.initialize(identity, manifest)
    assert state.event_count == 3
    replay = recovered.prepare_dispatch_batch(
        tuple((item, _sha(f"request-{item.ordinal}")) for item in operations)
    )
    assert tuple(item.should_dispatch for item in replay) == (False, False)
    material.mem0_credential_capabilities.close()


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
        created=created,
    )
    manifest = OperationManifest((_operation("live-run", 0),))
    receipt_authority = subject.ManagedMem0V5OperationReceiptAuthority(
        key=b"r" * 32,
        key_id="receipt-key-v1",
        manifest=manifest,
    )
    credential_capabilities = ManagedMem0V5CredentialCapabilities(
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

    def begin_cleanup(self):
        events.append("registry.begin_cleanup")
        if compensation_fails:
            raise RuntimeError("injected compensation failure")
        return SimpleNamespace(projection_cleanup="blocked", receipt_sha256="4" * 64)

    def finalize_abort(self, **kwargs):
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
            mem0_credential_capabilities=credential_capabilities,
            benchmark_registry=registry,
            benchmark_registration=registration,
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


def test_factory_closes_registry_when_registration_fails_without_recovery() -> None:
    closed: list[bool] = []

    class _Registry:
        cleanup_required = False

        def __init__(self, config: object) -> None:
            del config

        def register(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("rejected")

        def close(self) -> None:
            closed.append(True)

    registry = _Registry(object())
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError) as captured:
        subject._register_final(
            registry,  # type: ignore[arg-type]
            run_id_sha256="a" * 64,
            binding_commitment_sha256="b" * 64,
            infinity_target_identity_sha256="c" * 64,
            space_slug="memory-comparison-live-run",
        )
    assert captured.value.recovery_registry is None
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
    with pytest.raises(subject.ManagedV5LivePrivateDependencyError) as captured:
        subject._register_final(
            registry,
            run_id_sha256="a" * 64,
            binding_commitment_sha256="b" * 64,
            infinity_target_identity_sha256="c" * 64,
            space_slug="memory-comparison-live-run",
        )
    assert captured.value.recovery_registry is registry
    envelope = captured.value.recovery_envelope
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
