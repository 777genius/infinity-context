from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from infinity_context_adapters.postgres.managed_benchmark_strict_v4_document_authority import (
    ExpectedIndexStrictV4DocumentAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_lookup import (
    ExpectedCleanupV3Operation,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentClaim,
    ManagedBenchmarkStrictV4DocumentWriteError,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LONGMEMEVAL_PROFILE,
    PROFILE_ORACLES,
    build_context,
    commitment,
)
from test_managed_cleanup_v3_paged_authority import _operation


def _sha(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _context():
    oracle = PROFILE_ORACLES[LONGMEMEVAL_PROFILE]
    q_target, q_policy = _sha("q-target"), _sha("q-policy")
    g_target, g_policy = _sha("g-target"), _sha("g-policy")
    return build_context(
        profile_id=LONGMEMEVAL_PROFILE,
        manifest_context_sha256=_sha("manifest"),
        a1_terminal_commitment_sha256=_sha("a1"),
        run_id_sha256=_sha("run"),
        binding_commitment_sha256=_sha("binding"),
        publishable_profile_commitment_sha256=_sha("profile"),
        methodology_commitment_sha256=_sha("method"),
        dataset_sha256=str(oracle["dataset_sha256"]),
        admission_commitment_sha256=_sha("admission"),
        ingestion_root_sha256=_sha("ingestion"),
        case_manifest_sha256=_sha("cases"),
        infinity_target_identity_sha256=_sha("target"),
        space_id="benchmark-space-" + "a" * 48,
        space_slug="benchmark-space-" + "a" * 48,
        cleanup_target_authority_sha256=_sha("cleanup"),
        qdrant_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "qdrant",
                "target_commitment_sha256": q_target,
                "policy_commitment_sha256": q_policy,
            },
        ),
        qdrant_target_commitment_sha256=q_target,
        qdrant_policy_commitment_sha256=q_policy,
        graphiti_authority_sha256=commitment(
            "lane-authority/v4",
            {
                "lane": "graphiti",
                "target_commitment_sha256": g_target,
                "policy_commitment_sha256": g_policy,
            },
        ),
        graphiti_target_commitment_sha256=g_target,
        graphiti_policy_commitment_sha256=g_policy,
        cognee_policy_sha256=_sha("cognee"),
        namespace_policy_sha256=_sha("namespace"),
        cleanup_operation_stream_root_sha256=_sha("cleanup-root"),
        omitted_source_identity_root_sha256=str(oracle["omitted_source_identity_root_sha256"]),
    )


class _Lookup:
    def __init__(self, operation, source_refs, fragments) -> None:
        self.operation = operation
        self.source_refs = source_refs
        self.fragments = fragments

    def lookup_source(self, source_identity_sha256: str):
        if source_identity_sha256 != self.operation.source_identity_sha256:
            return None
        return self.operation

    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]:
        return self.source_refs if sequence == self.operation.sequence else ()

    def lookup_fragment_descriptors(self, sequence: int) -> tuple[str, ...]:
        return self.fragments if sequence == self.operation.sequence else ()


def _material():
    context = _context()
    source = _operation(LONGMEMEVAL_PROFILE, 0)
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
    claim = ManagedBenchmarkStrictV4DocumentClaim(
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
        ordered_source_ref_descriptor_sha256=(source.ordered_source_ref_descriptor_sha256),
        fragments_sha256=source.fragments_sha256,
        fragment_root_sha256=source.fragment_root_sha256,
        ordered_fragment_descriptor_sha256=source.ordered_fragment_descriptor_sha256,
    )
    return context, operation, claim


def _authority(context, operation, claim):
    return ExpectedIndexStrictV4DocumentAuthority(
        context=context,
        authority_terminal_sha256="f" * 64,
        lookup=_Lookup(
            operation,
            claim.ordered_source_ref_descriptor_sha256,
            claim.ordered_fragment_descriptor_sha256,
        ),
    )


def test_expected_index_authorizes_only_exact_strict_v4_document() -> None:
    context, operation, claim = _material()
    authority = _authority(context, operation, claim)

    admitted = authority.admit_document(claim)
    assert admitted.operation_sha256 == operation.operation_sha256
    assert admitted.idempotency_key.startswith("managed-benchmark-document-v4-")
    assert authority.admit_document(claim) == admitted

    for field in (
        "binding_commitment_sha256",
        "source_content_sha256",
        "operation_commitment_sha256",
        "source_ref_root_sha256",
        "fragment_root_sha256",
    ):
        with pytest.raises(ManagedBenchmarkStrictV4DocumentWriteError):
            authority.admit_document(replace(claim, **{field: "0" * 64}))


def test_expected_index_rejects_crosswired_document_descriptors() -> None:
    context, operation, claim = _material()
    for lookup in (
        _Lookup(operation, ("1" * 64,), claim.ordered_fragment_descriptor_sha256),
        _Lookup(operation, claim.ordered_source_ref_descriptor_sha256, ("2" * 64,)),
    ):
        with pytest.raises(ManagedBenchmarkStrictV4DocumentWriteError, match="operation_invalid"):
            ExpectedIndexStrictV4DocumentAuthority(
                context=context,
                authority_terminal_sha256="f" * 64,
                lookup=lookup,
            ).admit_document(claim)
