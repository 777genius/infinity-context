"""Domain identity for the memory_facts feature capsule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FEATURE_ID: Final = "memory_facts"


@dataclass(frozen=True, slots=True)
class MemoryFactsFeature:
    """Stable domain identity for the memory_facts business capability."""

    feature_id: str = FEATURE_ID
