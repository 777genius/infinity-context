"""Stable lock ordering shared by multi-fact application flows."""

from __future__ import annotations

from infinity_context_core.features.memory_facts.domain import MemoryFactIdentity


def memory_fact_identity_lock_key(
    identity: MemoryFactIdentity,
) -> tuple[str, str, str, str]:
    return (
        identity.scope.space_id,
        identity.scope.memory_scope_id,
        identity.scope.thread_id or "",
        identity.fact_id,
    )


__all__ = ("memory_fact_identity_lock_key",)
