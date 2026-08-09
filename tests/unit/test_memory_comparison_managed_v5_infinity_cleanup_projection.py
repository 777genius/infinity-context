from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_core.ports.benchmark_cleanup_plan import (
    MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
    MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS,
)
from infinity_context_core.ports.benchmark_managed_ingest import (
    managed_benchmark_infinity_operation_sha256,
)
from infinity_context_server.memory_comparison_conversation_ingestion import (
    conversation_documents,
)
from infinity_context_server.memory_comparison_full_profiles import (
    resolve_full_comparison_profile,
)
from infinity_context_server.memory_comparison_managed_corpus_projection import (
    _reconstruct_managed_corpus_case,
)
from infinity_context_server.memory_comparison_managed_plan_builder import (
    ManagedPublicRunProjection,
    managed_policy_cases_from_dataset,
)
from infinity_context_server.memory_comparison_managed_v5_infinity_cleanup_projection import (
    ManagedV5InfinityCleanupProjectionError,
    ManagedV5InfinityCorpusCleanupProjection,
    ManagedV5InfinitySourceDescriptor,
    managed_v5_infinity_document_operation_material,
    managed_v5_infinity_fact_operation_material,
    project_managed_v5_infinity_cleanup,
)
from infinity_context_server.public_benchmark_models import BenchmarkDocumentInput


@pytest.mark.parametrize(
    ("profile_id", "fixture", "selected", "facts", "documents", "chunks"),
    [
        (
            "mem0-locomo-top50-v1",
            "managed-locomo-sandbox.json",
            ("sandbox-locomo-1:qa:1",),
            1,
            0,
            0,
        ),
        (
            "mem0-longmemeval-top50-v1",
            "managed-longmemeval-sandbox.json",
            ("sandbox-longmem-multi",),
            0,
            4,
            4,
        ),
    ],
)
def test_exact_infinity_lane_projection_counts_and_distinct_refs(
    profile_id: str,
    fixture: str,
    selected: tuple[str, ...],
    facts: int,
    documents: int,
    chunks: int,
) -> None:
    projection = _projection(profile_id, fixture, selected)
    result = project_managed_v5_infinity_cleanup(projection)
    assert (result.expected_fact_count, result.expected_document_count) == (facts, documents)
    assert result.expected_chunk_count == chunks
    corpus = result.corpora[0]
    assert corpus.scope_external_ref_sha256 != corpus.thread_external_ref_sha256
    assert all(
        source.expected_chunk_count == 0 for source in corpus.sources if source.lane == "fact"
    )
    assert result.expected_fact_count <= MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
    assert result.expected_document_count <= MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
    assert result.expected_chunk_count <= MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
    assert (
        result.expected_fact_count + result.expected_document_count + result.expected_chunk_count
        <= MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS
    )


def test_operation_commitment_binds_fact_kind_and_document_request_semantics() -> None:
    locomo = _projection(
        "mem0-locomo-top50-v1",
        "managed-locomo-sandbox.json",
        ("sandbox-locomo-1:qa:1",),
    ).cases[0]
    rebuilt = _reconstruct(locomo)
    memory = rebuilt.memories[0]
    original_fact = managed_benchmark_infinity_operation_sha256(
        managed_v5_infinity_fact_operation_material(memory)
    )
    changed_fact = managed_benchmark_infinity_operation_sha256(
        managed_v5_infinity_fact_operation_material(replace(memory, kind="preference"))
    )
    assert original_fact != changed_fact

    longmem = _projection(
        "mem0-longmemeval-top50-v1",
        "managed-longmemeval-sandbox.json",
        ("sandbox-longmem-multi",),
    ).cases[0]
    document = conversation_documents(_reconstruct(longmem))[0]
    original_document = managed_benchmark_infinity_operation_sha256(
        managed_v5_infinity_document_operation_material(document)
    )
    changed_title = managed_benchmark_infinity_operation_sha256(
        managed_v5_infinity_document_operation_material(replace(document, title="changed"))
    )
    changed_type = managed_benchmark_infinity_operation_sha256(
        managed_v5_infinity_document_operation_material(
            replace(document, source_type="changed_source")
        )
    )
    assert len({original_document, changed_title, changed_type}) == 3


@pytest.mark.parametrize(("length", "expected_fragments"), ((1_201, 2), (76_719, 71)))
def test_document_operation_binds_exact_fragment_count(
    length: int, expected_fragments: int
) -> None:
    text = "x" * length
    document = BenchmarkDocumentInput(
        title="Long managed document",
        text=text,
        source_type="benchmark_conversation_pair",
        classification="internal",
        source_external_id=f"long-document-{length}",
        source_refs=(),
    )
    material = managed_v5_infinity_document_operation_material(document)
    assert material["fragment_count"] == expected_fragments


def test_document_content_hash_collision_with_distinct_sources_is_rejected() -> None:
    corpus_id = "corpus-1"
    content = hashlib.sha256(b"same-content").hexdigest()
    sources = tuple(
        ManagedV5InfinitySourceDescriptor(
            "document",
            hashlib.sha256(f"source-{index}".encode()).hexdigest(),
            content,
            1,
            hashlib.sha256(f"operation-{index}".encode()).hexdigest(),
        )
        for index in range(2)
    )
    with pytest.raises(ManagedV5InfinityCleanupProjectionError, match="corpus_invalid"):
        ManagedV5InfinityCorpusCleanupProjection(
            corpus_id,
            hashlib.sha256(corpus_id.encode()).hexdigest(),
            hashlib.sha256(b"thread-1").hexdigest(),
            sources,
        )


def _projection(
    profile_id: str, fixture: str, selected: tuple[str, ...]
) -> ManagedPublicRunProjection:
    profile = resolve_full_comparison_profile(profile_id)
    assert profile is not None
    cases = managed_policy_cases_from_dataset(
        profile=profile,
        dataset_bytes=(
            Path(__file__).parents[1] / "fixtures/memory_comparison" / fixture
        ).read_bytes(),
        scope="canary",
        selected_case_ids=selected,
    )
    projection = object.__new__(ManagedPublicRunProjection)
    object.__setattr__(projection, "cases", cases)
    object.__setattr__(projection, "bindings", None)
    return projection


def _reconstruct(case):
    return _reconstruct_managed_corpus_case(
        case.record,
        case_id=case.case_id,
        question="managed-ingest-gold-blind-projection",
        temporal_context={},
    )
