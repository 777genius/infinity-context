"""Strict-v4 document admission backed by the authenticated expected index."""

from __future__ import annotations

from typing import Any, Protocol, final

from infinity_context_core.ports.managed_benchmark_strict_v4_document_write import (
    ManagedBenchmarkStrictV4DocumentAdmission,
    ManagedBenchmarkStrictV4DocumentClaim,
    ManagedBenchmarkStrictV4DocumentWriteError,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    LONGMEMEVAL_PROFILE,
    ManagedCleanupV3Context,
    commitment,
    corpus_identity_sha256,
    digest,
    memory_scope_external_ref_sha256,
    thread_external_ref_sha256,
)


class StrictV4DocumentOperationLookup(Protocol):
    def lookup_source(self, source_identity_sha256: str) -> Any | None: ...

    def lookup_source_ref_descriptors(self, sequence: int) -> tuple[str, ...]: ...

    def lookup_fragment_descriptors(self, sequence: int) -> tuple[str, ...]: ...


@final
class ExpectedIndexStrictV4DocumentAuthority:
    """Authorize exact document writes without exposing SQLite to core."""

    def __init__(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority_terminal_sha256: str,
        lookup: StrictV4DocumentOperationLookup,
    ) -> None:
        if (
            type(context) is not ManagedCleanupV3Context
            or not callable(getattr(lookup, "lookup_source", None))
            or not callable(getattr(lookup, "lookup_source_ref_descriptors", None))
            or not callable(getattr(lookup, "lookup_fragment_descriptors", None))
        ):
            _fail("capability_invalid")
        context.__post_init__()
        self._context = context
        self._terminal = digest(authority_terminal_sha256)
        self._lookup = lookup

    def admit_document(
        self, claim: ManagedBenchmarkStrictV4DocumentClaim
    ) -> ManagedBenchmarkStrictV4DocumentAdmission:
        if type(claim) is not ManagedBenchmarkStrictV4DocumentClaim:
            _fail("claim_invalid")
        claim.__post_init__()
        context = self._context
        if context.profile_id != LONGMEMEVAL_PROFILE:
            _fail("binding_invalid")
        if (
            claim.run_id_sha256 != context.run_id_sha256
            or claim.binding_commitment_sha256 != context.binding_commitment_sha256
            or claim.infinity_target_identity_sha256 != context.infinity_target_identity_sha256
            or claim.space_id != context.space_id
            or claim.space_slug != context.space_slug
        ):
            _fail("binding_invalid")
        scope_sha = memory_scope_external_ref_sha256(claim.memory_scope_external_ref)
        thread_sha = thread_external_ref_sha256(claim.thread_external_ref)
        corpus_sha = corpus_identity_sha256(
            lane="document",
            memory_scope_external_ref_sha256=scope_sha,
            thread_external_ref_sha256=thread_sha,
        )
        operation = self._lookup.lookup_source(claim.source_identity_sha256)
        if (
            operation is None
            or operation.lane != "document"
            or operation.corpus_identity_sha256 != corpus_sha
            or operation.memory_scope_external_ref_sha256 != scope_sha
            or operation.thread_external_ref_sha256 != thread_sha
            or operation.source_identity_sha256 != claim.source_identity_sha256
            or operation.source_content_sha256 != claim.source_content_sha256
            or operation.operation_commitment_sha256 != claim.operation_commitment_sha256
            or operation.source_refs_sha256 != claim.source_refs_sha256
            or operation.source_ref_root_sha256 != claim.source_ref_root_sha256
            or operation.source_ref_count != len(claim.ordered_source_ref_descriptor_sha256)
            or operation.fragments_sha256 != claim.fragments_sha256
            or operation.fragment_root_sha256 != claim.fragment_root_sha256
            or operation.fragment_count != len(claim.ordered_fragment_descriptor_sha256)
            or self._lookup.lookup_source_ref_descriptors(operation.sequence)
            != claim.ordered_source_ref_descriptor_sha256
            or self._lookup.lookup_fragment_descriptors(operation.sequence)
            != claim.ordered_fragment_descriptor_sha256
        ):
            _fail("operation_invalid")
        operation_sha256 = digest(operation.operation_sha256)
        key_digest = commitment(
            "strict-v4-document-idempotency/v1",
            {
                "run_id_sha256": context.run_id_sha256,
                "context_sha256": context.context_sha256,
                "authority_terminal_sha256": self._terminal,
                "operation_sha256": operation_sha256,
                "source_identity_sha256": claim.source_identity_sha256,
            },
        )
        return ManagedBenchmarkStrictV4DocumentAdmission(
            operation_sha256=operation_sha256,
            idempotency_key=f"managed-benchmark-document-v4-{key_digest}",
        )


def _fail(suffix: str) -> None:
    raise ManagedBenchmarkStrictV4DocumentWriteError(
        f"managed_benchmark_strict_v4_document_write_{suffix}"
    )


__all__ = (
    "ExpectedIndexStrictV4DocumentAuthority",
    "StrictV4DocumentOperationLookup",
)
