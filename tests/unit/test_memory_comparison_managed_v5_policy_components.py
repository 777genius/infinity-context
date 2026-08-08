from __future__ import annotations

import hashlib
import threading
from datetime import timedelta

import pytest
from infinity_context_server import memory_comparison_managed_http_execution as legacy_execution
from infinity_context_server import memory_comparison_managed_policy_delegate_capability as cap
from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    binding_snapshot,
)
from infinity_context_server.memory_comparison_managed_http_policy_support import (
    ManagedHttpPolicyLifecycleError,
)
from infinity_context_server.memory_comparison_managed_infinity_http_execution import (
    ManagedInfinityHttpRuntimeConfig,
)
from infinity_context_server.memory_comparison_managed_infinity_http_lifecycle import (
    ManagedInfinityHttpIngestEvidence,
    ManagedInfinityHttpLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5IngestProjection,
    ManagedMem0V5IngestSnapshot,
    ManagedMem0V5ProductionLifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_ports import (
    ManagedV5CutoverIngestPort,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    ManagedMem0V5CorpusIngestEvidence,
    ManagedMem0V5CorpusUnitEvidence,
)
from infinity_context_server.memory_comparison_managed_v5_ingest_identity_projector import (
    ManagedV5IngestIdentityProjectionError,
    project_managed_infinity_v5_ingest_identities,
)
from infinity_context_server.memory_comparison_managed_v5_policy_lifecycle import (
    ManagedInfinityV5PolicyLifecycleAdapter,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import canonical_sha256
from test_memory_comparison_managed_ingest_manifest import _infinity_fact, _view
from test_memory_comparison_managed_mem0_v5_execution_evidence_adapter import _scenario
from test_memory_comparison_managed_mem0_v5_runner_foundation import _authority_and_case
from test_memory_comparison_managed_v5_cutover_components import _binding


def _projection(*, source_id: str, source_sha256: str) -> ManagedMem0V5IngestProjection:
    binding = _binding()
    _authority, case = _authority_and_case()
    unit = ManagedMem0V5CorpusUnitEvidence(
        hashlib.sha256(b"unit").hexdigest(),
        source_id,
        source_sha256,
        "2026-08-08",
        ("memory-1",),
        hashlib.sha256(b"storage").hexdigest(),
    )
    admission = hashlib.sha256(b"admission").hexdigest()
    corpus_target = canonical_sha256(
        {
            "admission_commitment_sha256": admission,
            "corpus_id": case.corpus_id,
        }
    )
    payload = {
        "run_id": binding.run_id,
        "target_identity_sha256": corpus_target,
        "corpus_id": case.corpus_id,
        "authority_commitment_sha256": "c" * 64,
        "seal_commitment_sha256": "d" * 64,
        "units": [unit.payload()],
    }
    evidence = ManagedMem0V5CorpusIngestEvidence(
        binding.run_id,
        corpus_target,
        case.corpus_id,
        "c" * 64,
        "d" * 64,
        (unit,),
        canonical_sha256(payload),
    )
    corpus = (hashlib.sha256(case.corpus_id.encode()).hexdigest(),)
    commitments = (evidence.evidence_commitment_sha256,)
    snapshot = ManagedMem0V5IngestSnapshot(
        corpus,
        commitments,
        1,
        canonical_sha256(
            {
                "ordered_corpus_id_sha256": corpus,
                "ordered_evidence_commitment_sha256": commitments,
                "receipt_count": 1,
            }
        ),
    )
    return ManagedMem0V5IngestProjection(snapshot, (evidence,), admission)


def test_pure_projector_pairs_exact_infinity_and_v5_sources() -> None:
    binding = _binding()
    _authority, case = _authority_and_case()
    view = _view(
        "infinity-context",
        _infinity_fact(),
        case_id=case.case_id,
        corpus_id=case.corpus_id,
        target="a" * 64,
    )
    infinity = ManagedInfinityHttpIngestEvidence(
        case.case_id,
        case.corpus_id,
        "a" * 64,
        view.ingest_result,
    )
    projected = project_managed_infinity_v5_ingest_identities(
        composition_binding=binding,
        cases=(case,),
        infinity_evidence=(infinity,),
        mem0_projection=_projection(source_id="source-1", source_sha256="a" * 64),
    )
    assert projected[0].manifest.mem0_created_memory_ids == ("memory-1",)
    assert projected[0].manifest.infinity_source_ids == ("source-1",)

    with pytest.raises(ManagedV5IngestIdentityProjectionError, match="source_pair_mismatch"):
        project_managed_infinity_v5_ingest_identities(
            composition_binding=binding,
            cases=(case,),
            infinity_evidence=(infinity,),
            mem0_projection=_projection(source_id="foreign-source", source_sha256="a" * 64),
        )

    tampered = _projection(source_id="source-1", source_sha256="a" * 64)
    object.__setattr__(tampered.evidence[0], "target_identity_sha256", "f" * 64)
    with pytest.raises(ManagedV5IngestIdentityProjectionError, match="binding_invalid"):
        project_managed_infinity_v5_ingest_identities(
            composition_binding=binding,
            cases=(case,),
            infinity_evidence=(infinity,),
            mem0_projection=tampered,
        )


def test_v5_policy_delegate_capability_is_nominal_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario()
    bindings = scenario.bindings
    case = scenario.cases[0]
    cases = (case,)
    delegate = object.__new__(ManagedInfinityV5PolicyLifecycleAdapter)
    monkeypatch.setattr(
        ManagedInfinityV5PolicyLifecycleAdapter,
        "_registry_delegate_composition_for_capability",
        lambda _self: (bindings, binding_snapshot(bindings), cases, "open"),
    )
    capability = cap._issue_managed_v5_policy_delegate_capability(
        delegate=delegate,
        bindings=bindings,
        cases=cases,
    )
    port, implementation = cap.consume_managed_policy_delegate_capability(
        capability,
        bindings=bindings,
        cases=cases,
    )
    assert cap.authenticate_managed_policy_delegate_port(port) == implementation
    with pytest.raises(cap.ManagedPolicyDelegateCapabilityError, match="replay"):
        cap.consume_managed_policy_delegate_capability(
            capability,
            bindings=bindings,
            cases=cases,
        )


def test_v5_policy_constructor_binds_exact_component_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario()
    infinity = object.__new__(ManagedInfinityHttpLifecycleAdapter)
    mem0 = object.__new__(ManagedMem0V5ProductionLifecycleAdapter)
    ingest = object.__new__(ManagedV5CutoverIngestPort)
    monkeypatch.setattr(
        ManagedInfinityHttpLifecycleAdapter,
        "composition_binding",
        property(lambda _self: scenario.binding),
    )
    monkeypatch.setattr(
        ManagedMem0V5ProductionLifecycleAdapter,
        "composition_binding",
        property(lambda _self: scenario.binding),
    )
    monkeypatch.setattr(
        ManagedV5CutoverIngestPort,
        "composition_binding",
        property(lambda _self: scenario.binding),
    )
    infinity_target = next(
        item.target_identity_sha256
        for item in scenario.binding.backend_targets
        if item.backend_role == "infinity-context"
    )
    config = object.__new__(ManagedInfinityHttpRuntimeConfig)
    monkeypatch.setattr(legacy_execution, "_validate_config", lambda **_values: None)
    for name, value in {
        "target_identity_sha256": infinity_target,
        "base_url": "http://127.0.0.1:8080",
        "auth_token": "test-token",
        "timeout_seconds": 60.0,
        "transport": None,
    }.items():
        monkeypatch.setattr(
            ManagedInfinityHttpRuntimeConfig,
            name,
            property(lambda _self, fixed=value: fixed),
        )
    adapter = ManagedInfinityV5PolicyLifecycleAdapter(
        bindings=scenario.bindings,
        cases=scenario.cases,
        composition_binding=scenario.binding,
        infinity_lifecycle=infinity,
        mem0_lifecycle=mem0,
        ingest_port=ingest,
        infinity_config=config,
        deadline=scenario.binding.deadline,
        clock=lambda: scenario.binding.deadline - timedelta(seconds=1),
    )
    capability = adapter.issue_registry_delegate_capability()
    port, _implementation = cap.consume_managed_policy_delegate_capability(
        capability,
        bindings=scenario.bindings,
        cases=scenario.cases,
    )
    assert cap.authenticate_managed_policy_delegate_port(port) == adapter.implementation_sha256


def _retry_adapter(scenario) -> ManagedInfinityV5PolicyLifecycleAdapter:
    adapter = object.__new__(ManagedInfinityV5PolicyLifecycleAdapter)
    adapter._bindings = scenario.bindings
    adapter._binding_snapshot = binding_snapshot(scenario.bindings)
    adapter._deadline = scenario.binding.deadline
    adapter._clock = lambda: scenario.binding.deadline - timedelta(seconds=1)
    adapter._lock = threading.RLock()
    adapter._delete_in_flight = None
    adapter._phase = "canonical-source-sealed"
    adapter._next_delete = 0
    adapter._issue_delete_receipt = lambda state: state
    return adapter


def test_v5_policy_retries_one_exact_transient_without_advancing() -> None:
    scenario = _scenario()
    adapter = _retry_adapter(scenario)
    calls = 0
    expected_receipt = object()

    def delete(_target: str, _pass_index: int) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider-secret")
        return expected_receipt

    adapter._delete_infinity = delete
    target = adapter._target("infinity-context")
    assert (
        adapter.terminal_delete(
            bindings=scenario.bindings,
            backend_role="infinity-context",
            target_identity_sha256=target,
            pass_index=1,
        )
        is expected_receipt
    )
    assert calls == 2
    assert adapter._next_delete == 1


def test_v5_policy_exhaustion_retains_operation_and_blocks_later_delegate() -> None:
    scenario = _scenario()
    adapter = _retry_adapter(scenario)
    calls = 0

    def fail(_target: str, _pass_index: int) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider-secret")

    adapter._delete_infinity = fail
    with pytest.raises(
        ManagedHttpPolicyLifecycleError,
        match="^managed_http_policy_infinity_context_delete_failed$",
    ):
        adapter.terminal_delete(
            bindings=scenario.bindings,
            backend_role="infinity-context",
            target_identity_sha256=adapter._target("infinity-context"),
            pass_index=1,
        )
    assert calls == 2
    assert adapter._phase == "cleanup-only"
    assert adapter._next_delete == 0

    with pytest.raises(ManagedHttpPolicyLifecycleError, match="delete_order_invalid"):
        adapter.terminal_delete(
            bindings=scenario.bindings,
            backend_role="mem0",
            target_identity_sha256=adapter._target("mem0"),
            pass_index=1,
        )
    assert calls == 2
