"""Canonical registration authority for the managed HTTP reset lifecycle."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx

from infinity_context_server.memory_comparison_clean_state import (
    BackendCleanStateProof,
    fresh_namespace_clean_state_proof,
)
from infinity_context_server.memory_comparison_clean_state_http import InfinityCleanStateSession
from infinity_context_server.memory_comparison_full_profiles import INFINITY_COMPARISON_BACKEND
from infinity_context_server.memory_comparison_managed_benchmark_registry_contracts import (
    ManagedBenchmarkRunRegistration,
)


def validate_benchmark_registration(
    value: object,
    *,
    run_id: str,
    binding_commitment_sha256: str,
    target_pairs: tuple[tuple[str, str], ...],
    space_slug: str,
) -> ManagedBenchmarkRunRegistration | None:
    """Validate the exact fresh canonical namespace registration, when supplied."""

    if value is None:
        return None
    infinity_targets = tuple(target for role, target in target_pairs if role == "infinity-context")
    if (
        type(value) is not ManagedBenchmarkRunRegistration
        or value.created is not True
        or value.state != "active"
        or value.run_id_sha256 != hashlib.sha256(run_id.encode()).hexdigest()
        or value.binding_commitment_sha256 != binding_commitment_sha256
        or len(infinity_targets) != 1
        or value.infinity_target_identity_sha256 != infinity_targets[0]
        or value.space_slug != space_slug
    ):
        raise ValueError("managed_http_lifecycle_registry_invalid")
    return value


def infinity_clean_state_proofs(
    *,
    registration: ManagedBenchmarkRunRegistration | None,
    run_id: str,
    slug: str,
    corpus_hashes: tuple[str, ...],
    expected_scope_count: int,
    attestation_key: bytes,
    client_factory: Callable[[], httpx.Client],
) -> tuple[BackendCleanStateProof, ...]:
    """Prove a registered namespace or create it once through the canonical API."""

    if registration is not None:
        return tuple(
            fresh_namespace_clean_state_proof(
                backend=INFINITY_COMPARISON_BACKEND,
                run_id=run_id,
                expected_slug=slug,
                corpus_identity_sha256=corpus_hash,
                expected_scope_count=expected_scope_count,
                status_code=201,
                payload={"data": {"slug": slug}},
                attestation_key=attestation_key,
            )
            for corpus_hash in corpus_hashes
        )

    session = InfinityCleanStateSession(backend=INFINITY_COMPARISON_BACKEND)
    client = client_factory()
    try:
        first = session.reset(
            client,
            run_id=run_id,
            slug=slug,
            corpus_identity_sha256=corpus_hashes[0],
            expected_scope_count=expected_scope_count,
            attestation_key=attestation_key,
        )
    finally:
        client.close()
    return (
        first,
        *(
            fresh_namespace_clean_state_proof(
                backend=INFINITY_COMPARISON_BACKEND,
                run_id=run_id,
                expected_slug=slug,
                corpus_identity_sha256=corpus_hash,
                expected_scope_count=expected_scope_count,
                status_code=201,
                payload={"data": {"slug": slug}},
                attestation_key=attestation_key,
            )
            for corpus_hash in corpus_hashes[1:]
        ),
    )


__all__ = ("infinity_clean_state_proofs", "validate_benchmark_registration")
