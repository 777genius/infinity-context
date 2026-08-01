"""Stable Graphiti group identity mapping shared by write and evidence adapters."""

from __future__ import annotations

import re


def graphiti_group_id(
    space_id: str,
    memory_scope_id: str,
    *,
    prefix: str = "memory",
) -> str:
    """Map canonical scope identity to Graphiti's persisted group identifier."""

    return "__".join(
        (
            _safe_group_id_part(prefix),
            _safe_group_id_part(space_id),
            _safe_group_id_part(memory_scope_id),
        )
    )


def _safe_group_id_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "default"


__all__ = ("graphiti_group_id",)
