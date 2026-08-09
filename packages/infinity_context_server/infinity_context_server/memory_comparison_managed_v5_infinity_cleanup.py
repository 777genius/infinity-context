"""Exact Infinity cleanup receipt projection for managed-v5 policy lifecycle."""

from __future__ import annotations

from infinity_context_server.memory_comparison_full_run_evidence import (
    FullComparisonRunBindings,
)
from infinity_context_server.memory_comparison_managed_http_exact_cleanup import (
    ManagedExactCleanupObservation,
    ManagedInfinityExactCleanupCoordinator,
)
from infinity_context_server.memory_comparison_managed_http_policy_material_projection import (
    ManagedHttpPolicyExactCorpusBindings,
    project_infinity_cleanup_commitments,
)
from infinity_context_server.memory_comparison_managed_http_policy_receipts import (
    ManagedHttpPolicyDeleteReceiptState,
)
from infinity_context_server.memory_comparison_managed_http_policy_registry_evidence import (
    ManagedHttpPolicyObservedCorpusEvidence,
)
from infinity_context_server.memory_comparison_managed_http_policy_support import (
    ManagedHttpPolicyLifecycleError,
)


def project_managed_v5_infinity_cleanup(
    *,
    owner: object,
    bindings: FullComparisonRunBindings,
    corpora: tuple[ManagedHttpPolicyObservedCorpusEvidence, ...],
    coordinator: ManagedInfinityExactCleanupCoordinator,
    exact_bindings: ManagedHttpPolicyExactCorpusBindings,
    target: str,
    pass_index: int,
) -> ManagedHttpPolicyDeleteReceiptState:
    if not corpora:
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_exact_cleanup_state_unavailable")
    observations = coordinator.cleanup_all(
        tuple((corpus.bundle.scope, corpus.bundle.manifest, corpus.presence) for corpus in corpora),
        pass_index=pass_index,
    )
    if any(
        type(item) is not ManagedExactCleanupObservation
        or item.lifecycle_target_identity_sha256 != target
        or item.corpus_id != corpus.bundle.corpus_id
        or item.pass_index != pass_index
        or not item.verified_absent
        for item, corpus in zip(observations, corpora, strict=True)
    ):
        raise ManagedHttpPolicyLifecycleError("managed_http_policy_infinity_exact_cleanup_invalid")
    commitments = project_infinity_cleanup_commitments(
        observations,
        target_identity_sha256=target,
        pass_index=pass_index,
    )
    return ManagedHttpPolicyDeleteReceiptState(
        owner,
        bindings.run_id,
        bindings.binding_commitment_sha256,
        "infinity-context",
        target,
        pass_index,
        len(corpora),
        sum(len(item.canonical) for item in observations),
        True,
        all(
            (item.qdrant is None or item.qdrant.verified_absent)
            and (item.graphiti is None or item.graphiti.verified_absent)
            for item in observations
        ),
        exact_bindings.manifest_sha256,
        exact_bindings.mem0_created_memory_ids,
        exact_bindings.source_pairs,
        commitments.cleanup_commitment_sha256,
        commitments.corpus_absence_commitments,
        commitments.exact_absence_commitment_sha256,
        "live",
    )


__all__ = ("project_managed_v5_infinity_cleanup",)
