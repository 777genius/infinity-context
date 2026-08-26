from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupTargetAuthority,
    build_managed_benchmark_cleanup_target_authority,
)
from infinity_context_server.memory_comparison_backend_target import (
    FullComparisonBackendTarget,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunCase
from infinity_context_server.memory_comparison_managed_v5_cleanup_plan_builder import (
    ManagedV5CleanupPlanBuilderError,
    ManagedV5CleanupPlanInputs,
    build_managed_v5_cleanup_plan,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _target(infinity: str = "1" * 64) -> ManagedBenchmarkCleanupTargetAuthority:
    return build_managed_benchmark_cleanup_target_authority(
        infinity_target_identity_sha256=infinity,
        qdrant_target_commitment_sha256=_sha("qdrant"),
        graphiti_target_commitment_sha256=_sha("graphiti"),
    )


@pytest.fixture(autouse=True)
def _exact_infinity_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = tuple(
        SimpleNamespace(
            lane="fact",
            source_id_sha256=_sha(f"infinity-source:{index}"),
            source_content_sha256=_sha(f"infinity-content:{index}"),
            expected_chunk_count=0,
            operation_commitment_sha256=_sha(f"infinity-operation:{index}"),
        )
        for index in range(419)
    )
    corpus = SimpleNamespace(
        corpus_id="conv-26",
        thread_external_ref_sha256=_sha("conv-26-thread"),
        sources=sources,
        expected_fact_count=419,
        expected_document_count=0,
        expected_chunk_count=0,
    )
    projected = SimpleNamespace(
        corpora=(corpus,),
        expected_source_count=419,
        expected_fact_count=419,
        expected_document_count=0,
        expected_chunk_count=0,
    )
    monkeypatch.setattr(
        "infinity_context_server.memory_comparison_managed_v5_cleanup_plan_builder."
        "project_managed_v5_infinity_cleanup",
        lambda _projection: projected,
    )


def _public(*, reverse_units: bool = False, conflict: bool = False):
    cases = tuple(
        ManagedRunCase(
            case_id=f"conv-26:qa:{index}",
            corpus_id="conv-26",
            record={
                "conversation": ["exact", "public", "record"],
                "version": index if conflict and index == 84 else 1,
            },
        )
        for index in (1, 2, 3, 4, 5, 15, 83, 84)
    )
    units = [
        SimpleNamespace(
            corpus_id="conv-26",
            source_id=f"conv-26:source:{index}",
            unit_identity_sha256=_sha(f"unit:{index}"),
        )
        for index in range(419)
    ]
    if reverse_units:
        units.reverse()
    manifest = SimpleNamespace(
        units=tuple(units),
        operation_count=419,
        ingestion_manifest_sha256=_sha("manifest"),
        ingestion_root_sha256=_sha("root"),
    )
    admission = SimpleNamespace(
        commitment_sha256=_sha("admission"),
        ingestion_manifest_sha256=manifest.ingestion_manifest_sha256,
        ingestion_root_sha256=manifest.ingestion_root_sha256,
        ingestion_unit_count=419,
        request=SimpleNamespace(expected_operation_count=419),
    )
    projection = SimpleNamespace(
        cases=cases,
        bindings=SimpleNamespace(
            run_id="mem0-v5-live-test-r1",
            binding_commitment_sha256=_sha("binding"),
            backend_targets=(
                FullComparisonBackendTarget("infinity-context", "1" * 64),
                FullComparisonBackendTarget("mem0", "2" * 64),
            ),
        ),
    )
    inputs = object.__new__(ManagedV5CleanupPlanInputs)
    object.__setattr__(inputs, "projection", projection)
    object.__setattr__(inputs, "manifest_authority", manifest)
    object.__setattr__(inputs, "admission", admission)
    object.__setattr__(inputs, "profile_id", "mem0-locomo-top50-v1")
    object.__setattr__(inputs, "run_id", projection.bindings.run_id)
    return inputs


def test_exact_eight_case_419_unit_plan_is_valid_and_ordered() -> None:
    plan = build_managed_v5_cleanup_plan(inputs=_public(), target_authority=_target())
    assert plan.value["cardinality"] == {
        "case_count": 8,
        "corpus_count": 1,
        "mem0_source_identity_count": 419,
        "expected_ingest_unit_count": 419,
        "infinity_operation_count": 419,
        "expected_fact_count": 419,
        "expected_document_count": 0,
        "expected_chunk_count": 0,
    }
    assert len(plan.value["ordered_case_sha256"]) == 8
    corpus = plan.value["corpora"][0]
    assert len(corpus["ordered_mem0_source_id_sha256"]) == 419
    assert len(corpus["ordered_infinity_operation_sha256"]) == 419
    assert len(corpus["ordered_mem0_unit_identity_sha256"]) == 419


def test_unit_order_changes_plan_digest_but_remains_exact() -> None:
    forward = build_managed_v5_cleanup_plan(inputs=_public(), target_authority=_target())
    reverse = build_managed_v5_cleanup_plan(
        inputs=_public(reverse_units=True), target_authority=_target()
    )
    assert forward.sha256 != reverse.sha256
    assert forward.value["corpora"][0]["ordered_mem0_unit_identity_sha256"] == list(
        reversed(reverse.value["corpora"][0]["ordered_mem0_unit_identity_sha256"])
    )


def test_target_tamper_record_conflict_and_duplicate_identity_fail_closed() -> None:
    target = _target()
    with pytest.raises(ManagedV5CleanupPlanBuilderError):
        build_managed_v5_cleanup_plan(
            inputs=_public(),
            target_authority=replace(target, authority_sha256="0" * 64),
        )
    with pytest.raises(ManagedV5CleanupPlanBuilderError, match="record_conflict"):
        build_managed_v5_cleanup_plan(inputs=_public(conflict=True), target_authority=target)

    public = _public()
    units = list(public.manifest_authority.units)
    units[1].source_id = units[0].source_id
    with pytest.raises(ManagedV5CleanupPlanBuilderError, match="identity_duplicate"):
        build_managed_v5_cleanup_plan(inputs=public, target_authority=target)
