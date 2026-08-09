from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
    validate_managed_benchmark_cleanup_plan,
)
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
    ManagedBenchmarkRegistryHttpConfig,
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
from infinity_context_server.memory_comparison_managed_v5_recovery_journal import (
    ManagedV5LiveRecoveryJournalStore,
    RecoveryJournalAuthenticator,
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
from test_memory_comparison_managed_v5_recovery_journal import _authority

_NOW = datetime(2026, 8, 8, tzinfo=UTC)
_DEADLINE = _NOW + timedelta(minutes=5)
_ORIGIN = "https://infinity.example.test"
_INFINITY_ORIGIN = "http://127.0.0.1:17789"


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
        "runtime-attestation",
        "recovery-hmac",
    )
    values = [f"secret-role-{index}-".encode() + bytes([65 + index]) * 32 for index in range(9)]
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
        runtime_attestation_secret_file=paths[7],
        recovery_hmac_secret_file=paths[8],
        runtime_attestation_secret_sha256=hashlib.sha256(values[7]).hexdigest(),
    )
    return filesystem, ManagedMem0V5CredentialPaths(*paths[:5])


def _recovery_inputs(
    tmp_path: Path,
    *,
    run_id: str,
    binding: str,
    target: str,
    space_slug: str,
) -> tuple[ManagedBenchmarkCleanupPlan, object, ManagedV5LiveRecoveryJournalStore, str]:
    authority = replace(
        _authority(tmp_path),
        run_id=run_id,
        run_id_sha256=_sha(run_id),
        binding_commitment_sha256=binding,
        infinity_target_identity_sha256=target,
        space_slug=space_slug,
        infinity_origin=_INFINITY_ORIGIN,
        current_date="2026-08-08",
        issued_at="2026-08-08T00:00:00Z",
        deadline="2026-08-08T00:05:00Z",
    )
    recovery_secret = b"secret-role-8-" + b"I" * 32
    authenticator = RecoveryJournalAuthenticator(
        secret=recovery_secret,
        run_id_sha256=authority.run_id_sha256,
    )
    store = ManagedV5LiveRecoveryJournalStore(
        path=authority.state_root / "recovery.json",
        state_root=authority.state_root,
        authenticator=authenticator,
    )
    store.initialize(
        authority=authority,
        recorded_at=authority.issued_at,
        details={"authority_sha256": authority.sha256},
    )
    value, digest = cleanup_plan_pair(
        run_id=authority.run_id_sha256,
        binding=binding,
        target=target,
        space_slug=space_slug,
    )
    cleanup_plan = validate_managed_benchmark_cleanup_plan(
        value,
        digest,
        run_id_sha256=authority.run_id_sha256,
        binding_commitment_sha256=binding,
        infinity_target_identity_sha256=target,
        space_slug=space_slug,
    )
    return cleanup_plan, authority, store, hashlib.sha256(recovery_secret).hexdigest()


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


def test_nine_secret_snapshot_returns_sealed_one_shot_capabilities(tmp_path: Path) -> None:
    filesystem, paths = _secret_fixture(tmp_path)
    recovery_sha = hashlib.sha256(filesystem.recovery_hmac_secret_file.read_bytes()).hexdigest()
    credentials, signer, durable = subject.load_nine_distinct_secrets(
        filesystem=filesystem,
        credential_paths=paths,
        recovery_secret_sha256=recovery_sha,
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
    with pytest.raises(subject.ManagedV5LiveSecretSnapshotError, match="secret_invalid"):
        subject.load_nine_distinct_secrets(
            filesystem=filesystem,
            credential_paths=paths,
            recovery_secret_sha256=recovery_sha,
        )


@pytest.mark.parametrize("existing_role", range(5))
@pytest.mark.parametrize("new_role", (5, 6, 7, 8))
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
    with pytest.raises(subject.ManagedV5LiveSecretSnapshotError, match="secret_reused"):
        subject.load_nine_distinct_secrets(
            filesystem=filesystem,
            credential_paths=paths,
            recovery_secret_sha256=hashlib.sha256(
                filesystem.recovery_hmac_secret_file.read_bytes()
            ).hexdigest(),
        )
    assert network_calls == []


def test_typed_construction_failure_closes_loaded_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "typed-failure-run"
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
    run_bindings = FullComparisonRunBindings(
        **binding_values,
        binding_commitment_sha256=_json_sha256(_binding_fields(**binding_values)),
    )
    plan = object.__new__(VerifiedManagedRunPlan)
    manifest = OperationManifest((_operation(run_id, 0),))
    activated = SimpleNamespace(
        plan=plan,
        request=SimpleNamespace(run_id=run_id),
        composition_binding=SimpleNamespace(deadline=_DEADLINE),
        production_authority=object(),
        operation_manifest=manifest,
    )
    monkeypatch.setattr(
        subject,
        "_authenticate_activated_managed_v5_public_run",
        lambda _value: activated,
    )
    monkeypatch.setattr(
        subject,
        "_inspect_verified_managed_run_plan",
        lambda _value: SimpleNamespace(run_id=run_id),
    )
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_run_bindings",
        lambda _value: run_bindings,
    )
    monkeypatch.setattr(
        subject,
        "inspect_managed_mem0_v5_production_authority",
        lambda _value: SimpleNamespace(
            run_id_sha256=_sha(run_id),
            authority_commitment_sha256=_sha("production-authority"),
        ),
    )
    infinity_credentials = object.__new__(ManagedV5InfinityCredentialBundle)
    monkeypatch.setattr(
        ManagedV5InfinityCredentialBundle,
        "_bind_activated_preparation",
        lambda self, value, *, now: None,
    )
    closed: list[bool] = []
    loaded_credentials = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(
        subject,
        "load_nine_distinct_secrets",
        lambda **_values: (loaded_credentials, b"s" * 32, b"d" * 32),
    )

    def typed_failure(**_values: object) -> str:
        raise subject.ManagedV5LivePrivateDependencyError("injected_typed_failure")

    monkeypatch.setattr(subject, "managed_v5_live_operation_policy_commitment", typed_failure)
    filesystem, credential_paths = _secret_fixture(tmp_path)
    config = object.__new__(ManagedV5LiveConfig)
    object.__setattr__(config, "filesystem", filesystem)
    object.__setattr__(config, "runtime", object())
    cleanup_plan, recovery_authority, recovery_journal, recovery_secret_sha256 = _recovery_inputs(
        tmp_path,
        run_id=run_id,
        binding=run_bindings.binding_commitment_sha256,
        target=managed_backend_target_identity_sha256(
            backend_role="infinity-context", base_url=_INFINITY_ORIGIN
        ),
        space_slug="memory-comparison-typed-failure-run",
    )

    with pytest.raises(
        subject.ManagedV5LivePrivateDependencyError,
        match="injected_typed_failure",
    ):
        subject._create_managed_v5_live_private_dependency_material(
            config=config,
            activated_preparation=object(),
            plan=plan,
            infinity_credentials=infinity_credentials,
            credential_paths=credential_paths,
            run_bindings=run_bindings,
            budget_policy=ManagedMem0V5BudgetPolicy(100),
            cleanup_plan=cleanup_plan,
            cleanup_target_authority_sha256=_sha("cleanup-target-authority"),
            recovery_authority=recovery_authority,
            recovery_journal=recovery_journal,
            recovery_secret_sha256=recovery_secret_sha256,
            deadline=_DEADLINE,
            now=_NOW,
            clock=lambda: _NOW,
        )

    assert closed == [True]


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
        backend_role="infinity-context", base_url=_INFINITY_ORIGIN
    )
    space_slug = "memory-comparison-live-run"
    filesystem, credential_paths = _secret_fixture(tmp_path)
    cleanup_plan, recovery_authority, recovery_journal, recovery_secret_sha256 = _recovery_inputs(
        tmp_path,
        run_id=run_id,
        binding=binding_sha,
        target=target,
        space_slug=space_slug,
    )
    space_id = f"benchmark-space-{descriptor.run_id_sha256[:48]}"
    network_events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        network_events.append(request.method)
        assert (tmp_path / "state" / "operations.sqlite3").exists()
        shared = {
            "authority": "infinity_canonical",
            "run_id_sha256": descriptor.run_id_sha256,
            "binding_commitment_sha256": binding_sha,
            "infinity_target_identity_sha256": target,
            "space_id": space_id,
            "space_slug": space_slug,
            "state": "active",
            "cleanup_plan_sha256": cleanup_plan.sha256,
            "cleanup_plan_state": "sealed",
        }
        if request.method == "POST":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "schema_version": ("memory-comparison-run-registration-response.v2"),
                        **shared,
                        "created": True,
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "schema_version": "memory-comparison-run-lifecycle-response.v2",
                    **shared,
                    "projection_cleanup_state": "unsealed",
                    "projection_manifest_sha256": None,
                    "cleanup_receipt": None,
                    "completion_receipt": None,
                }
            },
        )

    registry_config = ManagedBenchmarkRegistryHttpConfig(
        base_url=_INFINITY_ORIGIN,
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

    state_root = filesystem.state_root
    config = object.__new__(ManagedV5LiveConfig)
    object.__setattr__(config, "filesystem", filesystem)
    object.__setattr__(config, "runtime", object())
    factory = subject.ManagedV5LivePrivateDependencyFactory(
        config=config,
        budget_policy=ManagedMem0V5BudgetPolicy(maximum_total_call_count=100),
        cleanup_plan=cleanup_plan,
        cleanup_target_authority_sha256=_sha("cleanup-target-authority"),
        recovery_authority=recovery_authority,
        recovery_journal=recovery_journal,
        recovery_secret_sha256=recovery_secret_sha256,
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
    assert network_events == ["POST", "GET"]
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
