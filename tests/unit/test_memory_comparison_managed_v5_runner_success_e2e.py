from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta

import pytest
import test_memory_comparison_managed_v5_provider_free_e2e as support
from infinity_context_server import (
    memory_comparison_full_execution_evidence_variants as evidence_variants,
)
from infinity_context_server.memory_comparison_bounded_provider import (
    BoundedProviderBudget,
    BoundedProviderChatCompletions,
)
from infinity_context_server.memory_comparison_clean_state import (
    clean_state_identity_sha256,
    fresh_namespace_clean_state_proof,
)
from infinity_context_server.memory_comparison_full_execution_evidence_variants import (
    issue_infinity_di_full_execution_clean_state_evidence,
)
from infinity_context_server.memory_comparison_full_execution_validation import (
    FullExecutionCleanScope,
)
from infinity_context_server.memory_comparison_managed_live_admission import (
    MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
)
from infinity_context_server.memory_comparison_managed_live_composition import (
    ManagedLiveExecutionLimits,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_run import public_managed_run
from infinity_context_server.memory_comparison_managed_v5_extraction_budget import (
    ManagedV5ExtractionReservationUnit,
    ManagedV5ExtractionTokenBudget,
)
from infinity_context_server.memory_comparison_managed_v5_production_runner import (
    ManagedV5ProductionRunnerError,
    run_verified_managed_v5_production_execution,
)
from test_memory_comparison_managed_attestation import _runtime_validation
from test_memory_comparison_managed_llm_execution import _Delegate
from test_memory_comparison_managed_v5_provider_free_e2e import _fixture

_PROBE_NONCE = "managed-v5-runner-success-e2e-probe"


@pytest.fixture(autouse=True)
def _hermetic_phase_c(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    support.install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=support.PHASE_C_ROOT,
    )
    monkeypatch.setattr(
        support.composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_values: None,
    )


class _AttestationPort:
    adapter_id = "managed-v5-runner-success-attestation-v1"
    implementation_sha256 = "9" * 64

    def __init__(self, bindings: object, validation: object) -> None:
        self.bindings = bindings
        self.validation = validation
        self.calls = 0

    def attest(
        self, *, run_id: str, probe_nonce_sha256: str, target_identity_sha256: str
    ) -> object:
        self.calls += 1
        assert run_id == self.bindings.run_id
        assert probe_nonce_sha256 == self.bindings.runtime_probe_nonce_sha256
        assert target_identity_sha256 == next(
            target.target_identity_sha256
            for target in self.bindings.backend_targets
            if target.backend_role == "mem0"
        )
        return self.validation


def test_multicorpus_infinity_clean_evidence_has_one_resource_per_token() -> None:
    key = b"managed-v5-runner-multicorpus-key"
    run_id = "managed-v5-runner-multicorpus"
    corpus_ids = ("corpus-a", "corpus-b")
    slugs = ("fresh-infinity-a", "fresh-infinity-b")
    corpus_hashes = tuple(clean_state_identity_sha256(item) for item in corpus_ids)
    scope_hashes = tuple(clean_state_identity_sha256(item) for item in slugs)
    scopes = tuple(
        FullExecutionCleanScope("infinity-context", corpus_hash, scope_hash)
        for corpus_hash, scope_hash in zip(corpus_hashes, scope_hashes, strict=True)
    )
    proofs = tuple(
        fresh_namespace_clean_state_proof(
            backend="infinity-context",
            run_id=run_id,
            expected_slug=slug,
            corpus_identity_sha256=corpus_hash,
            expected_scope_count=len(scopes),
            status_code=201,
            payload={"data": {"slug": slug}},
            attestation_key=key,
        )
        for slug, corpus_hash in zip(slugs, corpus_hashes, strict=True)
    )
    evidence = issue_infinity_di_full_execution_clean_state_evidence(
        corpus_ids=corpus_ids,
        proofs=proofs,
        scopes=scopes,
        attestation_key=key,
    )

    inspection = evidence_variants._inspect_full_execution_clean_state_evidence_for_validation(
        evidence
    )

    assert len(inspection.resource_tokens) == len(inspection.resources) == 7
    assert inspection.resources == (*proofs, *scopes, *corpus_ids, key)


def test_runner_executes_provider_free_v5_success_path_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    run_now = datetime.now(UTC)
    monkeypatch.setattr(support, "_NOW", run_now)
    monkeypatch.setattr(support, "_DEADLINE", run_now + timedelta(seconds=60))
    original_builder = support.build_verified_managed_run_plan
    probe_sha = hashlib.sha256(_PROBE_NONCE.encode()).hexdigest()
    monkeypatch.setattr(
        support,
        "build_verified_managed_run_plan",
        lambda **kwargs: original_builder(**{**kwargs, "runtime_probe_nonce_sha256": probe_sha}),
    )
    dispatch_batches = 0
    original_dispatch = ManagedMem0V5ProductionLifecycleAdapter.dispatch_once

    def count_dispatch(self: ManagedMem0V5ProductionLifecycleAdapter):
        nonlocal dispatch_batches
        dispatch_batches += 1
        return original_dispatch(self)

    monkeypatch.setattr(ManagedMem0V5ProductionLifecycleAdapter, "dispatch_once", count_dispatch)
    runtime, plan, infinity_events, registry_events, mem0 = _fixture(monkeypatch, tmp_path)
    route = plan.provider_route
    delegate = _Delegate(route)
    close_calls = 0

    def close_delegate() -> None:
        nonlocal close_calls
        close_calls += 1

    delegate.close = close_delegate
    provider = BoundedProviderChatCompletions(
        delegate=delegate,
        budget=BoundedProviderBudget(
            max_total_tokens=100_000,
            deadline_monotonic=time.monotonic() + 120,
            max_calls=len(plan.cases) * 4,
            max_output_tokens_per_call=4096,
        ),
        input_token_estimator=lambda _text: 1,
    )
    limits = ManagedLiveExecutionLimits(
        MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        "gpt-5.6-sol",
        "gpt-5.6-sol",
        len(plan.cases),
        len(plan.cases) * 4,
        1,
        len(plan.cases) * 4 + 1,
        100_000,
        1,
        "estimated_by_subscription_runtime",
        100_001,
        False,
        1,
        run_now,
        runtime.composition_binding.deadline,
    )
    mem0_target = next(
        target.target_identity_sha256
        for target in runtime._bindings.backend_targets
        if target.backend_role == "mem0"
    )
    attestation = _AttestationPort(
        runtime._bindings,
        _runtime_validation(
            run_id=runtime._bindings.run_id,
            nonce=_PROBE_NONCE,
            target=mem0_target,
            managed_live_max_age_seconds=900,
        ),
    )

    outcome = run_verified_managed_v5_production_execution(
        runtime,
        provider=provider,
        limits=limits,
        provider_route=route,
        attestation_port=attestation,
        clock=lambda: run_now,
    )
    trace = public_managed_run(outcome)["managed_run"]["trace"]
    case_count = len(plan.cases)

    assert trace.count("reset.complete") == trace.count("attestation.live") == 1
    assert trace.count("canonical_source.seal") == 1
    assert trace.count("ingest:infinity-context") == case_count
    assert trace.count("ingest:mem0") == case_count
    assert trace.index("ingest:mem0") > max(
        i for i, event in enumerate(trace) if event == "ingest:infinity-context"
    )
    assert dispatch_batches == 1
    assert mem0.paths.count("/v5/operations/dispatch") == case_count
    assert trace.count("retrieve:infinity-context") == case_count
    assert trace.count("retrieve:mem0") == case_count
    assert infinity_events.count("/v1/context/benchmark-search") == case_count
    assert mem0.paths.count("/v5/runs/search") == case_count
    assert trace.count("answer:infinity-context") == case_count
    assert trace.count("answer:mem0") == case_count
    assert trace.count("judge:infinity-context") == case_count
    assert trace.count("judge:mem0") == case_count
    assert len(delegate.calls) == case_count * 4
    assert [event for event in trace if event.startswith("delete:")] == [
        "delete:infinity-context:1",
        "delete:mem0:1",
        "delete:infinity-context:2",
        "delete:mem0:2",
    ]
    assert runtime.policy_port.terminal_completion_receipt.state == "cleanup_complete"
    assert registry_events.index("registry.finalize") < registry_events.index(
        "recovery.canonical-terminal"
    )
    assert attestation.calls == 1
    assert runtime.owned_resources.closed is True
    assert close_calls == 1
    runtime.owned_resources.close()
    assert close_calls == 1


@pytest.mark.parametrize("verifier_raises", (False, True))
def test_terminal_observed_verification_is_normalized_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    verifier_raises: bool,
) -> None:
    run_now = datetime.now(UTC)
    monkeypatch.setattr(support, "_RUN_ID", "managed-v5-provider-free-over-cap")
    monkeypatch.setattr(support, "_NOW", run_now)
    monkeypatch.setattr(support, "_DEADLINE", run_now + timedelta(seconds=60))
    original_builder = support.build_verified_managed_run_plan
    probe_sha = hashlib.sha256(_PROBE_NONCE.encode()).hexdigest()
    monkeypatch.setattr(
        support,
        "build_verified_managed_run_plan",
        lambda **kwargs: original_builder(**{**kwargs, "runtime_probe_nonce_sha256": probe_sha}),
    )
    units = tuple(ManagedV5ExtractionReservationUnit(1, 1) for _ in range(2))
    token_budget = ManagedV5ExtractionTokenBudget.reserve(
        units,
        operator_extraction_token_ceiling=4,
        operator_total_token_ceiling=100_000,
    )
    runtime, plan, _infinity_events, registry_events, mem0 = _fixture(
        monkeypatch,
        tmp_path,
        budget_policy=ManagedMem0V5BudgetPolicy(100, token_budget),
    )
    route = plan.provider_route
    provider = BoundedProviderChatCompletions(
        delegate=_Delegate(route),
        budget=BoundedProviderBudget(
            max_total_tokens=100_000,
            deadline_monotonic=time.monotonic() + 120,
            max_calls=len(plan.cases) * 4,
            max_output_tokens_per_call=4096,
        ),
        input_token_estimator=lambda _text: 1,
    )
    limits = ManagedLiveExecutionLimits(
        MANAGED_PROVIDER_SUBSCRIPTION_RUNTIME,
        "gpt-5.6-sol",
        "gpt-5.6-sol",
        len(plan.cases),
        len(plan.cases) * 4,
        1,
        len(plan.cases) * 4 + 1,
        100_000,
        1,
        "estimated_by_subscription_runtime",
        100_001,
        False,
        1,
        run_now,
        runtime.composition_binding.deadline,
    )
    mem0_target = next(
        target.target_identity_sha256
        for target in runtime._bindings.backend_targets
        if target.backend_role == "mem0"
    )
    attestation = _AttestationPort(
        runtime._bindings,
        _runtime_validation(
            run_id=runtime._bindings.run_id,
            nonce=_PROBE_NONCE,
            target=mem0_target,
            managed_live_max_age_seconds=900,
        ),
    )
    if verifier_raises:
        monkeypatch.setattr(
            type(runtime.observed_extraction_verifier),
            "verify",
            lambda self: (_ for _ in ()).throw(RuntimeError("PRIVATE verifier failure")),
        )
    with pytest.raises(ManagedV5ProductionRunnerError) as caught:
        run_verified_managed_v5_production_execution(
            runtime,
            provider=provider,
            limits=limits,
            provider_route=route,
            attestation_port=attestation,
            clock=lambda: run_now,
        )
    assert mem0.errors == []
    assert runtime.policy_port.terminal_completion_receipt.state == "cleanup_complete"
    assert registry_events.index("registry.finalize") < registry_events.index(
        "recovery.canonical-terminal"
    )
    assert caught.value.code == (
        "managed_v5_production_execution_failed"
        if verifier_raises
        else "managed_v5_extraction_observed_token_ceiling_exceeded"
    )
    assert runtime.owned_resources.closed is True
    if not verifier_raises:
        for _ in range(2):
            assert (
                runtime.observed_extraction_verifier.verify()
                == "managed_v5_extraction_observed_token_ceiling_exceeded"
            )
