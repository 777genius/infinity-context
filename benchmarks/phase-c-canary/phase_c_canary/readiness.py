from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CanaryPhase(StrEnum):
    READINESS_CALIBRATION = "readiness_calibration"
    FACTUAL_CANARY = "factual_canary"


@dataclass(frozen=True, slots=True)
class ReadinessPolicy:
    phase: CanaryPhase
    historical_conservative_token_ceiling: int | None = None

    def __post_init__(self) -> None:
        ceiling = self.historical_conservative_token_ceiling
        if ceiling is not None and ceiling <= 0:
            raise ValueError("historical conservative ceiling must be positive")


def default_readiness_policy() -> ReadinessPolicy:
    # This is intentionally a ceiling, not a baseline or expected exact usage.
    return ReadinessPolicy(
        phase=CanaryPhase.READINESS_CALIBRATION,
        historical_conservative_token_ceiling=8063,
    )
