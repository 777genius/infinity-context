from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_adapters.postgres.managed_benchmark_strict_v4_fact_authority import (
    ExpectedIndexStrictV4FactAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_lookup import (
    ExpectedCleanupV3Operation,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusClaim,
    ManagedBenchmarkStrictV4FactClaim,
    ManagedBenchmarkStrictV4WriteError,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import LOCOMO_PROFILE

from tests.unit.test_managed_cleanup_v3_paged_authority import _context, _operation


class _Lookup:
    def __init__(self, operation, descriptors: tuple[str, ...]) -> None:
        self.operation = operation
        self.descriptors = descriptors

    def has_corpus(self, corpus_identity_sha256: str) -> bool:
        return corpus_identity_sha256 == self.operation.corpus_identity_sha256

    def lookup_source(self, source_identity_sha256: str):
        if source_identity_sha256 != self.operation.source_identity_sha256:
            return None
        return self.operation

    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]:
        return self.descriptors if sequence == self.operation.sequence else ()


def _material():
    context = _context(LOCOMO_PROFILE)
    source = _operation(LOCOMO_PROFILE, 0)
    operation = ExpectedCleanupV3Operation(
        sequence=source.sequence,
        lane=source.lane,
        corpus_identity_sha256=source.corpus_identity_sha256,
        memory_scope_external_ref_sha256=source.memory_scope_external_ref_sha256,
        thread_external_ref_sha256=source.thread_external_ref_sha256,
        source_identity_sha256=source.source_identity_sha256,
        source_content_sha256=source.source_content_sha256,
        operation_commitment_sha256=source.operation_commitment_sha256,
        operation_sha256=source.operation_sha256,
        source_refs_sha256=source.source_refs_sha256,
        source_ref_root_sha256=source.source_ref_root_sha256,
        source_ref_count=len(source.ordered_source_ref_descriptor_sha256),
        fragments_sha256=source.fragments_sha256,
        fragment_root_sha256=source.fragment_root_sha256,
        fragment_count=len(source.ordered_fragment_descriptor_sha256),
    )
    claim = ManagedBenchmarkStrictV4FactClaim(
        run_id_sha256=context.run_id_sha256,
        binding_commitment_sha256=context.binding_commitment_sha256,
        infinity_target_identity_sha256=context.infinity_target_identity_sha256,
        space_id=context.space_id,
        space_slug=context.space_slug,
        memory_scope_external_ref="benchmark-corpus:0",
        thread_external_ref="benchmark-thread:0",
        source_identity_sha256=source.source_identity_sha256,
        source_content_sha256=source.source_content_sha256,
        operation_commitment_sha256=source.operation_commitment_sha256,
        source_refs_sha256=source.source_refs_sha256,
        source_ref_root_sha256=source.source_ref_root_sha256,
        ordered_source_ref_descriptor_sha256=source.ordered_source_ref_descriptor_sha256,
    )
    return context, operation, claim


def test_expected_index_authorizes_only_exact_strict_v4_fact() -> None:
    context, operation, claim = _material()
    authority = ExpectedIndexStrictV4FactAuthority(
        context=context,
        authority_terminal_sha256="f" * 64,
        lookup=_Lookup(operation, claim.ordered_source_ref_descriptor_sha256),
    )

    admitted = authority.admit_fact(claim)
    assert admitted.operation_sha256 == operation.operation_sha256
    assert admitted.idempotency_key.startswith("managed-benchmark-fact-v4-")
    assert authority.admit_fact(claim) == admitted

    for field in (
        "binding_commitment_sha256",
        "source_content_sha256",
        "operation_commitment_sha256",
        "source_ref_root_sha256",
    ):
        with pytest.raises(ManagedBenchmarkStrictV4WriteError):
            authority.admit_fact(replace(claim, **{field: "0" * 64}))


def test_expected_index_authorizes_only_exact_scope_thread_pair() -> None:
    context, operation, claim = _material()
    authority = ExpectedIndexStrictV4FactAuthority(
        context=context,
        authority_terminal_sha256="f" * 64,
        lookup=_Lookup(operation, claim.ordered_source_ref_descriptor_sha256),
    )
    corpus_claim = ManagedBenchmarkStrictV4CorpusClaim(
        run_id_sha256=context.run_id_sha256,
        binding_commitment_sha256=context.binding_commitment_sha256,
        infinity_target_identity_sha256=context.infinity_target_identity_sha256,
        space_id=context.space_id,
        space_slug=context.space_slug,
        memory_scope_external_ref="benchmark-corpus:0",
        thread_external_ref="benchmark-thread:0",
    )
    admitted = authority.admit_corpus(corpus_claim)
    assert admitted.corpus_identity_sha256 == operation.corpus_identity_sha256
    with pytest.raises(ManagedBenchmarkStrictV4WriteError, match="corpus_invalid"):
        authority.admit_corpus(
            replace(corpus_claim, thread_external_ref="benchmark-thread:foreign")
        )


def test_expected_index_rejects_missing_or_crosswired_descriptors() -> None:
    context, operation, claim = _material()
    missing = replace(operation, source_identity_sha256="1" * 64)
    with pytest.raises(ManagedBenchmarkStrictV4WriteError, match="operation_invalid"):
        ExpectedIndexStrictV4FactAuthority(
            context=context,
            authority_terminal_sha256="f" * 64,
            lookup=_Lookup(missing, claim.ordered_source_ref_descriptor_sha256),
        ).admit_fact(claim)

    with pytest.raises(ManagedBenchmarkStrictV4WriteError, match="operation_invalid"):
        ExpectedIndexStrictV4FactAuthority(
            context=context,
            authority_terminal_sha256="f" * 64,
            lookup=_Lookup(operation, ("2" * 64,)),
        ).admit_fact(claim)
