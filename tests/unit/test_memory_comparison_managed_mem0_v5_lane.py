from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_http_ingest_request import case_message_groups
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _managed_corpus_record,
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_lane import (
    ManagedMem0V5Budget,
    ManagedMem0V5BudgetPolicy,
    ManagedMem0V5LaneCoordinator,
    ManagedMem0V5SourcePair,
    ManagedMem0V5StorageObservation,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestProjector,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    create_managed_mem0_v5_storage_witness_authority,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    managed_policy_cases_from_dataset,
)
from infinity_context_server.memory_comparison_managed_run_contract import (
    ManagedRunCase,
    ManagedRunError,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationResult,
    Mem0OssAdmissionRequest,
    Mem0OssFullRunError,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationContext,
    RuntimeReceiptVerificationResult,
    StorageVerificationContext,
    StorageVerificationResult,
    canonical_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_run import (
    Mem0OssFullRunService,
    verify_mem0_oss_sealed_evidence_pages,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkConversationInput,
    BenchmarkMessageInput,
    PublicBenchmarkCase,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _record(*, duplicate: bool = False) -> dict[str, object]:
    corpus_id = f"locomo-corpus-{'a' * 64}"
    memories = [
        {
            "kind": "fact",
            "role": "user",
            "session_alias": "session-0001",
            "source_alias": "memory-000001",
            "speaker": "Alice",
            "session_date": "2024-03-10",
            "text": "Alice likes tea.",
            "timestamp": 1,
        }
    ]
    if duplicate:
        memories.append({**memories[0], "source_alias": "memory-000002", "timestamp": 2})
    return {
        "schema_version": "memory-comparison-managed-corpus.v2",
        "benchmark": "locomo",
        "corpus_id": corpus_id,
        "thread_id": f"locomo-thread-{'b' * 64}",
        "memories": memories,
        "documents": [],
        "conversations": [],
    }


def _cases(*, duplicate: bool = False) -> tuple[ManagedRunCase, ...]:
    record = _record(duplicate=duplicate)
    corpus_id = str(record["corpus_id"])
    return (
        ManagedRunCase("case-1", corpus_id, record),
        ManagedRunCase("case-2", corpus_id, record),
    )


def _longmemeval_cases() -> tuple[ManagedRunCase, ...]:
    public_case = PublicBenchmarkCase(
        benchmark="longmemeval",
        case_id="long-source-case",
        question="Hidden evaluator question",
        expected_terms=("hidden-gold",),
        conversations=(
            BenchmarkConversationInput(
                messages=(
                    BenchmarkMessageInput("user", "I moved to Oslo.", timestamp=1_700_000_000),
                    BenchmarkMessageInput(
                        "assistant", "I will remember that.", timestamp=1_700_000_001
                    ),
                ),
                source_external_id="raw-pair-1",
                session_external_id="raw-session-1",
                session_date="2023-11-14",
                timestamp=1_700_000_001,
            ),
        ),
        memory_scope_external_ref="raw-corpus",
        thread_external_ref="raw-thread",
    )
    record = _managed_corpus_record(public_case)
    corpus_id = str(record["corpus_id"])
    return (ManagedRunCase("long-case-1", corpus_id, record),)


def _canonical_groups(case: ManagedRunCase):
    reconstructed = _reconstruct_managed_corpus_case(
        case.record,
        case_id=case.case_id,
        question="Managed source projection sentinel.",
        temporal_context={},
    )
    return case_message_groups(reconstructed)


class _ReceiptPort:
    def mark_outcome_unknown(self, *, context: RuntimeReceiptVerificationContext) -> None:
        assert context.readback_only is False

    def _result(
        self, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        return RuntimeReceiptVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=_sha("provider-receipt"),
            disposition=Mem0OssReceiptDisposition.COMPLETED,
            extraction_calls=1,
            retry_count=0,
            request_tokens=7,
            response_tokens=3,
        )

    def verify_dispatch_receipt(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        assert payload == {"receipt": "dispatch"}
        return self._result(context)

    def verify_status_readback(
        self, *, payload: object, context: RuntimeReceiptVerificationContext
    ) -> RuntimeReceiptVerificationResult:
        assert payload == {"receipt": "status"}
        return self._result(context)


class _StoragePort:
    def verify(
        self, *, payload: object, context: StorageVerificationContext
    ) -> StorageVerificationResult:
        assert type(payload) is ManagedMem0V5AuthenticatedStorageWitness
        return StorageVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=context.provider_receipt_sha256,
            stored_identity_sha256=payload.storage_commitment_sha256,
            stored_record_count=len(payload.created_record_ids),
        )


class _CleanupPort:
    def verify(
        self, *, payload: object, context: CleanupVerificationContext
    ) -> CleanupVerificationResult:
        assert payload == {"cleanup": context.aborting}
        return CleanupVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            seal_commitment_sha256=context.seal_commitment_sha256,
            operation_root_sha256=context.operation_root_sha256,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=context.expected_operation_count,
            residual_record_count=0,
            residual_root_sha256=MEM0_OSS_EMPTY_ROOT_SHA256,
        )


class _Lane:
    def __init__(
        self,
        *,
        crash_admit: bool = False,
        crash_dispatch: bool = False,
        crash_cleanup: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.crash_admit = crash_admit
        self.crash_dispatch = crash_dispatch
        self.crash_cleanup = crash_cleanup
        self.storage_issuer, _ = create_managed_mem0_v5_storage_witness_authority()

    def admit(self, **kwargs: object) -> None:
        del kwargs
        self.calls.append("admit")
        if self.crash_admit:
            self.crash_admit = False
            raise RuntimeError("simulated admission response loss")

    def dispatch(self, **kwargs: object) -> object:
        del kwargs
        self.calls.append("dispatch")
        if self.crash_dispatch:
            self.crash_dispatch = False
            raise RuntimeError("simulated lost response")
        return {"receipt": "dispatch"}

    def status(self, **kwargs: object) -> object:
        del kwargs
        self.calls.append("status")
        return {"receipt": "status"}

    def inspect_storage(self, **kwargs: object) -> ManagedMem0V5AuthenticatedStorageWitness:
        self.calls.append("storage")
        unit = kwargs["unit"]
        operation_id = kwargs["operation_id_sha256"]
        return self.storage_issuer.issue_authenticated_storage(
            operation_id_sha256=operation_id,
            unit_identity_sha256=unit.unit_identity_sha256,
            storage_commitment_sha256=_sha("storage"),
            created_record_ids=("memory-opaque-1",),
            source_pairs=((unit.source_id, unit.source_sha256),),
        )

    def cleanup(self, **kwargs: object) -> object:
        self.calls.append("cleanup")
        if self.crash_cleanup:
            self.crash_cleanup = False
            raise RuntimeError("simulated cleanup response loss")
        return {"cleanup": kwargs["aborting"]}


def _request(operation_count: int) -> Mem0OssAdmissionRequest:
    return Mem0OssAdmissionRequest(
        run_id="managed-v5-test",
        route_sha256=_sha("route"),
        credential_binding_sha256=_sha("credential"),
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        service_tier="priority",
        runtime_source_revision="source-r1",
        runtime_source_sha256=_sha("runtime-source"),
        runtime_base_sha256=_sha("runtime-base"),
        expected_operation_count=operation_count,
    )


def _coordinator(
    lane: _Lane, projector: ManagedMem0V5ManifestProjector
) -> ManagedMem0V5LaneCoordinator:
    service = Mem0OssFullRunService(
        manifest_port=projector,
        receipt_port=_ReceiptPort(),
        storage_port=_StoragePort(),
        cleanup_port=_CleanupPort(),
    )
    return ManagedMem0V5LaneCoordinator(service=service, lane_port=lane)


def test_projector_preserves_source_hash_parity_and_separates_case_operation_counts() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    unit = authority.units[0]

    assert authority.case_count == 2
    assert authority.corpus_count == 1
    assert authority.operation_count == 1
    messages, timestamp, metadata = _canonical_groups(_cases()[0])[0]
    assert timestamp == 1
    assert [item.payload() for item in unit.source_messages] == list(messages)
    assert unit.source_id == metadata["source_id"]
    assert unit.source_sha256 == metadata["source_sha256"]
    assert unit.source_sha256 != unit.unit_sha256
    assert unit.observation_date == "2024-03-10"
    assert unit.unit_sha256 == canonical_sha256({"source_messages": list(messages)})
    assert unit.scope_sha256 == canonical_sha256(
        {
            "corpus_id": unit.corpus_id,
            "source_id": unit.source_id,
            "source_sha256": unit.source_sha256,
            "unit_sha256": unit.unit_sha256,
        }
    )
    verified = projector.verify(payload=authority)
    assert verified.units == authority.manifest_units()


def test_projector_rejects_tamper_but_allows_distinct_duplicate_content_sources() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    object.__setattr__(authority, "sealed_payload_sha256", "0" * 64)
    with pytest.raises(ManagedRunError, match="seal differs"):
        projector.verify(payload=authority)

    repeated = projector.project(_cases(duplicate=True), current_date="2026-08-07")
    assert repeated.operation_count == 2
    assert repeated.units[0].unit_sha256 != repeated.units[1].unit_sha256
    assert repeated.units[0].scope_sha256 != repeated.units[1].scope_sha256
    assert repeated.units[0].unit_identity_sha256 != repeated.units[1].unit_identity_sha256
    assert projector.verify(payload=repeated).units == repeated.manifest_units()


def test_authority_count_tamper_fails_before_budget_or_lane_io() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    object.__setattr__(authority, "case_count", 1)

    with pytest.raises(ManagedRunError, match="authority seal differs"):
        ManagedMem0V5Budget.for_authority(authority)


def test_projector_rejects_system_role_before_manifest_admission() -> None:
    record = _record()
    memories = record["memories"]
    assert type(memories) is list and type(memories[0]) is dict
    memories[0]["role"] = "system"
    corpus_id = str(record["corpus_id"])

    with pytest.raises(ManagedRunError, match="official turn semantics are incomplete"):
        ManagedMem0V5ManifestProjector().project(
            (ManagedRunCase("case-system", corpus_id, record),),
            current_date="2026-08-07",
        )


def test_projected_private_payload_is_accepted_by_exact_adapter_parser(tmp_path: Path) -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(duplicate=True), current_date="2026-08-07")
    adapter_root = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
    sys.path.insert(0, str(adapter_root))
    try:
        parser = importlib.import_module("mem0_oss_adapter_v5.sealed_manifest")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(authority.private_payload(), sort_keys=True, separators=(",", ":"))
        )
        manifest_path.chmod(0o400)
        parsed = parser.SealedInputManifest(manifest_path)
    finally:
        sys.path.remove(str(adapter_root))
    assert parsed.ingestion_root_sha256 == authority.ingestion_root_sha256
    assert len(parsed.units) == authority.operation_count == 2
    assert parsed.units[0].source_sha256 == authority.units[0].source_sha256
    assert parsed.units[1].source_sha256 == authority.units[1].source_sha256


def test_adapter_parser_keeps_exact_v1_compatibility_and_rejects_malformed_schema(
    tmp_path: Path,
) -> None:
    adapter_root = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
    sys.path.insert(0, str(adapter_root))
    try:
        parser = importlib.import_module("mem0_oss_adapter_v5.sealed_manifest")
        unit = {
            "sequence": 0,
            "unit_identity_sha256": _sha("identity-v1"),
            "unit_sha256": _sha("unit-v1"),
            "scope_sha256": _sha("scope-v1"),
            "corpus_id": "corpus-v1",
            "source_id": "source-v1",
            "observation_date": "2024-03-10",
            "source_messages": [{"role": "user", "content": "legacy payload"}],
        }
        root = canonical_sha256(
            {
                "units": [
                    {
                        key: unit[key]
                        for key in (
                            "unit_identity_sha256",
                            "unit_sha256",
                            "scope_sha256",
                        )
                    }
                ]
            }
        )
        unsigned: dict[str, object] = {
            "schema_version": "mem0-oss-adapter-v5.sealed-input.v1",
            "ingestion_manifest_sha256": _sha("manifest-v1"),
            "ingestion_root_sha256": root,
            "current_date": "2026-08-07",
            "units": [unit],
        }
        path = tmp_path / "v1.json"
        path.write_text(
            json.dumps({**unsigned, "sealed_payload_sha256": canonical_sha256(unsigned)})
        )
        path.chmod(0o400)
        parsed = parser.SealedInputManifest(path)
        assert parsed.units[0].source_sha256 == parsed.units[0].unit_sha256

        malformed = {**unsigned, "schema_version": []}
        malformed_path = tmp_path / "malformed.json"
        malformed_path.write_text(
            json.dumps(
                {
                    **malformed,
                    "sealed_payload_sha256": canonical_sha256(malformed),
                }
            )
        )
        malformed_path.chmod(0o400)
        with pytest.raises(ValueError, match="sealed_input_invalid"):
            parser.SealedInputManifest(malformed_path)
    finally:
        sys.path.remove(str(adapter_root))


def test_adapter_v2_rejects_self_resealed_source_scope_tamper(tmp_path: Path) -> None:
    authority = ManagedMem0V5ManifestProjector().project(_cases(), current_date="2026-08-07")
    payload = authority.private_payload()
    units = payload["units"]
    assert type(units) is list and type(units[0]) is dict
    units[0]["source_sha256"] = "0" * 64
    unsigned = {key: value for key, value in payload.items() if key != "sealed_payload_sha256"}
    payload["sealed_payload_sha256"] = canonical_sha256(unsigned)
    path = tmp_path / "tampered-v2.json"
    path.write_text(json.dumps(payload))
    path.chmod(0o400)
    adapter_root = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
    sys.path.insert(0, str(adapter_root))
    try:
        parser = importlib.import_module("mem0_oss_adapter_v5.sealed_manifest")
        with pytest.raises(ValueError, match="sealed_input_invalid"):
            parser.SealedInputManifest(path)
    finally:
        sys.path.remove(str(adapter_root))


def test_longmemeval_projector_matches_canonical_message_group_lane() -> None:
    cases = _longmemeval_cases()
    authority = ManagedMem0V5ManifestProjector().project(cases, current_date="2026-08-07")
    messages, timestamp, metadata = _canonical_groups(cases[0])[0]
    unit = authority.units[0]

    assert timestamp == 1_700_000_001
    assert [item.payload() for item in unit.source_messages] == list(messages)
    assert unit.source_id == metadata["source_id"]
    assert unit.source_sha256 == metadata["source_sha256"]
    assert unit.observation_date == "2023-11-14"


def test_official_locomo10_projects_exact_frozen_turn_inventory_when_available() -> None:
    dataset_value = os.environ.get("MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET")
    if not dataset_value:
        pytest.skip("official LoCoMo dataset is opt-in")
    dataset_path = Path(dataset_value)
    cases = managed_policy_cases_from_dataset(
        profile=resolve_full_comparison_profile("mem0-locomo-top200-v1"),
        dataset_bytes=dataset_path.read_bytes(),
        scope="full",
        selected_case_ids=(),
    )
    authority = ManagedMem0V5ManifestProjector().project(
        cases,
        current_date="2026-08-07",
    )

    assert authority.case_count == 1_540
    assert authority.corpus_count == 10
    assert authority.operation_count == 5_882
    assert len({item.unit_sha256 for item in authority.units}) == 5_882
    assert len({item.source_sha256 for item in authority.units}) == 5_882
    assert len({item.source_id for item in authority.units}) == 5_882
    assert len({item.scope_sha256 for item in authority.units}) == 5_882
    assert len({item.unit_identity_sha256 for item in authority.units}) == 5_882


def test_budget_fails_before_lane_io_and_counts_four_benchmark_calls_per_case() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    lane = _Lane()
    coordinator = _coordinator(lane, projector)

    with pytest.raises(ManagedRunError, match="budget exceeded"):
        coordinator.admit(
            authority=authority,
            request=_request(1),
            budget_policy=ManagedMem0V5BudgetPolicy(8),
        )
    assert lane.calls == []

    coordinator = _coordinator(lane, projector)
    coordinator.admit(
        authority=authority,
        request=_request(1),
        budget_policy=ManagedMem0V5BudgetPolicy(9),
    )
    assert coordinator.budget.public_payload() == {
        "case_count": 2,
        "extraction_call_count": 1,
        "benchmark_call_count": 8,
        "total_call_count": 9,
    }


def test_crash_reconciliation_uses_status_and_never_redispatches() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    lane = _Lane(crash_dispatch=True)
    coordinator = _coordinator(lane, projector)
    coordinator.admit(
        authority=authority,
        request=_request(1),
        budget_policy=ManagedMem0V5BudgetPolicy(9),
    )

    with pytest.raises(RuntimeError, match="lost response"):
        coordinator.dispatch_pending()
    coordinator.reconcile_after_crash()
    seal = coordinator.dispatch_pending()

    assert seal.operation_count == 1
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 1


def test_repeated_content_hash_seals_and_evidence_pages_verify() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(duplicate=True), current_date="2026-08-07")
    lane = _Lane()
    service = Mem0OssFullRunService(
        manifest_port=projector,
        receipt_port=_ReceiptPort(),
        storage_port=_StoragePort(),
        cleanup_port=_CleanupPort(),
    )
    coordinator = ManagedMem0V5LaneCoordinator(service=service, lane_port=lane)
    coordinator.admit(
        authority=authority,
        request=_request(2),
        budget_policy=ManagedMem0V5BudgetPolicy(10),
    )
    seal = coordinator.dispatch_pending()
    pages = service.sealed_evidence_pages(page_size=1)

    verify_mem0_oss_sealed_evidence_pages(pages, seal=seal)
    assert seal.operation_count == 2
    assert pages[0].items[0].unit_sha256 != pages[1].items[0].unit_sha256


def test_fresh_coordinator_without_durable_checkpoint_fails_closed() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    lane = _Lane(crash_dispatch=True)
    service = Mem0OssFullRunService(
        manifest_port=projector,
        receipt_port=_ReceiptPort(),
        storage_port=_StoragePort(),
        cleanup_port=_CleanupPort(),
    )
    original = ManagedMem0V5LaneCoordinator(service=service, lane_port=lane)
    original.admit(
        authority=authority,
        request=_request(1),
        budget_policy=ManagedMem0V5BudgetPolicy(9),
    )
    with pytest.raises(RuntimeError, match="lost response"):
        original.dispatch_pending()

    restarted = ManagedMem0V5LaneCoordinator(service=service, lane_port=lane)
    with pytest.raises(ManagedRunError, match="not admitted"):
        restarted.reconcile_after_crash()
    with pytest.raises(ManagedRunError, match="not admitted"):
        restarted.dispatch_pending()
    assert lane.calls.count("dispatch") == 1
    assert lane.calls.count("status") == 0


def test_terminal_cleanup_is_required_and_public_storage_observations_is_private_free() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    lane = _Lane()
    coordinator = _coordinator(lane, projector)
    coordinator.admit(
        authority=authority,
        request=_request(1),
        budget_policy=ManagedMem0V5BudgetPolicy(9),
    )
    coordinator.dispatch_pending()

    with pytest.raises(Mem0OssFullRunError, match="cleanup_not_available"):
        _ = coordinator.terminal_evidence
    evidence_json = json.dumps(coordinator.storage_observations[0].public_payload())
    authority_json = json.dumps(authority.public_payload())
    assert "source_messages" not in evidence_json + authority_json
    assert "gold" not in (evidence_json + authority_json).lower()

    terminal = coordinator.cleanup()
    assert terminal.terminal_state == "deleted"
    assert terminal.residual_record_count == 0
    assert lane.calls[-1] == "cleanup"


def test_admission_failure_still_attempts_terminal_abort_cleanup() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    lane = _Lane(crash_admit=True)
    coordinator = _coordinator(lane, projector)

    with pytest.raises(RuntimeError, match="admission response loss"):
        coordinator.admit(
            authority=authority,
            request=_request(1),
            budget_policy=ManagedMem0V5BudgetPolicy(9),
        )
    assert lane.calls == ["admit", "cleanup"]
    assert coordinator.terminal_evidence.terminal_state == "aborted"


def test_cleanup_response_loss_is_retryable_without_reopening_delete() -> None:
    projector = ManagedMem0V5ManifestProjector()
    authority = projector.project(_cases(), current_date="2026-08-07")
    lane = _Lane(crash_cleanup=True)
    coordinator = _coordinator(lane, projector)
    coordinator.admit(
        authority=authority,
        request=_request(1),
        budget_policy=ManagedMem0V5BudgetPolicy(9),
    )
    coordinator.dispatch_pending()

    with pytest.raises(RuntimeError, match="cleanup response loss"):
        coordinator.cleanup()
    terminal = coordinator.cleanup()
    assert terminal.terminal_state == "deleted"
    assert lane.calls.count("cleanup") == 2


def test_storage_observations_commitment_rejects_tamper() -> None:
    evidence = ManagedMem0V5StorageObservation.create(
        operation_id_sha256=_sha("operation"),
        unit_identity_sha256=_sha("unit"),
        storage_commitment_sha256=_sha("storage"),
        created_record_ids=("memory-1",),
        source_pairs=(ManagedMem0V5SourcePair("source-1", _sha("source")),),
    )
    object.__setattr__(evidence, "created_record_ids", ("memory-2",))
    with pytest.raises(ManagedRunError, match="storage observation is invalid"):
        evidence.__post_init__()
