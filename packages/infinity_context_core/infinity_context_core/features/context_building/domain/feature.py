"""Domain identity for the context_building feature capsule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FEATURE_ID: Final = "context_building"


@dataclass(frozen=True, slots=True)
class ContextBuildingFeature:
    """Stable domain identity for the context_building business capability."""

    feature_id: str = FEATURE_ID
