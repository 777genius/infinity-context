"""Compatibility parsing for trusted code-scope metadata during migration."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_core.domain.errors import MemoryValidationError


def code_scope_from_metadata(
    metadata: Mapping[str, object],
    *,
    source: str,
) -> tuple[str | None, str | None]:
    repository_id = _opaque_id(metadata, "repository_id", source=source)
    code_scope_id = _opaque_id(metadata, "code_scope_id", source=source)
    if code_scope_id is not None and repository_id is None:
        raise MemoryValidationError(f"{source} code_scope_id requires repository_id")
    return repository_id, code_scope_id


def _opaque_id(
    metadata: Mapping[str, object],
    key: str,
    *,
    source: str,
) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{source} {key} must be a non-blank string")
    normalized = value.strip()
    if "/" in normalized or "\\" in normalized or "://" in normalized or "@" in normalized:
        raise MemoryValidationError(f"{source} {key} must be an opaque identifier")
    return normalized


__all__ = ("code_scope_from_metadata",)
