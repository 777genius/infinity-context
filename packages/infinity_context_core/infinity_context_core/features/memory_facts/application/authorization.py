"""Application authorization invariants for code-scoped fact mutations."""

from __future__ import annotations

from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    MemoryFactSnapshot,
)


def require_authorized_code_scope(
    fact: MemoryFactSnapshot,
    authorized: FactCodeScopeReference | None,
) -> None:
    """Fail closed when a caller is locked to a repository or narrower code scope."""

    if authorized is None:
        return
    actual = fact.code_scope
    if actual is None or actual.repository_id != authorized.repository_id:
        raise PermissionError("Fact is outside the authorized CodeRepository")
    if authorized.code_scope_id is not None and actual.code_scope_id != authorized.code_scope_id:
        raise PermissionError("Fact is outside the authorized CodeScope")


__all__ = ("require_authorized_code_scope",)
