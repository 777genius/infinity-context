from __future__ import annotations

import copy
import hashlib
import pickle
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from _phase_c_hermetic import install_hermetic_phase_c_authority
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_composition as composition_subject,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_lifecycle_adapter as lifecycle_subject,
)
from infinity_context_server import (
    memory_comparison_managed_mem0_v5_production_authority as authority_subject,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_clean_state_http import (
    ManagedMem0V5HmacDurableCleanStateFactory,
    ManagedMem0V5HttpCleanStateSnapshotFactory,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_composition import (
    compose_managed_mem0_v5,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_execution_evidence_adapter import (
    ManagedMem0V5ExecutionEvidenceAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5BudgetPolicy,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lifecycle_adapter import (
    ManagedMem0V5LifecycleAdapter,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_paired_bridge import (
    ManagedMem0V5PairedRun,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_authority import (
    ManagedMem0V5ProductionAuthorityError,
    _consume_managed_mem0_v5_production_authority,
    inspect_managed_mem0_v5_production_authority,
    issue_managed_mem0_v5_production_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_production_lifecycle import (
    ManagedMem0V5IngestSnapshot,
    ManagedMem0V5ProductionLifecycleAdapter,
    ManagedMem0V5ProductionLifecycleError,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_run_evidence import (
    create_managed_mem0_v5_clean_state_witness_authority,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_transport_evidence import (
    issue_managed_transport_coverage_capability,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    Mem0OssFullRunAdmission,
    canonical_sha256,
)
from infinity_context_server.resumable_operation_journal.crypto import (
    HmacSha256OperationJournalSigner,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationManifest,
    OperationRunIdentity,
    VerifiedOperationReceipt,
)
from infinity_context_server.resumable_operation_journal.service import (
    AllowAllOperationManifestPolicy,
    NullOperationNotification,
    ResumableOperationJournalService,
)
from infinity_context_server.resumable_operation_journal.sqlite import SQLiteOperationJournal
from test_memory_comparison_managed_mem0_v5_composition import (
    PHASE_C_ROOT,
    _observed_authority,
)
from test_memory_comparison_managed_mem0_v5_composition import (
    _inputs as _composition_inputs,
)
from test_memory_comparison_managed_mem0_v5_execution_evidence_adapter import (
    _infinity_claim,
    _scenario,
)
from test_memory_comparison_managed_mem0_v5_paired_bridge import (
    _Coordinator,
    _expected_clean_scopes,
)
from test_memory_comparison_managed_mem0_v5_runner_foundation import (
    _binding,
    _exact_transport_observations,
    _set_storage_operation,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(autouse=True)
def _hermetic_phase_c(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_hermetic_phase_c_authority(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        phase_c_root=PHASE_C_ROOT,
    )
    monkeypatch.setattr(
        composition_subject,
        "require_mem0_v5_observed_extraction_receipt_boundary",
        lambda **_values: None,
    )


def _public_inputs(tmp_path) -> tuple[dict[str, object], object]:
    compose_values, _secrets = _composition_inputs(tmp_path)
    observed = _observed_authority(compose_values)
    compose_values["receipt_authority"] = observed
    request = compose_values["request"]
    binding = _binding(run_id=request.run_id)
    authority = ManagedMem0V5ManifestProjector().project(
        compose_values["cases"], current_date=compose_values["current_date"]
    )
    manifest = OperationManifest(
        tuple(
            LogicalOperationIdentity(
                run_id=request.run_id,
                operation_key=item.operation_id_sha256,
                operation_kind="managed_mem0_v5_extraction",
                ordinal=index,
                authority_commitment_sha256=authority.authority_commitment_sha256,
            )
            for index, item in enumerate(observed.operations)
        )
    )
    values = {
        **compose_values,
        "composition_binding": binding,
        "operation_manifest": manifest,
    }
    return values, SimpleNamespace(binding=binding, cases=compose_values["cases"])


def _compose(values: dict[str, object]):
    keys = {
        "cases",
        "current_date",
        "request",
        "origin",
        "timeout_seconds",
        "state_paths",
        "credential_paths",
        "runtime_receipt_boundary",
        "trusted_runtime_binding",
        "receipt_authority",
        "dispatch_guard",
        "transport",
    }
    return compose_managed_mem0_v5(**{key: value for key, value in values.items() if key in keys})


def _consume_values(values: dict[str, object], composition: object) -> dict[str, object]:
    return {
        "composition": composition,
        "composition_binding": values["composition_binding"],
        "origin": values["origin"],
        "receipt_authority": values["receipt_authority"],
        "operation_manifest": values["operation_manifest"],
    }


class _ReceiptVerifier:
    def verify(self, *, identity: object, receipt: object) -> VerifiedOperationReceipt:
        del identity
        return VerifiedOperationReceipt(
            receipt=receipt,
            verifier_key_id="production-test-verifier",
            verification_commitment_sha256=_sha("verified-receipt"),
        )


def _journal_inputs(
    tmp_path: object,
    *,
    values: dict[str, object],
    production_authority: object,
) -> dict[str, object]:
    signer = HmacSha256OperationJournalSigner(
        key_id="production-test-signer",
        secret=b"production-foundation-test-secret-32",
    )
    descriptor = inspect_managed_mem0_v5_production_authority(production_authority)
    manifest = values["operation_manifest"]
    identity = OperationRunIdentity(
        run_id=values["composition_binding"].run_id,
        operation_namespace="managed_mem0_v5_production",
        manifest_commitment_sha256=manifest.commitment_sha256,
        policy_commitment_sha256=descriptor.authority_commitment_sha256,
        signer_key_id=signer.key_id,
        expected_operation_count=len(manifest.operations),
    )
    private = tmp_path / "operation-journal"
    service = ResumableOperationJournalService(
        journal=SQLiteOperationJournal(
            private / "operations.sqlite3",
            private_directory=private,
        ),
        signer=signer,
        manifest_policy=AllowAllOperationManifestPolicy(),
        receipt_verifier=_ReceiptVerifier(),
        notifications=NullOperationNotification(),
    )
    return {
        "operation_journal": service,
        "operation_run_identity": identity,
    }


def _production_fixture(tmp_path):
    values, fixture = _public_inputs(tmp_path)
    composition = _compose(values)
    authority = composition.authority
    binding = fixture.binding
    bundle = composition.issue_paired_runtime(
        budget_policy=ManagedMem0V5BudgetPolicy(10_000),
        clean_state_snapshot_factory=ManagedMem0V5HttpCleanStateSnapshotFactory(),
        durable_clean_state_factory=ManagedMem0V5HmacDurableCleanStateFactory(
            path=tmp_path / "production-clean-state.json",
            hmac_key_capability=_Capability(b"production-clean-state-hmac-key-value!!"),
        ),
    )
    paired_run = bundle.paired_run
    coordinator = composition.coordinator
    lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=binding,
        paired_run=paired_run,
        authority=authority,
        request=composition.request,
        cleanup_readback_capability=bundle.cleanup_readback_capability,
    )
    execution_evidence = ManagedMem0V5ExecutionEvidenceAdapter(
        composition_binding=binding,
        lifecycle=lifecycle,
        infinity_clean_state_evidence=_infinity_claim(
            run_id=binding.run_id,
            corpus_id=authority.units[0].corpus_id,
        ),
    )
    production_authority = issue_managed_mem0_v5_production_authority(**values)
    journal_values = _journal_inputs(
        tmp_path,
        values=values,
        production_authority=production_authority,
    )
    constructor_values = {
        "production_authority": production_authority,
        "composition": composition,
        "paired_runtime_bundle": bundle,
        "lifecycle": lifecycle,
        "execution_evidence": execution_evidence,
        **journal_values,
        **{
            key: value
            for key, value in _consume_values(values, composition).items()
            if key != "composition"
        },
    }
    return (
        lifecycle,
        binding,
        authority,
        coordinator,
        values,
        journal_values,
        constructor_values,
    )


def _new_production(tmp_path):
    (
        lifecycle,
        binding,
        authority,
        coordinator,
        values,
        journal_values,
        constructor_values,
    ) = _production_fixture(tmp_path)
    production = ManagedMem0V5ProductionLifecycleAdapter(**constructor_values)
    return (
        production,
        lifecycle,
        binding,
        authority,
        coordinator,
        values,
        journal_values,
        constructor_values,
    )


class _Capability:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def validate(self) -> None:
        assert 32 <= len(self.value) <= 4_096

    def consume(self) -> bytes:
        return self.value


def _provider_free_paired_run(authority: object, request: object):
    coordinator = _Coordinator(authority, request)
    issuer, verifier = create_managed_mem0_v5_clean_state_witness_authority()
    scopes = _expected_clean_scopes(
        authority=authority,
        admission_commitment_sha256=coordinator.admission,
    )

    class CleanState:
        def prove_empty_scopes(self, **proof_values: object):
            return issuer.issue_authenticated_clean_state(
                admission_commitment_sha256=proof_values["expected_admission_commitment_sha256"],
                run_id_sha256=proof_values["expected_run_id_sha256"],
                authority_commitment_sha256=proof_values["expected_authority_commitment_sha256"],
                scopes=proof_values["expected_scopes"],
            )

    class Durable:
        witness = issuer.issue_authenticated_clean_state(
            admission_commitment_sha256=coordinator.admission,
            run_id_sha256=_sha(request.run_id),
            authority_commitment_sha256=authority.authority_commitment_sha256,
            scopes=scopes,
        )

        def save_original(self, witness: object) -> None:
            self.witness = witness

        def load_original(self, **_values: object):
            return self.witness

    paired_run = ManagedMem0V5PairedRun(
        authority=authority,
        request=request,
        budget_policy=ManagedMem0V5BudgetPolicy(10_000),
        coordinator=coordinator,
        clean_state_snapshot_port=CleanState(),
        clean_state_verifier=verifier,
        durable_clean_state_port=Durable(),
        storage_witness_verifier=coordinator.storage_verifier,
    )
    return coordinator, paired_run


def test_authority_is_secret_free_redacted_and_bound_to_exact_public_tuple(tmp_path) -> None:
    values, scenario = _public_inputs(tmp_path)
    authority = issue_managed_mem0_v5_production_authority(**values)
    descriptor = inspect_managed_mem0_v5_production_authority(authority)

    assert descriptor.run_id_sha256 == _sha(scenario.binding.run_id)
    assert descriptor.binding_commitment_sha256 == scenario.binding.binding_commitment_sha256
    assert descriptor.origin_sha256 == _sha(values["origin"])
    assert descriptor.operation_count == len(values["operation_manifest"].operations)
    assert descriptor.authority_commitment_sha256 == canonical_sha256(
        {
            name: getattr(descriptor, name)
            for name in descriptor.__dataclass_fields__
            if name != "authority_commitment_sha256"
        }
    )
    assert "127.0.0.1" not in repr(authority)
    assert scenario.binding.run_id not in repr(authority)

    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(authority)


def test_authority_consumes_once_atomically_under_contention(tmp_path) -> None:
    values, _ = _public_inputs(tmp_path)
    authority = issue_managed_mem0_v5_production_authority(**values)
    consume_values = _consume_values(values, _compose(values))

    def consume() -> str:
        try:
            descriptor = _consume_managed_mem0_v5_production_authority(authority, **consume_values)
            return descriptor.authority_commitment_sha256
        except ManagedMem0V5ProductionAuthorityError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _: consume(), range(8)))

    descriptor = inspect_managed_mem0_v5_production_authority(authority)
    assert results.count(descriptor.authority_commitment_sha256) == 1
    assert results.count("managed_mem0_v5_production_authority_consume_invalid") == 7


def test_authority_rejects_operation_phase_c_origin_and_object_drift(tmp_path) -> None:
    values, _ = _public_inputs(tmp_path)
    observed = values["receipt_authority"]
    manifest = values["operation_manifest"]
    operation = manifest.operations[0]
    drifted_manifest = OperationManifest(
        (
            LogicalOperationIdentity(
                operation.run_id,
                _sha("different-operation"),
                operation.operation_kind,
                operation.ordinal,
                operation.authority_commitment_sha256,
            ),
        )
    )
    with pytest.raises(ManagedMem0V5ProductionAuthorityError, match="input_invalid"):
        issue_managed_mem0_v5_production_authority(
            **{**values, "operation_manifest": drifted_manifest}
        )
    with pytest.raises(ManagedMem0V5ProductionAuthorityError, match="preflight_invalid"):
        issue_managed_mem0_v5_production_authority(
            **{
                **values,
                "receipt_authority": replace(observed, runtime_source_sha256=_sha("drift")),
            }
        )
    with pytest.raises(ManagedMem0V5ProductionAuthorityError, match="preflight_invalid"):
        issue_managed_mem0_v5_production_authority(**{**values, "origin": "https://example.com"})

    authority = issue_managed_mem0_v5_production_authority(**values)
    composition = _compose(values)
    equal_manifest = OperationManifest(manifest.operations)
    with pytest.raises(ManagedMem0V5ProductionAuthorityError, match="consume_invalid"):
        _consume_managed_mem0_v5_production_authority(
            authority,
            **{
                **_consume_values(values, composition),
                "operation_manifest": equal_manifest,
            },
        )

    cross_root = tmp_path / "cross-wire"
    cross_root.mkdir()
    second_values, _ = _public_inputs(cross_root)
    cross_authority = issue_managed_mem0_v5_production_authority(**second_values)
    cross_composition = _compose({**second_values, "origin": "http://127.0.0.1:9999"})
    with pytest.raises(ManagedMem0V5ProductionAuthorityError, match="consume_invalid"):
        _consume_managed_mem0_v5_production_authority(
            cross_authority,
            **_consume_values(second_values, cross_composition),
        )


def test_authority_accepts_equivalent_trailing_slash_origin(tmp_path) -> None:
    values, _ = _public_inputs(tmp_path)
    slash_values = {**values, "origin": f"{values['origin']}/"}
    production_authority = issue_managed_mem0_v5_production_authority(**slash_values)
    descriptor = _consume_managed_mem0_v5_production_authority(
        production_authority,
        **_consume_values(slash_values, _compose(values)),
    )
    assert descriptor.origin_sha256 == _sha(values["origin"])


def test_authority_hmac_snapshot_rejects_private_state_tamper(tmp_path) -> None:
    values, _ = _public_inputs(tmp_path)
    authority = issue_managed_mem0_v5_production_authority(**values)
    state = authority_subject._STATES[authority]
    authority_subject._STATES[authority] = replace(state, consumed=True)

    with pytest.raises(ManagedMem0V5ProductionAuthorityError, match="authority_invalid"):
        inspect_managed_mem0_v5_production_authority(authority)


def test_production_lifecycle_consumes_authority_and_blocks_out_of_order_calls(
    tmp_path,
) -> None:
    adapter, _lifecycle, binding, _authority, _coordinator, values, _journal, _constructor = (
        _new_production(tmp_path)
    )

    assert adapter.composition_binding is binding
    assert "redacted" in repr(adapter)
    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="dispatch_invalid"):
        adapter.dispatch_once()
    with pytest.raises(
        ManagedMem0V5ProductionLifecycleError,
        match="execution_evidence_invalid",
    ):
        adapter.consume_ready_execution_evidence(
            composition_binding=binding,
            bindings=object(),
            cases=values["cases"],
        )


def test_production_rejects_crosswired_lifecycle_not_issued_by_composition(tmp_path) -> None:
    (
        _lifecycle,
        binding,
        authority,
        _coordinator,
        values,
        journal_values,
        constructor_values,
    ) = _production_fixture(tmp_path)
    _cross_coordinator, cross_run = _provider_free_paired_run(authority, values["request"])
    cross_lifecycle = ManagedMem0V5LifecycleAdapter(
        composition_binding=binding,
        paired_run=cross_run,
        authority=authority,
        request=values["request"],
        cleanup_readback_capability=SimpleNamespace(readback=lambda **items: items),
    )
    cross_evidence = ManagedMem0V5ExecutionEvidenceAdapter(
        composition_binding=binding,
        lifecycle=cross_lifecycle,
        infinity_clean_state_evidence=_infinity_claim(
            run_id=binding.run_id,
            corpus_id=authority.units[0].corpus_id,
        ),
    )
    with pytest.raises(ManagedMem0V5ProductionLifecycleError) as failed:
        ManagedMem0V5ProductionLifecycleAdapter(
            **{
                **constructor_values,
                **journal_values,
                "lifecycle": cross_lifecycle,
                "execution_evidence": cross_evidence,
            }
        )
    assert failed.value.code == "managed_mem0_v5_production_lifecycle_composition_invalid"


def test_journal_initialize_failure_does_not_consume_authority(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    *_, constructor_values = _production_fixture(tmp_path)
    journal = constructor_values["operation_journal"]
    real_initialize = journal.initialize
    failures = 1

    def fail_after_initialize(*args: object, **kwargs: object):
        nonlocal failures
        result = real_initialize(*args, **kwargs)
        if failures:
            failures -= 1
            raise RuntimeError("journal-init-secret")
        return result

    monkeypatch.setattr(journal, "initialize", fail_after_initialize)
    with pytest.raises(ManagedMem0V5ProductionLifecycleError) as failed:
        ManagedMem0V5ProductionLifecycleAdapter(**constructor_values)
    assert failed.value.code == "managed_mem0_v5_production_lifecycle_journal_initialize_failed"

    recovered = ManagedMem0V5ProductionLifecycleAdapter(**constructor_values)
    assert recovered.composition_binding is constructor_values["composition_binding"]


def test_production_lifecycle_retries_journal_before_atomic_ingest_consume(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        production,
        lifecycle,
        binding,
        authority,
        _coordinator,
        values,
        journal_values,
        _constructor,
    ) = _new_production(tmp_path)
    corpus_ids = tuple(dict.fromkeys(item.corpus_id for item in authority.units))
    admission = Mem0OssFullRunAdmission(
        request=values["request"],
        ingestion_manifest_sha256=authority.ingestion_manifest_sha256,
        ingestion_root_sha256=authority.ingestion_root_sha256,
        ingestion_unit_count=authority.operation_count,
    )
    observations = _exact_transport_observations(authority, admission)
    reference_coordinator, reference_run = _provider_free_paired_run(authority, values["request"])
    _set_storage_operation(
        authority,
        reference_coordinator,
        observations[0].operation_id_sha256,
    )
    reference_run.admit()
    actual_run = lifecycle_subject._STATES[lifecycle].paired_run
    original_dispatch = ManagedMem0V5PairedRun.dispatch
    original_coverage = ManagedMem0V5PairedRun.consume_transport_coverage
    original_evidence = ManagedMem0V5PairedRun.corpus_ingest_evidence

    def dispatch(run: ManagedMem0V5PairedRun):
        return reference_run.dispatch() if run is actual_run else original_dispatch(run)

    def coverage(run: ManagedMem0V5PairedRun, capability: object):
        return (
            reference_run.consume_transport_coverage(capability)
            if run is actual_run
            else original_coverage(run, capability)
        )

    def corpus_evidence(run: ManagedMem0V5PairedRun, *, corpus_id: str):
        return (
            reference_run.corpus_ingest_evidence(corpus_id=corpus_id)
            if run is actual_run
            else original_evidence(run, corpus_id=corpus_id)
        )

    monkeypatch.setattr(ManagedMem0V5PairedRun, "dispatch", dispatch)
    monkeypatch.setattr(
        ManagedMem0V5PairedRun,
        "consume_transport_coverage",
        coverage,
    )
    monkeypatch.setattr(
        ManagedMem0V5PairedRun,
        "corpus_ingest_evidence",
        corpus_evidence,
    )
    production.admit_or_restore()
    production.dispatch_once()
    capability = issue_managed_transport_coverage_capability(
        benchmark=binding.profile.benchmark,
        run_id_sha256=_sha(binding.run_id),
        backend_role="mem0",
        authority=authority,
        admission=admission,
        observations=observations,
    )
    production.consume_transport_coverage(capability)
    receipts = tuple(
        production.issue_corpus_receipt(corpus_id=corpus_id) for corpus_id in corpus_ids
    )
    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="receipt_consume_invalid"):
        production.consume_exact_receipts(tuple(reversed(receipts)) + receipts[:1])
    journal = journal_values["operation_journal"]
    real_commit = journal.commit
    failures = 1

    def fail_once(*args: object, **kwargs: object):
        nonlocal failures
        if failures:
            failures -= 1
            raise RuntimeError("journal-storage-secret")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(journal, "commit", fail_once)
    with pytest.raises(ManagedMem0V5ProductionLifecycleError) as failed:
        production.consume_exact_receipts(receipts)
    assert failed.value.code == "managed_mem0_v5_production_lifecycle_receipt_consume_failed"
    assert not lifecycle_subject._STATES[lifecycle].receipts_consumed

    snapshot = production.consume_exact_receipts(receipts)

    assert type(snapshot) is ManagedMem0V5IngestSnapshot
    assert snapshot.receipt_count == len(corpus_ids)
    assert len(snapshot.ordered_evidence_commitment_sha256) == len(corpus_ids)
    assert journal.snapshot(binding.run_id).committed_count == len(authority.units)
    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="receipt_consume_invalid"):
        production.consume_exact_receipts(receipts)


def test_authenticated_receipt_preview_is_retryable_before_atomic_consume() -> None:
    scenario = _scenario(consume_receipts=False)
    state = lifecycle_subject._STATES[scenario.lifecycle]
    first = scenario.lifecycle._authenticate_corpus_receipts_for_production(
        composition_binding=scenario.binding,
        receipts=state.receipts,
    )
    second = scenario.lifecycle._authenticate_corpus_receipts_for_production(
        composition_binding=scenario.binding,
        receipts=state.receipts,
    )
    assert tuple(item.evidence_commitment_sha256 for item in first) == tuple(
        item.evidence_commitment_sha256 for item in second
    )
    assert scenario.lifecycle.consume_corpus_receipts(state.receipts) == first


def test_dispatch_ambiguity_is_safe_and_never_redispatches(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production, _lifecycle, _binding, _authority, _coordinator, _values, _journal, _constructor = (
        _new_production(tmp_path)
    )
    calls = 0

    def fail_dispatch(_self: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider-secret-must-not-leak")

    monkeypatch.setattr(ManagedMem0V5LifecycleAdapter, "dispatch_once", fail_dispatch)
    production.admit_or_restore()
    with pytest.raises(ManagedMem0V5ProductionLifecycleError) as first:
        production.dispatch_once()
    with pytest.raises(ManagedMem0V5ProductionLifecycleError, match="dispatch_replay_blocked"):
        production.dispatch_once()

    rendered = "".join(traceback.format_exception(first.value))
    assert first.value.code == "managed_mem0_v5_production_lifecycle_dispatch_failed"
    assert first.value.__suppress_context__
    assert "provider-secret-must-not-leak" not in rendered
    assert calls == 1

    terminal = object()
    monkeypatch.setattr(
        ManagedMem0V5LifecycleAdapter,
        "terminalize",
        lambda _self, *, pass_two_request=None: terminal,
    )
    assert production.terminalize() is terminal


def test_terminalize_retries_through_lifecycle_owner(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production, _lifecycle, _binding, _authority, _coordinator, _values, _journal, _constructor = (
        _new_production(tmp_path)
    )
    terminal = object()
    calls = 0

    def terminalize(_self: object, *, pass_two_request: object | None = None) -> object:
        nonlocal calls
        del pass_two_request
        calls += 1
        if calls == 1:
            raise RuntimeError("cleanup-provider-secret")
        return terminal

    monkeypatch.setattr(ManagedMem0V5LifecycleAdapter, "terminalize", terminalize)
    production.admit_or_restore()
    with pytest.raises(ManagedMem0V5ProductionLifecycleError) as first:
        production.terminalize()
    assert first.value.code == "managed_mem0_v5_production_lifecycle_terminalize_failed"
    assert first.value.__suppress_context__
    assert production.terminalize() is terminal
    assert calls == 2


def test_terminalize_rejects_durable_journal_state_mismatch(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production, _lifecycle, _binding, _authority, _coordinator, _values, journal_values, _ = (
        _new_production(tmp_path)
    )
    journal = journal_values["operation_journal"]
    production.admit_or_restore()
    real_snapshot = journal.snapshot

    def mismatched_snapshot(run_id: str):
        snapshot = real_snapshot(run_id)
        return replace(
            snapshot,
            pending_count=0,
            committed_count=snapshot.run.identity.expected_operation_count,
        )

    monkeypatch.setattr(journal, "snapshot", mismatched_snapshot)
    with pytest.raises(ManagedMem0V5ProductionLifecycleError) as failed:
        production.terminalize()
    assert failed.value.code == "managed_mem0_v5_production_lifecycle_terminalize_journal_invalid"
