"""Domain identity for the memory_scopes feature capsule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FEATURE_ID: Final = "memory_scopes"


@dataclass(frozen=True, slots=True)
class MemoryScopesFeature:
    """Stable domain identity for the memory_scopes business capability."""

    feature_id: str = FEATURE_ID


__all__ = ("FEATURE_ID", "MemoryScopesFeature")
