"""Result contract for active Retrieval reconciliation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActiveReconciliationResult:
    complete: bool
    renewed: bool
    runtime_instance_id: str | None = None
    runtime_generation: str | None = None
    release_identity_sha256: str | None = None
    lifecycle_identity_sha256: str | None = None
    outcome: str = "skipped"


__all__ = ("ActiveReconciliationResult",)
