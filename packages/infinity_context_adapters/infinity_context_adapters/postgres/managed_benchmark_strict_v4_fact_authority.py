"""Strict-v4 fact admission backed by the authenticated expected-row index."""

from __future__ import annotations

from typing import Any, Protocol, final

from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusAdmission,
    ManagedBenchmarkStrictV4CorpusClaim,
    ManagedBenchmarkStrictV4FactAdmission,
    ManagedBenchmarkStrictV4FactClaim,
    ManagedBenchmarkStrictV4WriteError,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Context,
    commitment,
    corpus_identity_sha256,
    digest,
    memory_scope_external_ref_sha256,
    thread_external_ref_sha256,
)


class StrictV4FactOperationLookup(Protocol):
    def has_corpus(self, corpus_identity_sha256: str) -> bool: ...

    def lookup_source(self, source_identity_sha256: str) -> Any | None: ...

    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]: ...


@final
class ExpectedIndexStrictV4FactAuthority:
    """Authorize exact fact writes without exposing SQLite to the core layer."""

    def __init__(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        lookup: StrictV4FactOperationLookup,
    ) -> None:
        if (
            type(context) is not ManagedCleanupV3Context
            or not callable(getattr(lookup, "has_corpus", None))
            or not callable(getattr(lookup, "lookup_source", None))
            or not callable(getattr(lookup, "lookup_source_ref_descriptors", None))
        ):
            _fail("capability_invalid")
        context.__post_init__()
        self._context = context
        self._terminal = digest(authority_terminal_sha256)
        self._lookup = lookup

    def admit_corpus(
        self, claim: ManagedBenchmarkStrictV4CorpusClaim
    ) -> ManagedBenchmarkStrictV4CorpusAdmission:
        if type(claim) is not ManagedBenchmarkStrictV4CorpusClaim:
            _fail("claim_invalid")
        claim.__post_init__()
        self._validate_binding(
            run_id_sha256=claim.run_id_sha256,
            binding_commitment_sha256=claim.binding_commitment_sha256,
            infinity_target_identity_sha256=claim.infinity_target_identity_sha256,
            space_id=claim.space_id,
            space_slug=claim.space_slug,
        )
        scope_sha = memory_scope_external_ref_sha256(claim.memory_scope_external_ref)
        thread_sha = thread_external_ref_sha256(claim.thread_external_ref)
        candidates = tuple(
            corpus_sha
            for lane in ("fact", "document")
            for corpus_sha in (
                corpus_identity_sha256(
                    lane=lane,
                    memory_scope_external_ref_sha256=scope_sha,
                    thread_external_ref_sha256=thread_sha,
                ),
            )
            if self._lookup.has_corpus(corpus_sha)
        )
        if len(candidates) != 1:
            _fail("corpus_invalid")
        return ManagedBenchmarkStrictV4CorpusAdmission(candidates[0])

    def admit_fact(
        self, claim: ManagedBenchmarkStrictV4FactClaim
    ) -> ManagedBenchmarkStrictV4FactAdmission:
        if type(claim) is not ManagedBenchmarkStrictV4FactClaim:
            _fail("claim_invalid")
        claim.__post_init__()
        context = self._context
        if context.profile_id != "mem0-locomo-top50-v1":
            _fail("binding_invalid")
        self._validate_binding(
            run_id_sha256=claim.run_id_sha256,
            binding_commitment_sha256=claim.binding_commitment_sha256,
            infinity_target_identity_sha256=claim.infinity_target_identity_sha256,
            space_id=claim.space_id,
            space_slug=claim.space_slug,
        )
        scope_sha = memory_scope_external_ref_sha256(claim.memory_scope_external_ref)
        thread_sha = thread_external_ref_sha256(claim.thread_external_ref)
        corpus_sha = corpus_identity_sha256(
            lane="fact",
            memory_scope_external_ref_sha256=scope_sha,
            thread_external_ref_sha256=thread_sha,
        )
        operation = self._lookup.lookup_source(claim.source_identity_sha256)
        if (
            operation is None
            or operation.lane != "fact"
            or operation.corpus_identity_sha256 != corpus_sha
            or operation.memory_scope_external_ref_sha256 != scope_sha
            or operation.thread_external_ref_sha256 != thread_sha
            or operation.source_identity_sha256 != claim.source_identity_sha256
            or operation.source_content_sha256 != claim.source_content_sha256
            or operation.operation_commitment_sha256 != claim.operation_commitment_sha256
            or operation.source_refs_sha256 != claim.source_refs_sha256
            or operation.source_ref_root_sha256 != claim.source_ref_root_sha256
            or operation.source_ref_count != 1
            or operation.fragment_count != 0
            or self._lookup.lookup_source_ref_descriptors(operation.sequence)
            != claim.ordered_source_ref_descriptor_sha256
        ):
            _fail("operation_invalid")
        operation_sha256 = digest(operation.operation_sha256)
        key_digest = commitment(
            "strict-v4-fact-idempotency/v1",
            {
                "run_id_sha256": context.run_id_sha256,
                "context_sha256": context.context_sha256,
                "authority_terminal_sha256": self._terminal,
                "operation_sha256": operation_sha256,
                "source_identity_sha256": claim.source_identity_sha256,
            },
        )
        return ManagedBenchmarkStrictV4FactAdmission(
            operation_sha256=operation_sha256,
            idempotency_key=f"managed-benchmark-fact-v4-{key_digest}",
        )

    def _validate_binding(
        self,
        *,
        run_id_sha256: str,
        binding_commitment_sha256: str,
        infinity_target_identity_sha256: str,
        space_id: str,
        space_slug: str,
    ) -> None:
        context = self._context
        if (
            run_id_sha256 != context.run_id_sha256
            or binding_commitment_sha256 != context.binding_commitment_sha256
            or infinity_target_identity_sha256 != context.infinity_target_identity_sha256
            or space_id != context.space_id
            or space_slug != context.space_slug
        ):
            _fail("binding_invalid")


def _fail(suffix: str) -> None:
    raise ManagedBenchmarkStrictV4WriteError(f"managed_benchmark_strict_v4_write_{suffix}")


__all__ = ("ExpectedIndexStrictV4FactAuthority", "StrictV4FactOperationLookup")
