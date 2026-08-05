"""Domain identity for the cognitive_memory feature capsule."""

from dataclasses import dataclass
from typing import Final

FEATURE_ID: Final = "cognitive_memory"


@dataclass(frozen=True, slots=True)
class CognitiveMemoryFeature:
    feature_id: str = FEATURE_ID
