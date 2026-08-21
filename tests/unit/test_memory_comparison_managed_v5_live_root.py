from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server import memory_comparison_managed_v5_live_root as subject
from infinity_context_server import memory_comparison_managed_v5_production_runner as runner
from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    REGISTRATION_SCHEMA_VERSION,
    ManagedBenchmarkCleanupCounts,
    ManagedBenchmarkCleanupReceipt,
    ManagedBenchmarkRunRegistration,
)
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
    ManagedLiveExecutionLimits,
    VerifiedManagedLiveRunPreparation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    ManagedMem0V5StatePaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_credentials import (
    ManagedMem0V5CredentialCapabilities,
    ManagedMem0V5CredentialPaths,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_extraction_contract_binding import (
    REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
    ManagedMem0V5ExtractionContractBinding,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import ManagedMem0V5BudgetPolicy
from infinity_context_server.memory_comparison_managed_production_composition import (
    MANAGED_PRODUCTION_EXECUTION_V5,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_runner_binding import (
    ManagedRunnerCompositionBinding,
)
from infinity_context_server.memory_comparison_managed_runtime_credentials import (
    ManagedRuntimeCredentialAuthority,
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
)
from infinity_context_server.memory_comparison_managed_v5_live_preparation import (
    ManagedV5PublicRunPreparation,
)
from infinity_context_server.memory_comparison_managed_v5_live_private_dependencies import (
    ManagedMem0V5OperationReceiptAuthority,
    ManagedV5LivePrivateDependencyError,
    ManagedV5LivePrivateDependencyFactory,
    ManagedV5LivePrivateDependencyMaterial,
    ManagedV5RegistryRecoveryEnvelope,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_observer import (
    ManagedV5LiveRecoveryObserver,
)
from infinity_context_server.memory_comparison_managed_v5_production_runner import (
    ManagedV5ProductionRecoveryRequiredError,
    ManagedV5ProductionRunnerError,
)
from infinity_context_server.memory_comparison_managed_v5_runtime_factory import (
    ManagedV5ProductionRuntime,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import Mem0OssAdmissionRequest
from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.memory_comparison_provider_provenance import ProviderRouteAttestation
from infinity_context_server.resumable_operation_journal.service import (
    ResumableOperationJournalService,
)

ROOT = Path(__file__).resolve().parents[2]


def _registration(*, created: bool) -> ManagedBenchmarkRunRegistration:
    return ManagedBenchmarkRunRegistration(
        schema_version=REGISTRATION_SCHEMA_VERSION,
        authority="infinity_canonical",
        run_id_sha256="1" * 64,
        binding_commitment_sha256="2" * 64,
        infinity_target_identity_sha256="3" * 64,
        space_id="space-1",
        space_slug="memory-comparison-run-1",
        state="active",
        created=created,
        cleanup_plan_sha256="4" * 64,
        cleanup_plan_state="sealed",
    )


def _cleanup_receipt() -> ManagedBenchmarkCleanupReceipt:
    return ManagedBenchmarkCleanupReceipt(
        run_id_sha256="1" * 64,
        space_id="space-1",
        space_slug="memory-comparison-run-1",
        projection_cleanup="blocked",
        counts=ManagedBenchmarkCleanupCounts(*(0 for _ in range(10))),
        vector_delete_outbox_ids=(),
        graph_delete_outbox_ids=(),
        cognee_delete_outbox_ids=(),
        receipt_sha256="4" * 64,
        replayed=False,
    )


def _recovery_envelope(
    registry: ManagedBenchmarkRegistryHttpAdapter,
    *,
    stage: str = "begin_cleanup",
    registration: ManagedBenchmarkRunRegistration | None = None,
) -> ManagedV5RegistryRecoveryEnvelope:
    known = _registration(created=False) if registration is None else registration
    return ManagedV5RegistryRecoveryEnvelope(
        stage=stage,
        primary_reason_code="managed_v5_production_activation_failed",
        run_id_sha256=known.run_id_sha256,
        binding_commitment_sha256=known.binding_commitment_sha256,
        infinity_target_identity_sha256=known.infinity_target_identity_sha256,
        space_slug=known.space_slug,
        recovery_registry=registry,
        registration=known,
    )


def _extraction_binding(tmp_path: Path) -> ManagedMem0V5ExtractionContractBinding:
    tmp_path.mkdir(parents=True, exist_ok=True)
    reviewed_file = tmp_path / "reviewed-extraction-contract.py"
    reviewed_file.write_bytes(
        (
            ROOT
            / "benchmarks"
            / "mem0-oss-adapter-v5"
            / "mem0_oss_adapter_v5"
            / "extraction_contract.py"
        ).read_bytes()
    )
    reviewed_file.chmod(0o444)
    return ManagedMem0V5ExtractionContractBinding(
        reviewed_file.resolve(),
        REVIEWED_MEM0_V5_EXTRACTION_CONTRACT_SHA256,
    )


def _token_budget() -> ManagedV5ExtractionTokenBudget:
    return ManagedV5ExtractionTokenBudget.reserve(
        (ManagedV5ExtractionReservationUnit(100, 100),),
        operator_extraction_token_ceiling=1000,
        operator_total_token_ceiling=11_000,
    )


def _dependency_factory() -> ManagedV5LivePrivateDependencyFactory:
    factory = object.__new__(ManagedV5LivePrivateDependencyFactory)
    object.__setattr__(factory, "_budget_policy", ManagedMem0V5BudgetPolicy(100, _token_budget()))
    return factory


def _public(tmp_path: Path) -> subject.ManagedV5LivePublicInputs:
    paths = tuple(tmp_path / name for name in ("bearer", "evidence", "receipt", "sign", "head"))
    return subject.ManagedV5LivePublicInputs(
        cases=(object.__new__(ManagedRunCase),),
        current_date="2026-08-08",
        request=object.__new__(Mem0OssAdmissionRequest),
        composition_binding=object.__new__(ManagedRunnerCompositionBinding),
        mem0_origin="http://127.0.0.1:19091",
        timeout_seconds=5.0,
        state_paths=ManagedMem0V5StatePaths(tmp_path / "checkpoint", tmp_path / "head.sqlite"),
        credential_paths=ManagedMem0V5CredentialPaths(*paths),
        extraction_contract_binding=_extraction_binding(tmp_path),
        extraction_token_budget=_token_budget(),
        runtime_receipt_boundary=object(),
        trusted_runtime_binding=object(),
        receipt_authority=object.__new__(Mem0V5ObservedExtractionReceiptAuthority),
    )


def test_public_stage_finishes_before_activation_or_private_work(
    monkeypatch, tmp_path: Path
) -> None:
    events: list[str] = []
    public_capability = object.__new__(ManagedV5PublicRunPreparation)

    def prepare(**values: object) -> ManagedV5PublicRunPreparation:
        events.append("public.prepare")
        assert "provider" not in values
        assert "infinity_credentials" not in values
        return public_capability

    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", prepare)
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=object(),
            operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
        ),
    )
    monkeypatch.setattr(
        subject,
        "activate_managed_v5_production_runtime_with_factory",
        lambda *_args, **_kwargs: events.append("private.activate"),
    )

    prepared = subject.prepare_managed_v5_live_run(_public(tmp_path))

    assert subject._STATES[prepared].preparation is public_capability
    assert not hasattr(subject._STATES[prepared].inputs, "dispatch_guard")
    assert events == ["public.prepare"]


def test_private_stage_returns_explicit_v5_selection(monkeypatch, tmp_path: Path) -> None:
    public = _public(tmp_path)
    preparation = object.__new__(ManagedV5PublicRunPreparation)
    production_authority = object()
    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", lambda **_: preparation)
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=production_authority,
            operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
        ),
    )
    prepared = subject.prepare_managed_v5_live_run(public)
    runtime = object.__new__(ManagedV5ProductionRuntime)
    calls: list[dict[str, object]] = []
    credentials = object.__new__(ManagedV5InfinityCredentialBundle)
    authority = object.__new__(ManagedRuntimeCredentialAuthority)
    verified = object.__new__(VerifiedManagedLiveRunPreparation)
    route = object.__new__(ProviderRouteAttestation)
    limits = ManagedLiveExecutionLimits(
        provider_kind=MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        answerer_model="gpt-5.6-sol",
        judge_model="gpt-5.6-sol",
        max_cases=1,
        benchmark_max_provider_calls=4,
        readiness_probe_provider_calls=1,
        total_provider_attempt_ceiling=5,
        benchmark_reserved_token_ceiling=10000,
        readiness_probe_estimated_tokens=1,
        readiness_probe_usage_source="estimated_by_subscription_runtime",
        total_accounted_tokens=10001,
        token_accounting_publishable=False,
        post_reset_mem0_probe_attempt_ceiling=1,
        issued_at=datetime(2026, 8, 7, tzinfo=UTC),
        deadline=datetime(2026, 8, 8, 1, tzinfo=UTC),
    )
    plan = SimpleNamespace(
        cases=public.cases,
        run_id="run-1",
        backend_targets=(object(), object()),
        provider_route=route,
    )
    request = SimpleNamespace(
        provider_route=SimpleNamespace(origin="http://127.0.0.1:8891"),
        backend_endpoints=(
            SimpleNamespace(
                base_url="http://127.0.0.1:8080",
                target=SimpleNamespace(backend_role="infinity-context"),
            ),
        ),
    )
    material = SimpleNamespace(
        plan=object(),
        limits=limits,
        credential_authority=authority,
        readiness_claim=object(),
        preflight_request=request,
        mem0_runtime_port=object(),
    )
    monkeypatch.setattr(
        subject, "_consume_verified_managed_live_run_preparation", lambda *_, **__: material
    )
    monkeypatch.setattr(subject, "_inspect_verified_managed_run_plan", lambda _: plan)
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_run_bindings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(subject, "_require_private_matches_public", lambda *_: None)
    monkeypatch.setattr(
        ManagedRuntimeCredentialAuthority,
        "issue_managed_v5_infinity_credentials",
        lambda self, **kwargs: credentials,
    )
    monkeypatch.setattr(
        ManagedRuntimeCredentialAuthority,
        "issue_subscription_execution_adapter",
        lambda self, **kwargs: SimpleNamespace(close=lambda: None),
    )

    def activate(value: object, **kwargs: object) -> ManagedV5ProductionRuntime:
        calls.append(kwargs)
        assert value is preparation
        return runtime

    monkeypatch.setattr(subject, "activate_managed_v5_production_runtime_with_factory", activate)
    dependency_factory = _dependency_factory()
    private = subject.ManagedV5LivePrivateInputs(
        verified_preparation=verified,
        dependency_factory=dependency_factory,
        now=datetime(2026, 8, 8, tzinfo=UTC),
        wall_clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
        monotonic_clock=lambda: 100.0,
    )

    selected = subject.activate_managed_v5_live_run(prepared, private)

    assert selected.execution_mode == MANAGED_PRODUCTION_EXECUTION_V5
    assert selected.selection.runtime is runtime
    assert type(selected.selection.provider) is BoundedProviderChatCompletions
    assert calls[0]["dependency_factory"] is dependency_factory
    assert calls[0]["production_authority"] is production_authority
    assert calls[0]["infinity_credentials"] is credentials
    assert "legacy_prepared" not in calls[0]

    with pytest.raises(subject.ManagedV5LiveRootError, match="preparation_unavailable"):
        subject.activate_managed_v5_live_run(prepared, private)


def test_tampered_root_capability_fails_closed(monkeypatch, tmp_path: Path) -> None:
    preparation = object.__new__(ManagedV5PublicRunPreparation)
    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", lambda **_: preparation)
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=object(),
            operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
        ),
    )
    prepared = subject.prepare_managed_v5_live_run(_public(tmp_path))
    subject._STATES[prepared] = replace(subject._STATES[prepared], integrity_mac=b"tampered")

    with pytest.raises(subject.ManagedV5LiveRootError, match="preparation_unavailable"):
        subject.activate_managed_v5_live_run(
            prepared, object.__new__(subject.ManagedV5LivePrivateInputs)
        )


def test_tampered_extraction_binding_in_root_state_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preparation = object.__new__(ManagedV5PublicRunPreparation)
    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", lambda **_: preparation)
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=object(),
            operation_manifest=SimpleNamespace(
                commitment_sha256="b" * 64,
                operations=(object(),),
            ),
        ),
    )
    prepared = subject.prepare_managed_v5_live_run(_public(tmp_path))
    binding = subject._STATES[prepared].inputs.extraction_contract_binding
    object.__setattr__(binding, "implementation_sha256", "f" * 64)

    with pytest.raises(subject.ManagedV5LiveRootError, match="extraction_binding_invalid"):
        subject.activate_managed_v5_live_run(
            prepared,
            object.__new__(subject.ManagedV5LivePrivateInputs),
        )


def test_cross_wired_root_capability_fails_closed(monkeypatch, tmp_path: Path) -> None:
    preparations = iter(
        (
            object.__new__(ManagedV5PublicRunPreparation),
            object.__new__(ManagedV5PublicRunPreparation),
        )
    )
    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", lambda **_: next(preparations))
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=object(),
            operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
        ),
    )
    first = subject.prepare_managed_v5_live_run(_public(tmp_path / "first"))
    second = subject.prepare_managed_v5_live_run(_public(tmp_path / "second"))
    first_state = subject._STATES[first]
    subject._STATES[first] = subject._STATES[second]
    subject._STATES[second] = first_state

    for prepared in (first, second):
        with pytest.raises(subject.ManagedV5LiveRootError, match="preparation_unavailable"):
            subject.activate_managed_v5_live_run(
                prepared, object.__new__(subject.ManagedV5LivePrivateInputs)
            )


def test_private_plan_changed_nonce_binding_is_rejected() -> None:
    cases = (object(),)
    targets = (object(), object())
    profile = SimpleNamespace(
        profile_id="locomo-top-50",
        retrieval_top_k=50,
        answer_cutoff=40,
    )
    public = SimpleNamespace(
        cases=cases,
        request=SimpleNamespace(run_id="run-1"),
        composition_binding=SimpleNamespace(
            backend_targets=targets,
            binding_commitment_sha256="a" * 64,
            profile_id=profile.profile_id,
            retrieval_top_k=profile.retrieval_top_k,
            answer_cutoff=profile.answer_cutoff,
        ),
        extraction_token_budget=_token_budget(),
    )
    # All visible selection data remains identical. Only the binding commitment
    # differs, as it would after changing run_nonce_commitment_sha256.
    private_plan = SimpleNamespace(
        cases=cases,
        run_id="run-1",
        backend_targets=targets,
        profile=profile,
    )
    mutated_nonce_bindings = SimpleNamespace(
        binding_commitment_sha256="b" * 64,
        profile_id=profile.profile_id,
    )

    with pytest.raises(
        subject.ManagedV5LiveRootError,
        match="private_preparation_cross_wired",
    ):
        subject._require_private_matches_public(
            private_plan,
            mutated_nonce_bindings,
            public,
            SimpleNamespace(benchmark_reserved_token_ceiling=10_000),
        )


def test_cross_wired_private_plan_never_reaches_factory(monkeypatch, tmp_path: Path) -> None:
    public = _public(tmp_path)
    preparation = object.__new__(ManagedV5PublicRunPreparation)
    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", lambda **_: preparation)
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=object(),
            operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
        ),
    )
    prepared = subject.prepare_managed_v5_live_run(public)
    verified = object.__new__(VerifiedManagedLiveRunPreparation)
    factory = _dependency_factory()
    events: list[str] = []
    material = SimpleNamespace(
        plan=object(),
        limits=SimpleNamespace(benchmark_reserved_token_ceiling=10_000),
    )
    monkeypatch.setattr(
        subject,
        "_consume_verified_managed_live_run_preparation",
        lambda *_, **__: material,
    )
    monkeypatch.setattr(subject, "_inspect_verified_managed_run_plan", lambda _: object())
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_run_bindings",
        lambda _: object(),
    )

    def reject(*_: object) -> None:
        raise subject.ManagedV5LiveRootError("managed_v5_live_private_preparation_cross_wired")

    monkeypatch.setattr(subject, "_require_private_matches_public", reject)
    monkeypatch.setattr(
        ManagedV5LivePrivateDependencyFactory,
        "create",
        lambda self, **kwargs: events.append("factory.create"),
    )
    private = subject.ManagedV5LivePrivateInputs(
        verified_preparation=verified,
        dependency_factory=factory,
        now=datetime(2026, 8, 8, tzinfo=UTC),
        wall_clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
        monotonic_clock=lambda: 100.0,
    )

    with pytest.raises(subject.ManagedV5LiveRootError, match="cross_wired"):
        subject.activate_managed_v5_live_run(prepared, private)

    assert events == []


@pytest.mark.parametrize(
    "failure_at", ("infinity_credentials", "runtime_activation", "cleanup_required")
)
def test_private_stage_failure_closes_subscription_without_masking(
    monkeypatch,
    tmp_path: Path,
    failure_at: str,
) -> None:
    public = _public(tmp_path)
    preparation = object.__new__(ManagedV5PublicRunPreparation)
    monkeypatch.setattr(subject, "prepare_managed_v5_public_run", lambda **_: preparation)
    monkeypatch.setattr(
        subject,
        "_authenticate_managed_v5_public_run_preparation",
        lambda value: SimpleNamespace(
            production_authority=object(),
            operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
        ),
    )
    prepared = subject.prepare_managed_v5_live_run(public)
    authority = object.__new__(ManagedRuntimeCredentialAuthority)
    verified = object.__new__(VerifiedManagedLiveRunPreparation)
    route = object.__new__(ProviderRouteAttestation)
    limits = ManagedLiveExecutionLimits(
        provider_kind=MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        answerer_model="gpt-5.6-sol",
        judge_model="gpt-5.6-sol",
        max_cases=1,
        benchmark_max_provider_calls=4,
        readiness_probe_provider_calls=1,
        total_provider_attempt_ceiling=5,
        benchmark_reserved_token_ceiling=10000,
        readiness_probe_estimated_tokens=1,
        readiness_probe_usage_source="estimated_by_subscription_runtime",
        total_accounted_tokens=10001,
        token_accounting_publishable=False,
        post_reset_mem0_probe_attempt_ceiling=1,
        issued_at=datetime(2026, 8, 7, tzinfo=UTC),
        deadline=datetime(2026, 8, 8, 1, tzinfo=UTC),
    )
    plan = SimpleNamespace(run_id="run-1", provider_route=route)
    request = SimpleNamespace(
        provider_route=SimpleNamespace(origin="http://127.0.0.1:8891"),
        backend_endpoints=(
            SimpleNamespace(
                base_url="http://127.0.0.1:8080",
                target=SimpleNamespace(backend_role="infinity-context"),
            ),
        ),
    )
    material = SimpleNamespace(
        plan=object(),
        limits=limits,
        credential_authority=authority,
        readiness_claim=object(),
        preflight_request=request,
        mem0_runtime_port=object(),
    )
    monkeypatch.setattr(
        subject, "_consume_verified_managed_live_run_preparation", lambda *_, **__: material
    )
    monkeypatch.setattr(subject, "_inspect_verified_managed_run_plan", lambda _: plan)
    monkeypatch.setattr(
        subject,
        "create_managed_comparison_run_bindings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(subject, "_require_private_matches_public", lambda *_: None)
    events: list[str] = []

    class Subscription:
        close_count = 0

        def close(self) -> None:
            self.close_count += 1
            events.append("provider.close")

    subscription = Subscription()
    monkeypatch.setattr(
        ManagedRuntimeCredentialAuthority,
        "issue_subscription_execution_adapter",
        lambda self, **kwargs: subscription,
    )
    credential_error = ManagedRuntimeCredentialError("managed_credentials_configuration_invalid")
    activation_error = ManagedV5ProductionRunnerError("managed_v5_production_activation_failed")
    recovery_registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    recovery_error = ManagedV5ProductionRecoveryRequiredError(
        envelope=_recovery_envelope(recovery_registry)
    )

    def issue_credentials(self, **kwargs):
        if failure_at == "infinity_credentials":
            raise credential_error
        return object.__new__(ManagedV5InfinityCredentialBundle)

    def activate(*args, **kwargs):
        raise recovery_error if failure_at == "cleanup_required" else activation_error

    monkeypatch.setattr(
        ManagedRuntimeCredentialAuthority,
        "issue_managed_v5_infinity_credentials",
        issue_credentials,
    )
    monkeypatch.setattr(subject, "activate_managed_v5_production_runtime_with_factory", activate)
    private = subject.ManagedV5LivePrivateInputs(
        verified_preparation=verified,
        dependency_factory=_dependency_factory(),
        now=datetime(2026, 8, 8, tzinfo=UTC),
        wall_clock=lambda: datetime(2026, 8, 8, tzinfo=UTC),
        monotonic_clock=lambda: 100.0,
    )
    expected = (
        credential_error
        if failure_at == "infinity_credentials"
        else recovery_error
        if failure_at == "cleanup_required"
        else activation_error
    )

    with pytest.raises(type(expected)) as caught:
        subject.activate_managed_v5_live_run(prepared, private)

    assert caught.value is expected
    assert subscription.close_count == 1
    assert events == ["provider.close"]


@pytest.mark.parametrize("created", (False, True))
@pytest.mark.parametrize(
    "failure_at",
    ("none", "cleanup_receipt", "begin_cleanup", "finalize_unsealed_abort"),
)
def test_factory_activation_compensation_preserves_primary_or_recovery(
    monkeypatch,
    failure_at: str,
    created: bool,
) -> None:
    events: list[str] = []
    factory = _dependency_factory()
    registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    registration = _registration(created=created)
    dependencies = ManagedV5LivePrivateDependencyMaterial(
        budget_policy=object.__new__(ManagedMem0V5BudgetPolicy),
        clean_state_snapshot_factory=object.__new__(ManagedMem0V5HttpCleanStateSnapshotFactory),
        durable_clean_state_factory=object.__new__(ManagedMem0V5HmacDurableCleanStateFactory),
        operation_journal=object.__new__(ResumableOperationJournalService),
        operation_signer_key_id="test-signer",
        operation_policy_commitment_sha256="a" * 64,
        operation_receipt_authority=object.__new__(ManagedMem0V5OperationReceiptAuthority),
        mem0_credential_capabilities=object.__new__(ManagedMem0V5CredentialCapabilities),
        benchmark_registry=registry,
        benchmark_registration=registration,
        recovery_observer=object.__new__(ManagedV5LiveRecoveryObserver),
    )
    activated = SimpleNamespace(
        operation_manifest=SimpleNamespace(commitment_sha256="b" * 64, operations=(object(),)),
    )
    monkeypatch.setattr(runner, "_activate_managed_v5_public_run", lambda *_, **__: activated)
    monkeypatch.setattr(
        ManagedV5LivePrivateDependencyFactory,
        "create",
        lambda self, **kwargs: dependencies,
    )
    monkeypatch.setattr(runner, "OperationRunIdentity", lambda **_: object())
    primary = ManagedV5ProductionRunnerError("managed_v5_production_activation_failed")
    monkeypatch.setattr(
        runner,
        "create_managed_v5_production_runtime",
        lambda **_: (_ for _ in ()).throw(primary),
    )

    cleanup_receipt = _cleanup_receipt()
    receipt_state: list[ManagedBenchmarkCleanupReceipt] = []

    def begin_cleanup(self):
        events.append("registry.begin_cleanup")
        if failure_at == "begin_cleanup":
            raise RuntimeError("private registry failure")
        receipt_state.append(cleanup_receipt)
        return cleanup_receipt

    def finalize_abort(self, **kwargs):
        events.append("registry.finalize_unsealed_abort")
        assert kwargs == {"cleanup_initiation_receipt_sha256": "4" * 64}
        if failure_at == "finalize_unsealed_abort":
            raise RuntimeError("private registry failure")

    def current_cleanup_receipt(self):
        if failure_at == "cleanup_receipt":
            raise RuntimeError("private registry failure")
        return receipt_state[-1] if receipt_state else None

    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "cleanup_receipt",
        property(current_cleanup_receipt),
    )
    monkeypatch.setattr(ManagedBenchmarkRegistryHttpAdapter, "begin_cleanup", begin_cleanup)
    monkeypatch.setattr(
        ManagedBenchmarkRegistryHttpAdapter,
        "finalize_unsealed_abort",
        finalize_abort,
    )

    expected_type = (
        ManagedV5ProductionRunnerError
        if failure_at == "none"
        else ManagedV5ProductionRecoveryRequiredError
    )
    with pytest.raises(expected_type) as caught:
        runner.activate_managed_v5_production_runtime_with_factory(
            object.__new__(ManagedV5PublicRunPreparation),
            cases=(object(),),
            request=SimpleNamespace(run_id="run-1"),
            composition_binding=object(),
            receipt_authority=object(),
            production_authority=object(),
            plan=object(),
            run_bindings=object.__new__(FullComparisonRunBindings),
            now=datetime(2026, 8, 8, tzinfo=UTC),
            deadline=datetime(2026, 8, 8, 1, tzinfo=UTC),
            infinity_credentials=object.__new__(ManagedV5InfinityCredentialBundle),
            dependency_factory=factory,
            current_date="2026-08-08",
            mem0_origin="http://127.0.0.1:19091",
            timeout_seconds=5.0,
            state_paths=object(),
            credential_paths=object(),
            runtime_receipt_boundary=object(),
            trusted_runtime_binding=object(),
        )

    if failure_at == "none":
        assert caught.value is primary
    else:
        assert caught.value.recovery_registry is registry
        assert caught.value.registration is registration
        assert caught.value.cleanup_stage == (
            "begin_cleanup" if failure_at == "cleanup_receipt" else failure_at
        )
        assert caught.value.primary_code == primary.code
        assert caught.value.cleanup_receipt is (
            None if failure_at in {"cleanup_receipt", "begin_cleanup"} else cleanup_receipt
        )
    assert events == (
        []
        if failure_at == "cleanup_receipt"
        else ["registry.begin_cleanup"]
        if failure_at == "begin_cleanup"
        else ["registry.begin_cleanup", "registry.finalize_unsealed_abort"]
    )


def test_factory_registration_uncertainty_preserves_typed_recovery_authority(
    monkeypatch,
) -> None:
    factory = _dependency_factory()
    registry = object.__new__(ManagedBenchmarkRegistryHttpAdapter)
    envelope = ManagedV5RegistryRecoveryEnvelope(
        stage="registration_outcome_unknown",
        primary_reason_code=("managed_v5_live_private_dependencies_registration_failed"),
        run_id_sha256="1" * 64,
        binding_commitment_sha256="2" * 64,
        infinity_target_identity_sha256="3" * 64,
        space_slug="memory-comparison-run-1",
        recovery_registry=registry,
    )
    primary = ManagedV5LivePrivateDependencyError(
        "managed_v5_live_private_dependencies_registration_failed",
        recovery_envelope=envelope,
    )
    monkeypatch.setattr(
        runner,
        "_activate_managed_v5_public_run",
        lambda *_, **__: SimpleNamespace(),
    )
    monkeypatch.setattr(
        ManagedV5LivePrivateDependencyFactory,
        "create",
        lambda self, **kwargs: (_ for _ in ()).throw(primary),
    )

    with pytest.raises(ManagedV5ProductionRecoveryRequiredError) as caught:
        runner.activate_managed_v5_production_runtime_with_factory(
            object.__new__(ManagedV5PublicRunPreparation),
            cases=(object(),),
            request=SimpleNamespace(run_id="run-1"),
            composition_binding=object(),
            receipt_authority=object(),
            production_authority=object(),
            plan=object(),
            run_bindings=object.__new__(FullComparisonRunBindings),
            now=datetime(2026, 8, 8, tzinfo=UTC),
            deadline=datetime(2026, 8, 8, 1, tzinfo=UTC),
            infinity_credentials=object.__new__(ManagedV5InfinityCredentialBundle),
            dependency_factory=factory,
            current_date="2026-08-08",
            mem0_origin="http://127.0.0.1:19091",
            timeout_seconds=5.0,
            state_paths=object(),
            credential_paths=object(),
            runtime_receipt_boundary=object(),
            trusted_runtime_binding=object(),
        )

    assert caught.value.recovery_registry is registry
    assert caught.value.envelope is envelope
    assert caught.value.registration is None
    assert caught.value.cleanup_stage == "registration_outcome_unknown"
